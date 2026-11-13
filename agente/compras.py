"""Compras, recebimento e contas a pagar pelo agente (Plano 3, fase 2b).

Mesmo padrão de `acoes.py`: tudo chega pelo nome falado (fornecedor, item) e é
resolvido aqui — ambíguo vira `ConsultaInvalida` com `opcoes`. Consultas
devolvem os dados enxutos e um `texto` pronto para falar, com totais já
somados pelo sistema. Gravações com dinheiro ou estoque são nível 2
(proposta simulada pelo núcleo); cadastrar fornecedor e resolver aviso são
nível 1. Nenhuma regra de negócio aqui: custos, saldos, parcelas e recusas
vêm de `compras`, `financeiro`, `estoque` e `producao`.
"""

import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from cadastros.models import Conversao, Fornecedor, Item
from cadastros.servicos import salvar_fornecedor
from compras import consultas as cc
from compras.models import Compra, Recebimento
from estoque.models import ConsumoPendente, Lote
from estoque.servicos import consumos_pendentes, saldo_lote
from financeiro import consultas as fc
from financeiro.models import AvisoAjuste
from financeiro.servicos import dividir_parcelas, resolver_aviso as _resolver_aviso
from web.templatetags.formato import quantidade as fmt_qtd

from .acoes import _data, _decimal, _feito, _proposta, _uma_vez
from .consultas import ConsultaInvalida, _casa, _filtrar, _inteiro, _normal, escolher

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")
CENTAVO = Decimal("0.01")
MAX_FALADOS = 5  # itens lidos no `texto`; o resto vira "e mais N"

_UNIDADES = {"quilo": "kg", "kilo": "kg", "quilograma": "kg", "kg": "kg", "grama": "g", "g": "g",
             "litro": "L", "l": "L", "mililitro": "mL", "ml": "mL", "unidade": "un", "un": "un"}
_POR = {"g": (1000, "o quilo"), "mL": (1000, "o litro"), "un": (1, "a unidade")}


# --- fala -------------------------------------------------------------------

def reais(v) -> str:
    """Dinheiro como se fala: "90 reais", "1 real e 50 centavos", "1.234 reais"."""
    q = Decimal(str(v)).quantize(CENTAVO, ROUND_HALF_UP)
    sinal, q = ("menos " if q < 0 else ""), abs(q)
    inteiro, centavos = int(q), int((q % 1) * 100)
    partes = []
    if inteiro:
        partes.append(f"{inteiro:,}".replace(",", ".") + (" real" if inteiro == 1 else " reais"))
    if centavos:
        partes.append(f"{centavos} centavo" + ("s" if centavos > 1 else ""))
    return sinal + (" e ".join(partes) or "zero real")


def _dia(d) -> date:
    return d if isinstance(d, date) else date.fromisoformat(str(d))


def quando(d) -> str:
    """"hoje", "amanhã", "ontem" ou "em 12 de dezembro" (com o ano só se não for o atual)."""
    d, hoje = _dia(d), timezone.localdate()
    perto = {0: "hoje", 1: "amanhã", -1: "ontem"}.get((d - hoje).days)
    if perto:
        return perto
    return f"em {d.day} de {MESES[d.month - 1]}" + ("" if d.year == hoje.year else f" de {d.year}")


def mes_falado(competencia) -> str:
    """"novembro" (no ano de hoje) ou "novembro de 2025"."""
    d, hoje = _dia(competencia), timezone.localdate()
    return MESES[d.month - 1] + ("" if d.year == hoje.year else f" de {d.year}")


def dia_falado(d) -> str:
    """"hoje", "amanhã", "ontem", "dia 10" (no mês de hoje) ou "dia 2 de dezembro" — o jeito de dizer vencimento."""
    d, hoje = _dia(d), timezone.localdate()
    perto = {0: "hoje", 1: "amanhã", -1: "ontem"}.get((d - hoje).days)
    if perto:
        return perto
    if (d.year, d.month) == (hoje.year, hoje.month):
        return f"dia {d.day}"
    return f"dia {d.day} de {MESES[d.month - 1]}" + ("" if d.year == hoje.year else f" de {d.year}")


_MES_NUMERICO = re.compile(r"(\s+—\s+)?(?<![/\d])(\d{1,2})/(\d{4})\b")


def sem_mes_numerico(texto) -> str:
    """"Energia — 11/2026" → "Energia de novembro" (o núcleo escreve o mês da despesa como MM/AAAA)."""
    def troca(m):
        mes = int(m.group(2))
        if not 1 <= mes <= 12:
            return m.group(0)
        return (" de " if m.group(1) else "") + mes_falado(date(int(m.group(3)), mes, 1))
    return _MES_NUMERICO.sub(troca, texto or "")


def qtd(q, unidade) -> str:
    return fmt_qtd(Decimal(str(q)), unidade)


def _dinheiro(v) -> dict:
    return {"valor": float(v), "texto": reais(v)}


def _q(q, unidade) -> dict:
    return {"valor": float(q), "unidade": unidade, "texto": qtd(q, unidade)}


def _juntar(partes) -> str:
    partes = list(partes)
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]


def _ate_cinco(frases) -> str:
    frases = list(frases)
    resto = len(frases) - MAX_FALADOS
    return "; ".join(frases[:MAX_FALADOS]) + (f"; e mais {resto}" if resto > 0 else "") + "."


def _n(n, singular, plural=None) -> str:
    return f"{n} {singular if n == 1 else plural or singular + 's'}"


def _ha(dias) -> str:
    return "de hoje" if dias <= 0 else f"há {_n(dias, 'dia')}"


def _parcela_txt(p) -> str:
    """"parcela 1 de 3, 30 reais, vence em 12 de dezembro" a partir de um dict de `financeiro.consultas`."""
    qual = "parcela única" if p["de"] == 1 else f"parcela {p['numero']} de {p['de']}"
    if p["situacao"] == "paga":
        return f"{qual} de {reais(p['valor'])}, paga"
    verbo = "venceu" if p["vencida"] else "vence"
    return f"{qual}, {reais(p['saldo'])}, {verbo} {quando(p['vencimento'])}"


# --- resolução pelo nome ------------------------------------------------------

