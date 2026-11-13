"""Despesas pelo agente de voz (Plano 8, fase 2b): o que falta pagar, anotar despesa e pagamento por voz.

Mesmo padrão de `compras.py`: a despesa chega pelo nome falado ("luz", "a internet", "o gás") e é resolvida aqui
— "luz" casa com a despesa mensal Energia ou com a categoria Energia; ambíguo vira `ConsultaInvalida` com
`opcoes`. O mês é falado ("este mês", "mês passado", "outubro") e as datas também ("hoje", "ontem", "dia 20").
Consultas devolvem os dados e um `texto` curto para falar, com dinheiro por extenso e datas faladas; os totais
vêm prontos de `financeiro.consultas` (o modelo de voz não faz conta). Despesa sem valor é dita "sem valor",
nunca zero.

Alçada (Plano 8, Q8): ler é nível 0; informar o valor de uma despesa do mês ("a internet veio 99,90") é nível 1
(contrato da fase 2: corrige o previsto, não movimenta nada e se refaz falando de novo); anotar pagamento,
lançar despesa avulsa e cancelar despesa (com motivo) são nível 2 — proposta simulada pelo núcleo e só grava com
`confirmar_proposta`. O sistema nunca paga nada: só anota que o dono pagou. Cadastro e alteração de despesa
mensal (previsto, dia, categoria), categorias, canais, taxas, referências e preço: só pela tela.
"""

import calendar
import re
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from financeiro import consultas as fc
from financeiro.despesas import informar_valor_despesa as _informar_valor
from financeiro.models import CategoriaDespesa, Conta, DespesaDoMes, DespesaMensal

from .acoes import _decimal, _feito, _proposta, _uma_vez
from .compras import MESES, _juntar, _n, _sem_valor, dia_falado, mes_falado, reais
from .consultas import ConsultaInvalida, _inteiro, _normal

ZERO = Decimal("0")
CENTAVO = Decimal("0.01")
MAX_FALADOS = 3  # despesas lidas em cada parte do `texto`; o resto fica nos dados

# --- mês e datas faladas ----------------------------------------------------------------

_SEM_SENTIDO_MES = {"este", "esse", "neste", "nesse", "deste", "desse", "o", "no", "do", "de", "da", "em", "mes",
                    "mês", "atual", "corrente"}
_MESES_NORMAIS = [_normal(m) for m in MESES]