def _fornecedor(nome, *, ativos=True) -> Fornecedor:
    if not (nome or "").strip():
        raise ConsultaInvalida("Diga o nome do fornecedor.")
    qs = Fornecedor.objects.order_by("nome")
    return escolher(qs.filter(ativo=True) if ativos else qs, nome, oque="fornecedor")


def _item(nome) -> Item:
    """Item que se compra (ingrediente, insumo, embalagem), pelo nome falado."""
    if not (nome or "").strip():
        raise ConsultaInvalida("Diga o nome do item.")
    return escolher(Item.objects.filter(ativo=True).exclude(tipo="produto").order_by("nome"), nome, oque="item")


def _unidade(item, unidade) -> str:
    """"quilos" → kg, "litro" → L; outras (saco, caixa) como o item tem cadastrado, aceitando plural."""
    u = (unidade or "").strip()
    v = _normal(u)
    if not v:
        return ""
    sem_s = v[:-1] if v.endswith("s") else v
    if v in _UNIDADES or sem_s in _UNIDADES:
        return _UNIDADES.get(v) or _UNIDADES[sem_s]
    conv = Conversao.objects.filter(item=item, unidade__iexact=u).first() or \
        Conversao.objects.filter(item=item, unidade__iexact=u[:-1] if v.endswith("s") else u).first()
    return conv.unidade if conv else u  # sem conversão: o núcleo recusa com a mensagem certa


def _casados(busca, linhas, chave="item"):
    """Linhas cujo nome casa com o que foi dito; nome idêntico ganha das parciais."""
    achadas = [l for l in linhas if _casa(busca, l[chave])]
    exatas = [l for l in achadas if _normal(l[chave]) == _normal(busca)]
    return exatas or achadas


def _dicts(itens) -> list[dict]:
    return [dict(i) if isinstance(i, dict) else i.model_dump() for i in itens or []]


def _do(f) -> str:
    return f" do fornecedor {f.nome}" if f else ""


# --- consultas (nível 0) --------------------------------------------------------

def buscar_fornecedores(busca=""):
    fs = _filtrar(Fornecedor.objects.order_by("nome"), busca)
    if not fs:
        texto = f"Nenhum fornecedor com o nome '{busca}'." if busca else "Nenhum fornecedor cadastrado."
    else:
        texto = "Fornecedores: " + _juntar(f.nome + ("" if f.ativo else " (inativo)") for f in fs) + "."
    return {"fornecedores": [{"fornecedor_id": f.id, "nome": f.nome, "ativo": f.ativo, "contato": f.contato,
                              "documento": f.documento} for f in fs], "texto": texto}


def _falta_txt(linhas) -> str:
    return _juntar(f"{qtd(l['pendente'], l['unidade_base'])} de {l['item']}" for l in linhas)


def _compra_txt(c) -> str:
    return (f"Compra {c['compra_id']}, fornecedor {c['fornecedor']}, comprada {quando(c['data'])}: "
            f"falta {_falta_txt(c['pendentes'])}")


def ver_compras_em_aberto(fornecedor=""):
    f = _fornecedor(fornecedor, ativos=False) if fornecedor else None
    compras = cc.compras_em_aberto(fornecedor_id=f.id if f else None)
    if not compras:
        texto = f"Nenhuma compra{_do(f)} esperando entrega."
    else:
        texto = (f"{_n(len(compras), 'compra')}{_do(f)} esperando entrega. "
                 + _ate_cinco(_compra_txt(c) for c in compras))
    return {"compras": [{"compra_id": c["compra_id"], "fornecedor": c["fornecedor"], "data": c["data"].isoformat(),
                         "total": _dinheiro(c["total"]), "status": c["status"], "dias": c["dias"],
                         "falta": [{"linha_id": l["linha_id"], "item": l["item"],
                                    "pendente": _q(l["pendente"], l["unidade_base"])} for l in c["pendentes"]]}
                        for c in compras], "texto": texto}


def _linhas_em_falta(fornecedor="", item="", compra_id=None):
    f = _fornecedor(fornecedor, ativos=False) if fornecedor else None
    linhas = cc.falta_receber(compra_id=_inteiro(compra_id, "compra_id") if compra_id else None)
    if f:
        linhas = [l for l in linhas if l["fornecedor"] == f.nome]
    if item:
        linhas = _casados(item, linhas)
    return f, linhas


def ver_falta_receber(fornecedor="", item=""):
    f, linhas = _linhas_em_falta(fornecedor, item)
    if not linhas:
        texto = "Nada" + (f" de {item}" if item else "") + f"{_do(f)} esperando entrega."
    else:
        texto = "Falta receber: " + _ate_cinco(
            f"{qtd(l['pendente'], l['unidade_base'])} de {l['item']}, fornecedor {l['fornecedor']}, "
            f"compra {l['compra_id']} {_ha(l['dias'])}" for l in linhas)
    return {"linhas": [{"compra_id": l["compra_id"], "linha_id": l["linha_id"], "fornecedor": l["fornecedor"],
                        "item": l["item"], "documentado": _q(l["documentado"], l["unidade_base"]),
                        "recebido": _q(l["recebido"], l["unidade_base"]),
                        "pendente": _q(l["pendente"], l["unidade_base"]), "dias": l["dias"]} for l in linhas],
            "texto": texto}


def _linha_compra_txt(l) -> str:
    un = l["unidade_base"]
    t = f"{qtd(l['documentado'], un)} de {l['item']}"
    if l["pendente"] <= 0 and l["encerrado"] <= 0:
        return t + ", tudo recebido"
    if l["recebido"] > 0:
        t += f", chegaram {qtd(l['recebido'], un)}"
    if l["pendente"] > 0:
        t += f", faltam {qtd(l['pendente'], un)}"
    if l["encerrado"] > 0:
        t += f", {qtd(l['encerrado'], un)} não entregues"
    return t


def ver_compra(compra_id):
    d = cc.detalhe_compra(_inteiro(compra_id, "compra_id"))
    if d is None:
        raise ConsultaInvalida("Compra não encontrada.", 404)
    conta = d["conta"]
    texto = (f"Compra {d['compra_id']}, fornecedor {d['fornecedor']}, {quando(d['data'])}, total {reais(d['total'])}, "
             f"{d['status_texto'].lower()}. Itens: {_juntar(_linha_compra_txt(l) for l in d['linhas'])}.")
    if conta["cancelada"]:
        texto += " A conta foi cancelada."
    else:
        texto += " Conta: " + _juntar(_parcela_txt(p) for p in conta["parcelas"]) + "."
    abertos = [a for a in conta["avisos"] if not a["resolvido"]]
    if abertos:
        texto += f" {_n(len(abertos), 'aviso')} de ajuste em aberto."
    return {
        "compra_id": d["compra_id"], "fornecedor": d["fornecedor"], "data": d["data"].isoformat(),
        "documento": d["documento"], "status": d["status"], "total": _dinheiro(d["total"]),
        "linhas": [{"linha_id": l["linha_id"], "item": l["item"],
                    **{k: _q(l[k], l["unidade_base"]) for k in ("documentado", "recebido", "pendente", "encerrado")},
                    "valor": _dinheiro(l["valor"]),
                    "recebimentos": [{"recebimento_id": r["recebimento_id"], "lote_id": r["lote_id"],
                                      "quantidade": _q(r["quantidade"], l["unidade_base"]),
                                      "validade": r["validade"].isoformat() if r["validade"] else None,
                                      "estornado": r["estornado"]} for r in l["recebimentos"]]}
                   for l in d["linhas"]],
        "parcelas": [{"parcela_id": p["parcela_id"], "numero": p["numero"], "de": p["de"],
                      "valor": _dinheiro(p["valor"]), "saldo": _dinheiro(p["saldo"]),
                      "vencimento": p["vencimento"].isoformat(), "situacao": p["situacao"], "vencida": p["vencida"]}
                     for p in conta["parcelas"]],
        "avisos": [{"aviso_id": a["aviso_id"], "aviso": a["texto"]} for a in abertos],
        "texto": texto,
    }


_SITUACOES = {"todas": "todas", "aberta": "todas", "abertas": "todas", "vencidas": "vencidas", "vencida": "vencidas",
              "a_vencer": "a_vencer", "a vencer": "a_vencer", "vencer": "a_vencer"}


def _parcela_curta(p) -> dict:
    return {"parcela_id": p["parcela_id"], "compra_id": p["compra_id"], "fornecedor": p["fornecedor"],
            "origem": p.get("origem", "compra"), "descricao": p.get("descricao", ""), "numero": p["numero"], "de": p["de"], "saldo": _dinheiro(p["saldo"]),
            "vencimento": p["vencimento"].isoformat(), "dias": p["dias"], "vencida": p["vencida"]}


def _de_quem(p) -> str:
    """"Atacadão, compra 3" ou, para despesa (Plano 8, sem fornecedor), "despesa Energia de novembro"."""
    if p.get("origem") == "despesa":
        return f"despesa {sem_mes_numerico(p['descricao'])}"
    return f"{p['fornecedor']}, compra {p['compra_id']}"


def ver_contas(situacao="todas", dias=7, fornecedor=""):
    tipo = _SITUACOES.get(_normal(situacao or "todas"))
    if tipo is None:
        raise ConsultaInvalida("'situacao' deve ser todas, vencidas ou a_vencer.")
    dias = _inteiro(dias, "dias")
    f = _fornecedor(fornecedor, ativos=False) if fornecedor else None
    if tipo == "vencidas":
        ps = fc.contas_vencidas()
    elif tipo == "a_vencer":
        ps = fc.contas_a_vencer(dias=dias)
    else:
        ps = fc.parcelas_em_aberto()
    if f:
        ps = [p for p in ps if p["fornecedor_id"] == f.id]
    total = sum((p["saldo"] for p in ps), Decimal("0"))
    vencido = sum((p["saldo"] for p in ps if p["vencida"]), Decimal("0"))
    do = _do(f)
    if not ps:
        texto = {"vencidas": f"Nenhuma conta{do} vencida.",
                 "a_vencer": f"Nenhuma conta{do} vencendo nos próximos {_n(dias, 'dia')}.",
                 "todas": f"Nenhuma conta{do} em aberto."}[tipo]
    else:
        cabeca = {"vencidas": f"{_n(len(ps), 'conta vencida', 'contas vencidas')}{do}",
                  "a_vencer": f"{_n(len(ps), 'conta')}{do} vencendo nos próximos {_n(dias, 'dia')}",
                  "todas": f"{_n(len(ps), 'conta')}{do} em aberto"}[tipo]
        texto = f"{cabeca}, somando {reais(total)}"
        if tipo == "todas" and vencido:
            texto += f", dos quais {reais(vencido)} já vencidos"
        texto += ". " + _ate_cinco(f"{_de_quem(p)}, {_parcela_txt(p)}" for p in ps)
    return {"parcelas": [_parcela_curta(p) for p in ps], "total": _dinheiro(total), "vencido": _dinheiro(vencido),
            "texto": texto}


def ver_divida_fornecedores(fornecedor=""):
    devido = fc.devido_por_fornecedor()
    if fornecedor:
        f = _fornecedor(fornecedor, ativos=False)
        devido = [d for d in devido if d["fornecedor_id"] == f.id]
        if not devido:
            texto = f"Nada em aberto com o fornecedor {f.nome}."
        else:
            d = devido[0]
            proxima = fc.parcelas_em_aberto(fornecedor_id=f.id)[0]
            texto = (f"Com o fornecedor {f.nome}, você deve {reais(d['devido'])} em {_n(d['parcelas'], 'parcela')}, "
                     + (f"{reais(d['vencido'])} já vencidos." if d["vencido"] else "nada vencido.")
                     + f" A mais antiga: {_parcela_txt(proxima)}.")
    else:
        if not devido:
            texto = "Você não deve nada a nenhum fornecedor."
        else:
            total = sum(d["devido"] for d in devido)
            texto = f"Você deve {reais(total)} no total. " + _ate_cinco(
                f"{d['fornecedor']}, {reais(d['devido'])}"
                + (f", sendo {reais(d['vencido'])} vencidos" if d["vencido"] else "") for d in devido)
    total = sum((d["devido"] for d in devido), Decimal("0"))
    return {"fornecedores": [{"fornecedor_id": d["fornecedor_id"], "fornecedor": d["fornecedor"],
                              "devido": _dinheiro(d["devido"]), "vencido": _dinheiro(d["vencido"]),
                              "parcelas": d["parcelas"]} for d in devido],
            "total": _dinheiro(total), "texto": texto}