def _mes_seguinte(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def _ultimo_dia(competencia: date) -> date:
    return competencia.replace(day=calendar.monthrange(competencia.year, competencia.month)[1])


def _competencia(valor) -> date:
    """Dia 1 do mês falado: vazio/"este mês" → o mês de hoje; "mês passado"; "próximo mês"; "outubro" (o último
    outubro até hoje), "outubro de 2025"; ou AAAA-MM."""
    hoje = timezone.localdate()
    este = hoje.replace(day=1)
    bruto = str(valor or "").strip()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", bruto):
        ano, mes = int(m.group(1)), int(m.group(2))
        if 1 <= mes <= 12:
            return date(ano, mes, 1)
    palavras = [p for p in re.split(r"[\s_\-]+", _normal(bruto)) if p and p not in _SEM_SENTIDO_MES]
    if not palavras:
        return este
    if palavras[0] in ("passado", "anterior", "ultimo"):
        return (este - timedelta(days=1)).replace(day=1)
    if palavras[0] in ("proximo", "seguinte", "que"):
        return _mes_seguinte(este)
    if palavras[0] in _MESES_NORMAIS:
        mes = _MESES_NORMAIS.index(palavras[0]) + 1
        if len(palavras) > 1 and palavras[-1].isdigit() and len(palavras[-1]) == 4:
            return date(int(palavras[-1]), mes, 1)
        return date(hoje.year if mes <= hoje.month else hoje.year - 1, mes, 1)
    raise ConsultaInvalida(f"Não conheço o mês '{valor}'. Diga este mês, mês passado, o nome do mês (outubro) "
                           "ou AAAA-MM.")


def _data(valor, nome, *, passado) -> date | None:
    """Data falada: hoje, ontem, anteontem, amanhã, "dia 20" (no mês de hoje; se já passou e é vencimento, no
    próximo; se ainda não chegou e é pagamento, no anterior), "20 de dezembro" ou AAAA-MM-DD."""
    bruto = str(valor or "").strip()
    if not bruto:
        return None
    hoje = timezone.localdate()
    v = " ".join(_normal(bruto).replace("-", " ").split())
    perto = {"hoje": 0, "ontem": -1, "anteontem": -2, "amanha": 1, "depois de amanha": 2}
    if v in perto:
        return hoje + timedelta(days=perto[v])
    try:
        return date.fromisoformat(bruto)
    except ValueError:
        pass
    m = re.fullmatch(r"(?:dia )?(\d{1,2})(?: de ([a-z]+)(?: de (\d{4}))?)?", v)
    if m:
        dia = int(m.group(1))
        try:
            if m.group(2):
                if m.group(2) not in _MESES_NORMAIS:
                    raise ValueError
                mes = _MESES_NORMAIS.index(m.group(2)) + 1
                if m.group(3):
                    return date(int(m.group(3)), mes, dia)
                d = date(hoje.year, mes, dia)
                if passado and d > hoje:
                    d = date(hoje.year - 1, mes, dia)
                elif not passado and d < hoje:
                    d = date(hoje.year + 1, mes, dia)
                return d
            base = hoje.replace(day=1)
            if passado and dia > hoje.day:
                base = (base - timedelta(days=1)).replace(day=1)
            elif not passado and dia < hoje.day:
                base = _mes_seguinte(base)
            return base.replace(day=dia)
        except ValueError:
            pass
    raise ConsultaInvalida(f"Não entendi a data '{valor}' em '{nome}'. Diga hoje, ontem, amanhã, dia 20, "
                           "20 de dezembro ou AAAA-MM-DD.")


def _valor(v, nome="valor") -> Decimal | None:
    if _sem_valor(v):
        return None
    d = _decimal(v, nome).quantize(CENTAVO)
    if d <= 0:
        raise ConsultaInvalida(f"O {nome} deve ser maior que zero.")
    return d


# --- nome falado ----------------------------------------------------------------------------

_VAZIAS = {"conta", "contas", "boleto", "fatura", "da", "de", "do", "das", "dos", "a", "o", "as", "os", "e", "pra",
           "pro", "para", "mes", "mensal", "despesa", "despesas", "pagamento", "valor", "com", "no", "na", "este",
           "esse", "deste", "desse"}
# como o dono fala → como está no cadastro (sem acento)
_TROCAS = {"luz": "energia", "eletrica": "energia", "eletricidade": "energia", "botijao": "gas", "botijoes": "gas",
           "diarista": "diaria", "faxina": "diaria", "faxineira": "diaria", "salario": "funcionario",
           "imposto": "impostos", "wifi": "internet"}


def _palavras(texto) -> list[str]:
    toks = [t for t in re.split(r"[\s,;()/—\-]+", _normal(texto or "")) if t]
    palavras = [_TROCAS.get(t, t) for t in toks if t not in _VAZIAS]
    if not palavras and "das" in toks:  # "paguei o DAS"
        palavras = ["impostos"]
    return palavras


def _casa(busca, rotulo) -> bool:
    ws, n = _palavras(busca), _normal(rotulo)
    return bool(ws) and all(w in n for w in ws)


def _escolher(candidatos, busca, *, rotulo):
    """Os candidatos que casam com o nome falado; nome idêntico ganha dos parciais."""
    achados = [c for c in candidatos if _casa(busca, rotulo(c))]
    exatos = [c for c in achados if " ".join(_palavras(busca)) == " ".join(_palavras(c["nome"]))]
    return exatos or achados


def _categoria(nome, *, obrigatoria=True) -> CategoriaDespesa | None:
    cats = list(CategoriaDespesa.objects.filter(ativa=True))
    if (nome or "").strip():
        achadas = [c for c in cats if _casa(nome, c.nome)]
        exatas = [c for c in achadas if " ".join(_palavras(nome)) == " ".join(_palavras(c.nome))]
        achadas = exatas or achadas
        if len(achadas) == 1:
            return achadas[0]
        if len(achadas) > 1:
            raise ConsultaInvalida(f"Mais de uma categoria de despesa com '{nome}'; pergunte qual.", 409,
                                   opcoes=[c.nome for c in achadas])
    if not obrigatoria:
        return None
    raise ConsultaInvalida("De que categoria é essa despesa? Pergunte ao dono e passe em 'categoria'.", 409,
                           opcoes=[c.nome for c in cats])


# --- as despesas como se fala ---------------------------------------------------------------

def _mensal(d) -> dict:
    """Despesa do mês (de `despesas_do_mes`/`despesas_sem_valor`) no formato comum do agente."""
    return {"tipo": "mensal", "despesa_do_mes_id": d["despesa_do_mes_id"], "conta_id": d["conta_id"],
            "parcela_id": d["parcela_id"], "nome": d["despesa"], "categoria": d["categoria"],
            "competencia": d["competencia"], "vencimento": d["vencimento"], "valor": d["valor"], "pago": d["pago"],
            "saldo": d["saldo"], "situacao": d["situacao"], "vencida": d["vencida"],
            "rotulo": f"{d['despesa']} de {mes_falado(d['competencia'])}"}


def _avulsa(d) -> dict:
    return {"tipo": "avulsa", "despesa_do_mes_id": None, "conta_id": d["conta_id"], "parcela_id": d["parcela_id"],
            "nome": d["descricao"], "categoria": d["categoria"], "competencia": d["competencia"],
            "vencimento": d["vencimento"], "valor": d["valor"], "pago": d["pago"], "saldo": d["saldo"],
            "situacao": d["situacao"], "vencida": d["vencida"], "rotulo": d["descricao"]}


def _do_mes(competencia) -> list[dict]:
    m = fc.despesas_do_mes(competencia=competencia)
    return [_mensal(d) for d in m["mensais"]] + [_avulsa(d) for d in m["avulsas"]]


def _situacao_txt(d) -> str:
    """"850 reais, vence dia 10", "sem valor, venceu ontem", "230 reais, paga"."""
    if d["situacao"] == "sem_valor":
        return f"sem valor, {'venceu' if d['vencida'] else 'vence'} {dia_falado(d['vencimento'])}"
    if d["situacao"] == "paga":
        return f"{reais(d['valor'])}, paga"
    if d["situacao"] == "cancelada":
        return f"{reais(d['valor'])}, cancelada"
    t = f"{reais(d['saldo'])}"
    if d["situacao"] == "parcial":
        t += f" faltando de {reais(d['valor'])}"
    return t + f", {'venceu' if d['vencida'] else 'vence'} {dia_falado(d['vencimento'])}"


def _opcao(d) -> str:
    return f"{d['rotulo']}, {_situacao_txt(d)}"


def _ate_tres(frases) -> str:
    frases = list(frases)
    sobra = len(frases) - MAX_FALADOS
    return "; ".join(frases[:MAX_FALADOS]) + (f"; e mais {sobra}" if sobra > 0 else "")


def _curta(d) -> dict:
    return {k: (v.isoformat() if isinstance(v, date) else float(v) if isinstance(v, Decimal) else v)
            for k, v in d.items()}


# --- consultas (nível 0) ---------------------------------------------------------------------

def ver_despesas(mes=""):
    comp = _competencia(mes)
    m = fc.despesas_do_mes(competencia=comp)
    t = m["totais"]
    por = fc.despesas_periodo(de=comp, ate=_ultimo_dia(comp))["por_categoria"]
    todas = [_mensal(d) for d in m["mensais"]] + [_avulsa(d) for d in m["avulsas"]]
    validas = [d for d in todas if d["situacao"] != "cancelada"]
    nome_mes = mes_falado(comp)
    if not validas:
        texto = f"Nenhuma despesa lançada em {nome_mes}."
        if not DespesaMensal.objects.filter(ativa=True).exists():
            texto += " Não há despesa mensal cadastrada; as contas que se repetem se cadastram pela tela."
    else:
        texto = f"Despesas de {nome_mes}: {reais(t['valor'])} lançados"
        if t["falta_pagar"] > 0:
            texto += (f", {reais(t['pago'])} já com pagamento anotado" if t["pago"] > 0 else ", nenhum pago ainda")
            texto += f", falta pagar {reais(t['falta_pagar'])}."
        elif t["valor"] > 0:
            texto += ", tudo com pagamento anotado."
        else:
            texto += "."
        sem = [d for d in validas if d["situacao"] == "sem_valor"]
        if sem:
            texto += (f" Ainda sem valor, fora da conta: {_juntar([d['nome'] for d in sem])}; quando a conta chegar, "
                      "é só dizer o valor.")
        vencidas = [d for d in validas if d["vencida"]]
        if vencidas:
            texto += " Vencidas: " + _ate_tres(f"{d['nome']}, {_situacao_txt(d)}" for d in vencidas) + "."
        a_pagar = [d for d in validas if d["situacao"] in ("aberta", "parcial") and not d["vencida"]]
        if a_pagar:
            texto += " A pagar: " + _ate_tres(f"{d['nome']}, {_situacao_txt(d)}" for d in a_pagar) + "."
        if por:
            texto += " Por categoria: " + _ate_tres(f"{g['categoria']}, {reais(g['valor'])}" for g in por) + "."
    return {"competencia": comp.isoformat(), "mes": nome_mes,
            "totais": _curta({k: t[k] for k in ("valor", "pago", "falta_pagar", "sem_valor", "completo", "vencidas")}),
            "despesas": [_curta({k: d[k] for k in ("tipo", "despesa_do_mes_id", "conta_id", "nome", "categoria",
                                                   "vencimento", "valor", "pago", "saldo", "situacao", "vencida")})
                         for d in todas],
            "por_categoria": [_curta({k: g[k] for k in ("categoria", "indireta", "valor", "lancamentos", "completo")})
                              for g in por],
            "texto": texto}


_SITUACOES = {"todas": "todas", "tudo": "todas", "aberta": "todas", "abertas": "todas", "vencidas": "vencidas",
              "vencida": "vencidas", "atrasadas": "vencidas", "atrasada": "vencidas"}


def ver_despesas_a_pagar(situacao="todas"):
    tipo = _SITUACOES.get(_normal(situacao or "todas"))
    if tipo is None:
        raise ConsultaInvalida("'situacao' deve ser todas ou vencidas.")
    e = fc.despesas_em_aberto()
    todas = _em_aberto()
    vencidas = [d for d in todas if d["vencida"]]
    lista = vencidas if tipo == "vencidas" else todas
    if not lista:
        texto = ("Nenhuma despesa vencida." if tipo == "vencidas"
                 else "Nenhuma despesa em aberto: tudo com pagamento anotado.")
    else:
        vencido = sum((d["saldo"] for d in vencidas if d["saldo"] is not None), ZERO)
        if tipo == "todas":
            texto = (f"Falta pagar {reais(e['total'])} de despesas"
                     + (f", {reais(vencido)} já vencidos" if vencido else "") + ".")
        else:
            texto = (f"{_n(len(vencidas), 'despesa vencida', 'despesas vencidas')}"
                     + (f", somando {reais(vencido)}" if vencido else "") + ".")
        sem = [d for d in lista if d["situacao"] == "sem_valor"]
        if sem:
            texto += f" Sem valor ainda, fora da soma: {_juntar([d['rotulo'] for d in sem])}."
        texto += " " + _ate_tres(f"{d['rotulo']}, {_situacao_txt(d)}" for d in lista) + "."
    return {"situacao": tipo, "total": float(e["total"]), "completo": e["completo"],
            "despesas": [_curta({k: d[k] for k in ("tipo", "rotulo", "despesa_do_mes_id", "conta_id", "categoria",
                                                   "valor", "saldo", "situacao", "vencimento", "vencida")})
                         for d in lista],
            "texto": texto}


# --- resolução para gravar -----------------------------------------------------------------

def _em_aberto(mes="") -> list[dict]:
    """Despesas que ainda esperam pagamento (do mês falado ou, sem mês, de qualquer mês até o atual): mensais sem
    valor ou com saldo e avulsas a pagar."""
    if (mes or "").strip():
        return [d for d in _do_mes(_competencia(mes)) if d["situacao"] in ("sem_valor", "aberta", "parcial")]
    e = fc.despesas_em_aberto()
    mensais = {dm.conta_id: dm for dm in DespesaDoMes.objects.filter(
        conta_id__in=[p["conta_id"] for p in e["parcelas"]]).select_related("despesa__categoria")}
    saida = [_mensal(d) for d in e["sem_valor"]]
    for p in e["parcelas"]:
        dm = mensais.get(p["conta_id"])
        if dm is None:
            saida.append({"tipo": "avulsa", "despesa_do_mes_id": None, "conta_id": p["conta_id"],
                          "parcela_id": p["parcela_id"], "nome": p["descricao"], "categoria": p["categoria"],
                          "competencia": p["competencia"], "vencimento": p["vencimento"], "valor": p["valor"],
                          "pago": p["pago"], "saldo": p["saldo"], "situacao": p["situacao"], "vencida": p["vencida"],
                          "rotulo": p["descricao"]})
        else:
            saida.append({"tipo": "mensal", "despesa_do_mes_id": dm.id, "conta_id": p["conta_id"],
                          "parcela_id": p["parcela_id"], "nome": dm.despesa.nome, "categoria": p["categoria"],
                          "competencia": dm.competencia, "vencimento": p["vencimento"], "valor": p["valor"],
                          "pago": p["pago"], "saldo": p["saldo"], "situacao": p["situacao"], "vencida": p["vencida"],
                          "rotulo": f"{dm.despesa.nome} de {mes_falado(dm.competencia)}"})
    return sorted(saida, key=lambda d: (d["vencimento"], d["nome"]))


def _rotulo(d) -> str:
    return f"{d['nome']} {d['categoria']}"


def _uma(candidatos, nome, *, pergunta):
    achados = _escolher(candidatos, nome, rotulo=_rotulo)
    if len(achados) > 1:
        raise ConsultaInvalida(pergunta, 409, opcoes=[_opcao(d) for d in achados])
    return achados[0] if achados else None


def _forma_txt(forma) -> str:
    f = (forma or "").strip()
    return f", no {f}" if f else ""


# --- nível 2: anotar pagamento e lançar despesa ------------------------------------------------

def _propor_lancar(*, descricao, cat, valor, paga, dia, vencimento, forma, autor, canal):
    desc = (descricao or "").strip()
    desc = desc[:1].upper() + desc[1:]
    parametros = {"descricao": desc, "categoria_id": cat.id, "valor": valor, "paga": paga,
                  "data_pagamento": dia if paga else None, "vencimento": None if paga else vencimento,
                  "forma": (forma or "").strip()}

    def resumir(r):
        t = f"Lançar a despesa {desc}, em {cat.nome}: {reais(valor)}, "
        t += (f"paga {dia_falado(dia)}{_forma_txt(forma)}" if paga
              else f"a pagar, vence {dia_falado(vencimento)}")
        if r.get("parecidas"):
            nomes = _juntar([p["despesa"] for p in r["parecidas"]])
            t += (f". Atenção: {nomes} deste mês ainda está em aberto como despesa mensal; se for a mesma conta, "
                  "diga não e anote o pagamento nela")
        return t

    return _proposta("lancar_despesa", parametros, resumir, autor, canal)


def propor_pagar_despesa(*, nome, valor=None, data_pagamento="", forma="", mes="", categoria="", autor, canal):
    if not (nome or "").strip():
        raise ConsultaInvalida("Diga qual despesa foi paga (ex.: luz, internet, gás).")
    v = _valor(valor)
    dia = _data(data_pagamento, "data_pagamento", passado=True) or timezone.localdate()
    if dia > timezone.localdate():
        raise ConsultaInvalida("O pagamento não pode ser numa data que ainda não chegou.")
    d = _uma(_em_aberto(mes), nome, pergunta=f"Mais de uma despesa em aberto com '{nome}'; pergunte qual "
                                               "(e passe o mês em 'mes', se for de outro mês).")
    if d is None:
        pagas = _escolher([x for x in _do_mes(_competencia(mes)) if x["situacao"] == "paga"], nome, rotulo=_rotulo)
        if pagas and not (categoria or "").strip():
            p = pagas[0]
            raise ConsultaInvalida(f"{p['rotulo']} já está com pagamento anotado ({reais(p['valor'])}). Se for "
                                   "outra conta, pergunte se é uma despesa nova e use lancar_despesa.", 409)
        if v is None:
            raise ConsultaInvalida(f"Quanto foi pago de {nome.strip()}? Diga o valor.")
        cat = _categoria(categoria or nome)
        return _propor_lancar(descricao=nome, cat=cat, valor=v, paga=True, dia=dia, vencimento=None, forma=forma,
                              autor=autor, canal=canal)
    if d["tipo"] == "avulsa":
        if v is not None and v > d["saldo"]:
            raise ConsultaInvalida(f"{d['rotulo']} está lançada com {reais(d['saldo'])} a pagar; o valor dito passa "
                                   "disso. Se o valor da conta estava errado, cancele e lance de novo.", 409)
        parametros = {"parcela_id": d["parcela_id"], "valor": v, "data_pagamento": dia, "forma": (forma or "").strip(),
                      "diferenca": 0, "diferenca_tipo": "", "diferenca_motivo": ""}

        def resumir(r):
            t = f"Anotar o pagamento da despesa {d['rotulo']}: {reais(r['valor_pago'])}, paga {dia_falado(dia)}"
            t += _forma_txt(forma)
            return t + (". Fica quitada" if r["situacao"] == "paga" else f". Ficam faltando {reais(r['saldo'])}")

        return _proposta("registrar_pagamento", parametros, resumir, autor, canal)
    if v is None and d["situacao"] == "sem_valor":
        raise ConsultaInvalida(f"{d['rotulo']} ainda não tem valor: pergunte quanto foi pago.")
    parametros = {"despesa_do_mes_id": d["despesa_do_mes_id"], "valor": v, "data_pagamento": dia,
                  "forma": (forma or "").strip()}

    def resumir(r):
        t = f"Anotar o pagamento de {d['rotulo']}: {reais(r['valor_pago'])}, paga {dia_falado(dia)}{_forma_txt(forma)}"
        if d["valor"] is None:
            t += " (ela ainda não tinha valor; fica este)"
        elif v is not None and v != d["valor"]:
            t += f" (estava lançada com {reais(d['valor'])}; fica o valor real)"
        return t + (". Fica quitada" if r["situacao"] == "paga" else f". Ficam faltando {reais(r['saldo'])}")

    return _proposta("pagar_despesa_do_mes", parametros, resumir, autor, canal)


def propor_lancar_despesa(*, descricao, valor, categoria="", vencimento="", paga=False, data_pagamento="", forma="",
                          autor, canal):
    if not (descricao or "").strip():
        raise ConsultaInvalida("Diga do que é a despesa (ex.: gás, diarista, conserto da fritadeira).")
    v = _valor(valor)
    if v is None:
        raise ConsultaInvalida("Diga o valor da despesa.")
    cat = _categoria(categoria or descricao)
    hoje = timezone.localdate()
    if paga:
        dia = _data(data_pagamento, "data_pagamento", passado=True) or hoje
        if dia > hoje:
            raise ConsultaInvalida("O pagamento não pode ser numa data que ainda não chegou.")
        venc = None
    else:
        dia = None
        venc = _data(vencimento, "vencimento", passado=False)
        if venc is None:
            raise ConsultaInvalida("Quando vence? Diga o dia (ou, se já foi paga, diga que já pagou).")
    # a mesma conta já existe como despesa mensal deste mês, ainda em aberto: não lançar em dobro
    mensais = [d for d in _do_mes(hoje) if d["tipo"] == "mensal" and d["situacao"] in ("sem_valor", "aberta", "parcial")]
    iguais = _escolher(mensais, descricao, rotulo=lambda d: d["nome"])
    if iguais:
        d = iguais[0]
        acao = ("anote o pagamento nela (pagar_despesa)" if paga
                else "diga o valor dela (informar_valor_despesa)" if d["situacao"] == "sem_valor"
                else "ela já está nas contas a pagar")
        raise ConsultaInvalida(f"{d['rotulo']} já é uma despesa mensal, {_situacao_txt(d)}: {acao}. Se for outra "
                               "conta, lance com uma descrição diferente.", 409)
    return _propor_lancar(descricao=descricao, cat=cat, valor=v, paga=paga, dia=dia, vencimento=venc, forma=forma,
                          autor=autor, canal=canal)


def propor_cancelar_despesa(*, motivo, nome="", mes="", conta_id=None, autor, canal):
    texto = (motivo or "").strip()
    if not texto:
        raise ConsultaInvalida("Por que cancelar? O motivo é obrigatório: pergunte ao dono.")
    if conta_id:
        cid = _inteiro(conta_id, "conta_id")
        conta = Conta.objects.filter(id=cid, origem="despesa").first()
        achada = [d for d in _do_mes(conta.competencia) if d["conta_id"] == cid] if conta and conta.competencia else []
        if not achada:
            raise ConsultaInvalida("Despesa não encontrada.", 404)
        d = achada[0]
    else:
        if not (nome or "").strip():
            raise ConsultaInvalida("Diga qual despesa cancelar.")
        if (mes or "").strip():
            meses = [_competencia(mes)]
        else:
            este = timezone.localdate().replace(day=1)
            meses = [este, (este - timedelta(days=1)).replace(day=1)]
        todas = [d for c in meses for d in _do_mes(c) if d["situacao"] != "cancelada"]
        achados = _escolher(todas, nome, rotulo=_rotulo)
        if not achados:
            raise ConsultaInvalida(f"Nenhuma despesa com '{nome}' em {_juntar([mes_falado(c) for c in meses])}.", 404)
        com_conta = [d for d in achados if d["conta_id"]]
        if not com_conta:
            raise ConsultaInvalida(f"{achados[0]['rotulo']} ainda não tem valor: não há conta para cancelar por voz.",
                                   409)
        if len(com_conta) > 1:
            raise ConsultaInvalida(f"Mais de uma despesa com '{nome}'; pergunte qual (conta_id).", 409,
                                   opcoes=[f"Despesa {d['conta_id']}: {_opcao(d)}" for d in com_conta])
        d = com_conta[0]

    def resumir(r):
        t = f"Cancelar a despesa {d['rotulo']}, {reais(d['valor'])} (motivo: {texto})"
        if r["pagamentos_estornados"]:
            t += f". O pagamento anotado de {reais(d['pago'])} é estornado junto"
        return t + ". Ela sai das contas a pagar e do resultado"

    return _proposta("cancelar_despesa", {"conta_id": d["conta_id"], "motivo": texto}, resumir, autor, canal)


# --- nível 1: o valor da conta do mês -----------------------------------------------------------

def informar_valor_despesa(*, nome, valor, mes="", autor, canal):
    if not (nome or "").strip():
        raise ConsultaInvalida("Diga de qual despesa é o valor (ex.: internet, luz).")
    v = _valor(valor)
    if v is None:
        raise ConsultaInvalida("Diga o valor da conta.")
    if (mes or "").strip():
        mensais = [d for d in _do_mes(_competencia(mes)) if d["tipo"] == "mensal" and d["situacao"] != "cancelada"]
    else:
        mensais = [d for d in _em_aberto() if d["tipo"] == "mensal"]
        if not _escolher(mensais, nome, rotulo=_rotulo):  # já paga neste mês: o núcleo diz o que fazer
            mensais = [d for d in _do_mes(timezone.localdate()) if d["tipo"] == "mensal" and d["situacao"] == "paga"]
    achados = _escolher(mensais, nome, rotulo=_rotulo)
    if not achados:
        raise ConsultaInvalida(f"Nenhuma despesa mensal em aberto com '{nome}'. Despesa nova se lança com "
                               "lancar_despesa; despesa mensal nova só pela tela.", 404)
    if len(achados) > 1:
        raise ConsultaInvalida(f"Mais de uma despesa mensal com '{nome}'; pergunte qual (e o mês, se for outro).",
                               409, opcoes=[_opcao(d) for d in achados])
    d = achados[0]
    r, rep = _uma_vez("informar_valor_despesa", {"despesa_do_mes": d["despesa_do_mes_id"], "valor": str(v)},
                      lambda chave: _informar_valor(despesa_do_mes_id=d["despesa_do_mes_id"], valor=v, autor=autor,
                                                    canal=canal, chave=chave))
    anterior = None if r["valor_anterior"] is None else Decimal(str(r["valor_anterior"]))
    dito = f"Anotado: {d['rotulo']} veio {reais(v)}"
    if anterior is not None and anterior != v:
        dito += f"; estava lançada com {reais(anterior)}"
    elif anterior is not None:
        dito += ", o mesmo valor que já estava"
    dito += (f". {'Venceu' if d['vencida'] else 'Vence'} {dia_falado(d['vencimento'])}, ainda sem pagamento "
             "anotado.")
    return _feito(dito, r, rep, despesa_do_mes_id=d["despesa_do_mes_id"])