def ver_avisos_de_ajuste():
    avisos = fc.avisos_de_ajuste()
    if not avisos:
        texto = "Nenhum aviso de ajuste em aberto."
    else:
        texto = f"{_n(len(avisos), 'aviso')} de ajuste em aberto. " + _ate_cinco(
            f"Aviso {a['aviso_id']}: {a['texto'].rstrip('.')}" for a in avisos)
    return {"avisos": [{"aviso_id": a["aviso_id"], "compra_id": a["compra_id"], "aviso": a["texto"],
                        "criado_em": timezone.localtime(a["criado_em"]).isoformat(timespec="minutes")}
                       for a in avisos], "texto": texto}


def _pendente_txt(p) -> str:
    t = f"{qtd(p['quantidade'], p['unidade_base'])} de {p['item']}"
    return t + (f" da produção {p['producao_id']}" if p["producao_id"] else "")


def ver_consumos_pendentes(item=""):
    ps = consumos_pendentes()
    if item:
        ps = _casados(item, ps)
    if not ps:
        texto = "Nenhum consumo pendente" + (f" de {item}" if item else "") + "."
    else:
        texto = f"{_n(len(ps), 'consumo pendente', 'consumos pendentes')}. " + _ate_cinco(
            _pendente_txt(p) + (", já dá para conciliar" if p["lotes_possiveis"] else ", ainda sem lote com saldo")
            for p in ps)
    return {"pendentes": [{"pendente_id": p["pendente_id"], "item": p["item"], "producao_id": p["producao_id"],
                           "quantidade": _q(p["quantidade"], p["unidade_base"]), "justificativa": p["justificativa"],
                           "lotes_possiveis": [{"lote_id": l["lote_id"], "codigo": l["codigo"],
                                                "validade": l["validade"].isoformat() if l["validade"] else None,
                                                "saldo": _q(l["saldo"], p["unidade_base"])}
                                               for l in p["lotes_possiveis"]]} for p in ps], "texto": texto}


def ultimo_preco(item):
    i = _item(item)
    u = cc.ultimo_custo(i.id)
    if u is None:
        return {"item": i.nome, "custo": None, "texto": f"Ainda não há compra de {i.nome}."}
    fator, por = _POR.get(i.unidade_base, (1, f"por {i.unidade_base}"))
    preco = (u["custo_unitario"] * fator).quantize(CENTAVO, ROUND_HALF_UP)
    return {"item": i.nome, "compra_id": u["compra_id"], "fornecedor": u["fornecedor"], "data": u["data"].isoformat(),
            "custo": _dinheiro(preco), "por": por,
            "texto": (f"Última compra de {i.nome}: fornecedor {u['fornecedor']}, {quando(u['data'])}, "
                      f"{reais(preco)} {por}, já com frete e desconto rateados.")}


# --- nível 1 ------------------------------------------------------------------

def cadastrar_fornecedor(*, nome, contato="", documento="", autor, canal):
    nome = (nome or "").strip()

    def fazer(chave):
        # o núcleo compara com iexact, que no SQLite não iguala "ATACADÃO", "Atacadao" e "Atacadão"
        mesmo = [f for f in Fornecedor.objects.all() if nome and _normal(f.nome) == _normal(nome)]
        if mesmo:
            raise ConsultaInvalida(f"Já existe o fornecedor '{mesmo[0].nome}'.", 409)
        return salvar_fornecedor(nome=nome, contato=contato, documento=documento, autor=autor, canal=canal,
                                 chave=chave)

    r, rep = _uma_vez("cadastrar_fornecedor", {"nome": _normal(nome)}, fazer)
    return _feito(f"Fornecedor {r['nome']} cadastrado.", r, rep, fornecedor_id=r["fornecedor_id"])


def resolver_aviso(*, observacao, aviso_id=None, autor, canal):
    if aviso_id is None:
        abertos = list(AvisoAjuste.objects.filter(resolvido_operacao__isnull=True).order_by("criado_em", "id"))
        if not abertos:
            raise ConsultaInvalida("Não há aviso de ajuste em aberto.", 404)
        if len(abertos) > 1:
            raise ConsultaInvalida("Há mais de um aviso de ajuste em aberto; diga qual (aviso_id).", 409,
                                   opcoes=[f"Aviso {a.id}: {a.texto}" for a in abertos])
        aviso_id = abertos[0].id
    aviso_id = _inteiro(aviso_id, "aviso_id")
    r, rep = _uma_vez("resolver_aviso", {"aviso": aviso_id}, lambda chave: _resolver_aviso(
        aviso_id=aviso_id, observacao=observacao, autor=autor, canal=canal, chave=chave))
    return _feito(f"Aviso {aviso_id} resolvido: {(observacao or '').strip().rstrip('.')}.", r, rep)


# --- nível 2: compras ---------------------------------------------------------------

def _condicao(valor) -> str:
    v = _normal(valor or "").replace("_", " ")
    if "vista" in v or v in ("pix", "dinheiro", "cartao"):
        return "a_vista"
    if "prazo" in v or "boleto" in v or "fiado" in v or "parcel" in v:
        return "a_prazo"
    raise ConsultaInvalida("'condicao' deve ser a_vista ou a_prazo.")


def _sem_valor(v) -> bool:
    return v in (None, "", 0)


def propor_registrar_compra(*, fornecedor, itens, condicao, total=None, prazo_dias=None, vencimento="", parcelas=1,
                            intervalo_dias=30, data_compra="", forma_pagamento="", frete=0, desconto=0, documento="",
                            justificativa="", ja_recebido=False, autor, canal):
    f = _fornecedor(fornecedor)
    pedidos = _dicts(itens)
    if not pedidos:
        raise ConsultaInvalida("Diga os itens da compra: item, quantidade, unidade e valor de cada um.")
    linhas, lidos = [], []
    for p in pedidos:
        i = _item(p.get("item"))
        if _sem_valor(p.get("valor")):
            raise ConsultaInvalida(f"Quanto custou {i.nome}? Diga o valor total desse item.")
        un = _unidade(i, p.get("unidade")) or i.unidade_base
        q, v = _decimal(p.get("quantidade"), "quantidade"), _decimal(p.get("valor"), "valor")
        linhas.append({"item_id": i.id, "quantidade": q, "unidade": un, "valor": v})
        lidos.append((i, q, un, v, _data(p.get("validade"), "validade"), (p.get("lote") or "").strip()))
    quando_compra = _data(data_compra, "data_compra") or timezone.localdate()
    fr, de = _decimal(frete or 0, "frete"), _decimal(desconto or 0, "desconto")
    # sem total dito, vale a soma dos itens (o sistema soma; o modelo não faz conta)
    tot = sum((l["valor"] for l in linhas), Decimal("0")) + fr - de if _sem_valor(total) else _decimal(total, "total")
    cond = _condicao(condicao)
    parametros = {"fornecedor_id": f.id, "data_compra": quando_compra, "linhas": linhas, "total": tot,
                  "condicao": cond, "frete": fr, "desconto": de, "documento": (documento or "").strip(),
                  "justificativa": justificativa}
    if cond == "a_prazo":
        if vencimento:
            primeiro = _data(vencimento, "vencimento")
        elif not _sem_valor(prazo_dias):
            primeiro = quando_compra + timedelta(days=_inteiro(prazo_dias, "prazo_dias"))
        else:
            raise ConsultaInvalida("Quando vence? Diga o prazo em dias (ex.: 30) ou a data do vencimento.")
        parametros["parcelas"] = dividir_parcelas(tot, _inteiro(parcelas or 1, "parcelas"), primeiro,
                                                  _inteiro(intervalo_dias or 30, "intervalo_dias"))
    else:
        parametros["forma_pagamento"] = forma_pagamento
    operacao = "registrar_compra"
    if ja_recebido:
        operacao = "registrar_e_receber_compra"
        parametros["recebimento"] = [{"validade": val, "lote_codigo": lote} for *_, val, lote in lidos]

    def resumir(r):
        itens_txt = _juntar(f"{qtd(q, un)} de {i.nome} por {reais(v)}" + (f", validade {quando(val)}" if val else "")
                            for i, q, un, v, val, _ in lidos)
        t = f"Lançar compra do fornecedor {f.nome}, {quando(quando_compra)}: {itens_txt}"
        if fr:
            t += f", frete de {reais(fr)}"
        if de:
            t += f", desconto de {reais(de)}"
        t += f". Total {reais(tot)}, "
        if cond == "a_vista":
            t += "à vista, já pago" + (f" no {forma_pagamento.strip()}" if (forma_pagamento or "").strip() else "")
        else:
            ps = parametros["parcelas"]
            if len(ps) == 1:
                t += f"a prazo, vence {quando(ps[0]['vencimento'])}"
            else:
                t += f"a prazo em {len(ps)} parcelas: " + _juntar(
                    f"{reais(p['valor'])} {quando(p['vencimento'])}" for p in ps)
        if parametros["documento"]:
            t += f", documento {parametros['documento']}"
        if ja_recebido:
            t += ". Já chegou: entra no estoque agora"
        if r["alertas"]:
            t += ". Atenção: " + " ".join(a.rstrip(".") + "." for a in r["alertas"]).rstrip(".")
        return t

    return _proposta(operacao, parametros, resumir, autor, canal)


def _compra_unica(compras: set, linhas):
    if len(compras) == 1:
        return next(iter(compras))
    por_compra = {}
    for l in linhas:
        if l["compra_id"] in compras:
            por_compra.setdefault(l["compra_id"], []).append(l)
    opcoes = [f"Compra {cid}, fornecedor {ls[0]['fornecedor']}, {_ha(ls[0]['dias'])}: falta {_falta_txt(ls)}"
              for cid, ls in sorted(por_compra.items())]
    raise ConsultaInvalida("Há mais de uma compra esperando entrega; diga qual (compra_id).", 409, opcoes=opcoes)


def _achar_compra(fornecedor, compra_id, nomes):
    """(compra_id, linhas pendentes dela casadas com cada nome) — sem nomes, todas as linhas pendentes."""
    f, linhas = _linhas_em_falta(fornecedor, "", compra_id)
    if not linhas:
        raise ConsultaInvalida(f"Nenhuma compra{_do(f)} esperando entrega.", 404)
    if not nomes:
        cid = _compra_unica({l["compra_id"] for l in linhas}, linhas)
        return cid, [l for l in linhas if l["compra_id"] == cid]
    casadas = []
    for nome in nomes:
        c = _casados(nome, linhas)
        if not c:
            raise ConsultaInvalida(f"Nada de '{nome}'{_do(f)} esperando entrega.", 404)
        casadas.append(c)
    comuns = set.intersection(*({l["compra_id"] for l in c} for c in casadas))
    if not comuns:
        raise ConsultaInvalida("Esses itens não estão numa mesma compra; fale de uma compra por vez.")
    cid = _compra_unica(comuns, [l for c in casadas for l in c])
    escolhidas = []
    for nome, c in zip(nomes, casadas):
        da_compra = [l for l in c if l["compra_id"] == cid]
        if len(da_compra) > 1:
            raise ConsultaInvalida(f"Mais de um item com o nome '{nome}' nesta compra; diga qual.", 409,
                                   opcoes=[l["item"] for l in da_compra])
        escolhidas.append(da_compra[0])
    return cid, escolhidas


def _restante_txt(cid) -> str:
    falta = cc.falta_receber(compra_id=cid)
    return f"Fica faltando {_falta_txt(falta)}" if falta else "Com isso a compra fica completa"


def propor_receber_compra(*, fornecedor="", item="", quantidade=None, unidade="", validade="", lote="",
                          compra_id=None, itens=None, autor, canal):
    pedidos = _dicts(itens) or ([{"item": item, "quantidade": quantidade, "unidade": unidade, "validade": validade,
                                  "lote": lote}] if (item or "").strip() else [])
    cid, linhas = _achar_compra(fornecedor, compra_id, [p.get("item") for p in pedidos])
    if not pedidos:
        if not _sem_valor(quantidade):
            if len(linhas) > 1:
                raise ConsultaInvalida("Diga qual item chegou: esta compra tem mais de um esperando entrega.", 409,
                                       opcoes=[l["item"] for l in linhas])
            pedidos = [{"quantidade": quantidade, "unidade": unidade, "validade": validade, "lote": lote}]
        else:  # "chegou tudo": todas as linhas pendentes, com a validade e o lote ditos (se houver)
            pedidos = [{"validade": validade, "lote": lote} for _ in linhas]
    receber = []
    tudo = not itens and not (item or "").strip() and len(linhas) > 1
    for p, l in zip(pedidos, linhas):
        i = Item.objects.get(id=l["item_id"])
        validade_linha = _data(p.get("validade"), "validade")
        if tudo and not i.controla_validade:
            validade_linha = None  # validade dita para "chegou tudo" vale para quem controla validade
        if _sem_valor(p.get("quantidade")):  # sem quantidade: tudo o que falta da linha
            q, un = l["pendente"], l["unidade_base"]
        else:
            q, un = _decimal(p.get("quantidade"), "quantidade"), _unidade(i, p.get("unidade")) or l["unidade"]
        receber.append({"linha_id": l["linha_id"], "quantidade": q, "unidade": un,
                        "lote_codigo": (p.get("lote") or "").strip(), "validade": validade_linha})
    nomes = {l["linha_id"]: (l["item"], l["unidade_base"]) for l in linhas}
    fornecedor_nome = linhas[0]["fornecedor"]

    def resumir(r):
        partes = []
        for rec, pedido in zip(r["recebimentos"], receber):
            nome, un = nomes[rec["linha_id"]]
            partes.append(f"{qtd(rec['quantidade_base'], un)} de {nome}"
                          + (f", validade {quando(pedido['validade'])}" if pedido["validade"] else "")
                          + (f", lote {pedido['lote_codigo']}" if pedido["lote_codigo"] else ""))
        return f"Receber da compra {cid}, fornecedor {fornecedor_nome}: {_juntar(partes)}. {_restante_txt(cid)}"

    return _proposta("receber_compra", {"compra_id": cid, "linhas": receber}, resumir, autor, canal)


def propor_encerrar_pendencia(*, motivo, fornecedor="", item="", compra_id=None, autor, canal):
    nomes = [item] if (item or "").strip() else []
    cid, linhas = _achar_compra(fornecedor, compra_id, nomes)
    parametros = {"compra_id": cid, "motivo": motivo, "linha_ids": [l["linha_id"] for l in linhas] if nomes else None}
    nomes_linha = {l["linha_id"]: (l["item"], l["unidade_base"]) for l in linhas}

    def resumir(r):
        lista = _juntar(f"{qtd(x['encerrado'], nomes_linha[x['linha_id']][1])} de {nomes_linha[x['linha_id']][0]}"
                        for x in r["linhas"])
        return (f"Encerrar o que falta da compra {cid}, fornecedor {linhas[0]['fornecedor']}: {lista} não vai ser "
                f"entregue (motivo: {(motivo or '').strip()}). O valor da conta não muda; fica um aviso para ajustar "
                "no pagamento")

    return _proposta("encerrar_pendencia", parametros, resumir, autor, canal)


def propor_cancelar_compra(*, motivo, compra_id=None, fornecedor="", autor, canal):
    qs = Compra.objects.select_related("fornecedor").exclude(status="cancelada").order_by("-data", "-id")
    if compra_id:
        c = qs.filter(id=_inteiro(compra_id, "compra_id")).first() or \
            Compra.objects.filter(id=_inteiro(compra_id, "compra_id")).first()
        if c is None:
            raise ConsultaInvalida("Compra não encontrada.", 404)
    else:
        if not (fornecedor or "").strip():
            raise ConsultaInvalida("Diga qual compra cancelar: o fornecedor ou o número da compra.")
        f = _fornecedor(fornecedor, ativos=False)
        candidatas = list(qs.filter(fornecedor=f, status="aprovada"))  # só sem recebimento podem ser canceladas
        if not candidatas:
            raise ConsultaInvalida(f"Nenhuma compra do fornecedor {f.nome} pode ser cancelada: "
                                   "as que existem já tiveram recebimento.", 404)
        if len(candidatas) > 1:
            raise ConsultaInvalida(f"Há mais de uma compra do fornecedor {f.nome}; diga qual (compra_id).", 409,
                                   opcoes=[f"Compra {x.id}, {quando(x.data)}, total {reais(x.total)}"
                                           for x in candidatas])
        c = candidatas[0]
    return _proposta("cancelar_compra", {"compra_id": c.id, "motivo": motivo},
                     lambda r: (f"Cancelar a compra {c.id}, fornecedor {c.fornecedor.nome}, de {quando(c.data)}, "
                                f"total {reais(c.total)}; a conta a pagar é cancelada junto "
                                f"(motivo: {(motivo or '').strip()})"), autor, canal)


def _recebimentos(*, fornecedor="", item="", compra_id=None):
    qs = (Recebimento.objects.filter(estorno_operacao__isnull=True)
          .select_related("linha__item", "linha__compra__fornecedor", "lote").order_by("-id"))
    f = _fornecedor(fornecedor, ativos=False) if fornecedor else None
    if f:
        qs = qs.filter(linha__compra__fornecedor=f)
    if compra_id:
        qs = qs.filter(linha__compra_id=_inteiro(compra_id, "compra_id"))
    recs = list(qs)
    if item:
        achados = [r for r in recs if _casa(item, r.linha.item.nome)]
        recs = [r for r in achados if _normal(r.linha.item.nome) == _normal(item)] or achados
    return f, recs


def _rec_txt(r) -> str:
    return (f"{qtd(r.quantidade, r.linha.item.unidade_base)} de {r.linha.item.nome}, compra {r.linha.compra_id}, "
            f"fornecedor {r.linha.compra.fornecedor.nome}, recebido {quando(timezone.localtime(r.criado_em).date())}")


def propor_estornar_recebimento(*, motivo, fornecedor="", item="", compra_id=None, recebimento_id=None, autor, canal):
    if recebimento_id:
        r = Recebimento.objects.select_related("linha__item", "linha__compra__fornecedor").filter(
            id=_inteiro(recebimento_id, "recebimento_id")).first()
        if r is None:
            raise ConsultaInvalida("Recebimento não encontrado.", 404)
    else:
        if not ((fornecedor or "").strip() or (item or "").strip() or compra_id):
            raise ConsultaInvalida("Diga qual recebimento estornar: o fornecedor, o item ou a compra.")
        f, recs = _recebimentos(fornecedor=fornecedor, item=item, compra_id=compra_id)
        if not recs:
            raise ConsultaInvalida("Nenhum recebimento encontrado para estornar.", 404)
        if len(recs) > 1:
            raise ConsultaInvalida("Há mais de um recebimento; diga qual (recebimento_id).", 409,
                                   opcoes=[f"Recebimento {x.id}: {_rec_txt(x)}" for x in recs])
        r = recs[0]
    return _proposta("estornar_recebimento", {"recebimento_id": r.id, "motivo": motivo},
                     lambda res: (f"Estornar o recebimento de {_rec_txt(r)} (motivo: {(motivo or '').strip()}). "
                                  "Sai do estoque e volta a ficar pendente de entrega"), autor, canal)


def propor_devolver_ao_fornecedor(*, item, quantidade, motivo, unidade="", fornecedor="", compra_id=None,
                                  lote_id=None, autor, canal):
    f, recs = _recebimentos(fornecedor=fornecedor, item=item, compra_id=compra_id)
    if lote_id:
        recs = [r for r in recs if r.lote_id == _inteiro(lote_id, "lote_id")]
    com_saldo = [(r, s) for r in recs if (s := saldo_lote(r.lote)) > 0]
    if not com_saldo:
        raise ConsultaInvalida(f"Nenhum lote de '{item}'{_do(f)} vindo de compra com saldo.", 404)
    if len(com_saldo) > 1:
        raise ConsultaInvalida(f"Há mais de um lote de '{item}' vindo de compra; diga qual (compra_id ou lote_id).", 409,
                               opcoes=[f"Lote {r.lote_id}: compra {r.linha.compra_id}, fornecedor "
                                       f"{r.linha.compra.fornecedor.nome}, {qtd(s, r.linha.item.unidade_base)} "
                                       f"no estoque" for r, s in com_saldo])
    r = com_saldo[0][0]
    i = r.linha.item
    parametros = {"lote_id": r.lote_id, "quantidade": _decimal(quantidade, "quantidade"), "motivo": motivo,
                  "unidade": _unidade(i, unidade) or None}
    return _proposta("devolver_ao_fornecedor", parametros, lambda res: (
        f"Devolver {qtd(res['quantidade_base'], i.unidade_base)} de {i.nome} ao fornecedor "
        f"{r.linha.compra.fornecedor.nome}, compra {r.linha.compra_id} (motivo: {(motivo or '').strip()}). "
        f"Ficam {qtd(res['saldo_lote'], i.unidade_base)} nesse lote. O valor da conta não muda; fica um aviso "
        "para ajustar no pagamento"), autor, canal)


def propor_receber_bonificacao(*, item, quantidade, unidade, motivo, validade="", lote="", fornecedor="",
                               compra_id=None, autor, canal):
    i = _item(item)
    texto = (motivo or "").strip()
    if (fornecedor or "").strip() and not compra_id and texto:
        texto += f" ({_fornecedor(fornecedor, ativos=False).nome})"
    parametros = {"item_id": i.id, "quantidade": _decimal(quantidade, "quantidade"),
                  "unidade": _unidade(i, unidade) or i.unidade_base, "motivo": texto, "lote_codigo": lote,
                  "validade": _data(validade, "validade"),
                  "compra_id": _inteiro(compra_id, "compra_id") if compra_id else None}
    return _proposta("receber_bonificacao", parametros, lambda r: (
        f"Entrada de {qtd(r['quantidade_base'], i.unidade_base)} de {i.nome} como bonificação, sem custo"
        + (f", validade {quando(parametros['validade'])}" if parametros["validade"] else "")
        + (f", junto da compra {parametros['compra_id']}" if parametros["compra_id"] else "")
        + f" (motivo: {texto})"), autor, canal)


# --- nível 2: contas a pagar ---------------------------------------------------------

def _uma_parcela(fornecedor, compra_id, valor):
    f = _fornecedor(fornecedor, ativos=False) if fornecedor else None
    if not f and not compra_id:
        raise ConsultaInvalida("Diga de qual fornecedor é a conta.")
    ps = fc.parcelas_em_aberto(fornecedor_id=f.id if f else None)
    if compra_id:
        ps = [p for p in ps if p["compra_id"] == _inteiro(compra_id, "compra_id")]
    if not ps:
        raise ConsultaInvalida(f"Nenhuma conta{_do(f)} em aberto.", 404)
    if len({p["conta_id"] for p in ps}) == 1:
        return ps[0]  # parcelas da mesma compra: paga-se a mais antiga
    if not _sem_valor(valor):
        mesmas = [p for p in ps if p["saldo"] == _decimal(valor, "valor").quantize(CENTAVO)]
        if len(mesmas) == 1:
            return mesmas[0]
    raise ConsultaInvalida(f"Há mais de uma conta{_do(f)} em aberto; diga qual (parcela_id).", 409,
                           opcoes=[f"Parcela {p['parcela_id']}: compra {p['compra_id']}, {_parcela_txt(p)}" for p in ps])


def propor_registrar_pagamento(*, fornecedor="", valor=None, data_pagamento="", forma="", compra_id=None,
                               parcela_id=None, juros=0, multa=0, desconto=0, motivo_diferenca="", autor, canal):
    if parcela_id:
        abertas = [p for p in fc.parcelas_em_aberto() if p["parcela_id"] == _inteiro(parcela_id, "parcela_id")]
        if not abertas:
            raise ConsultaInvalida("Essa parcela não está em aberto.", 404)
        p = abertas[0]
    else:
        p = _uma_parcela(fornecedor, compra_id, valor)
    difs = [(t, _decimal(v, t)) for t, v in (("juros", juros), ("multa", multa), ("desconto", desconto))
            if not _sem_valor(v)]
    if len(difs) > 1:
        raise ConsultaInvalida("Diga só um entre juros, multa e desconto.")
    tipo, dif = difs[0] if difs else ("", Decimal("0"))
    dia = _data(data_pagamento, "data_pagamento") or timezone.localdate()
    parametros = {"parcela_id": p["parcela_id"], "valor": None if _sem_valor(valor) else _decimal(valor, "valor"),
                  "data_pagamento": dia, "forma": forma, "diferenca": dif, "diferenca_tipo": tipo,
                  "diferenca_motivo": motivo_diferenca}

    def resumir(r):
        t = (f"Anotar que você pagou {reais(r['valor_pago'])} {quando(dia)} ao fornecedor {p['fornecedor']}, "
             f"compra {p['compra_id']}, {_parcela_txt(p)}")
        if (forma or "").strip():
            t += f", no {forma.strip()}"
        if dif:
            t += f", com {reais(dif)} de {tipo}"
        situacao = r["situacao"]
        return t + (". A parcela fica quitada" if situacao == "paga"
                    else f". Ficam faltando {reais(r['saldo'])} nesta parcela")

    return _proposta("registrar_pagamento", parametros, resumir, autor, canal)


def propor_estornar_pagamento(*, motivo, fornecedor="", pagamento_id=None, autor, canal):
    if pagamento_id:
        pid = _inteiro(pagamento_id, "pagamento_id")
        pgs = [x for x in fc.pagamentos() if x["pagamento_id"] == pid]
        if not pgs:
            raise ConsultaInvalida("Pagamento não encontrado ou já estornado.", 404)
    else:
        f = _fornecedor(fornecedor, ativos=False)
        pgs = list(reversed(fc.pagamentos(fornecedor_id=f.id)))
        if not pgs:
            raise ConsultaInvalida(f"Nenhum pagamento anotado do fornecedor {f.nome}.", 404)
    rotulo = lambda x: f"{reais(x['valor_pago'])} pagos {quando(x['data'])}, {x['descricao']}"
    if len(pgs) > 1:
        raise ConsultaInvalida("Há mais de um pagamento; diga qual (pagamento_id).", 409,
                               opcoes=[f"Pagamento {x['pagamento_id']}: {rotulo(x)}" for x in pgs])
    pg = pgs[0]
    return _proposta("estornar_pagamento", {"pagamento_id": pg["pagamento_id"], "motivo": motivo}, lambda r: (
        f"Estornar o pagamento de {rotulo(pg)} (motivo: {(motivo or '').strip()}). "
        f"A parcela volta a ficar em aberto com {reais(r['saldo'])}"), autor, canal)


# --- nível 2: consumo pendente ---------------------------------------------------------

def propor_conciliar_consumo(*, item="", pendente_id=None, lote_id=None, autor, canal):
    ps = consumos_pendentes()
    if pendente_id:
        ps = [p for p in ps if p["pendente_id"] == _inteiro(pendente_id, "pendente_id")]
    elif item:
        ps = _casados(item, ps)
    if not ps:
        raise ConsultaInvalida("Nenhum consumo pendente" + (f" de '{item}'" if item else "") + ".", 404)
    if len(ps) > 1:
        raise ConsultaInvalida("Há mais de um consumo pendente; diga qual (pendente_id).", 409,
                               opcoes=[f"Pendência {p['pendente_id']}: {_pendente_txt(p)}" for p in ps])
    p = ps[0]
    if lote_id:
        lote = Lote.objects.filter(id=_inteiro(lote_id, "lote_id")).first()
        if lote is None:
            raise ConsultaInvalida("Lote não encontrado.", 404)
    elif p["lotes_possiveis"]:
        lote = Lote.objects.get(id=p["lotes_possiveis"][0]["lote_id"])  # o que vence primeiro
    else:
        raise ConsultaInvalida(f"Ainda não há lote de {p['item']} com {qtd(p['quantidade'], p['unidade_base'])} "
                               "disponíveis para conciliar.", 409)

    def resumir(r):
        t = (f"Conciliar {_pendente_txt(p)} com o lote {lote.codigo or 'sem código'}"
             + (f", validade {quando(lote.validade)}" if lote.validade else "") + f": custo de {reais(r['custo'])}")
        if r["producao_id"] and not r["custo_pendente"]:
            t += ". O custo da produção fica fechado"
        return t

    return _proposta("conciliar_consumo", {"pendente_id": p["pendente_id"], "lote_id": lote.id}, resumir, autor, canal)


# --- o que dizer depois de confirmar ---------------------------------------------

def pendentes_txt(pendentes) -> str:
    """Consumos pendentes criados numa conclusão: "500 g de Farinha de trigo"."""
    objs = ConsumoPendente.objects.select_related("item").in_bulk([x["pendente_id"] for x in pendentes])
    return _juntar(f"{qtd(o.quantidade, o.item.unidade_base)} de {o.item.nome}" for o in objs.values())


def _conciliaveis_txt(conciliaveis) -> str:
    if not conciliaveis:
        return ""
    objs = ConsumoPendente.objects.select_related("item").in_bulk({c["pendente_id"] for c in conciliaveis})
    lista = _juntar(f"{qtd(o.quantidade, o.item.unidade_base)} de {o.item.nome}"
                    + (f" da produção {o.producao_id}" if o.producao_id else "") for o in objs.values())
    return f" Há consumo pendente que pode ser conciliado com o que entrou: {lista}. Quer conciliar?"


def depois(p) -> str:
    r = p.resultado
    if p.operacao == "registrar_compra":
        return f" É a compra {r['compra_id']}."
    if p.operacao == "registrar_e_receber_compra":
        return f" É a compra {r['compra_id']}.{_conciliaveis_txt(r['recebimento']['conciliaveis'])}"
    if p.operacao in ("receber_compra", "receber_bonificacao"):
        return _conciliaveis_txt(r["conciliaveis"])
    return ""
