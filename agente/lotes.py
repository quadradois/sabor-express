"""Lotes na operação pelo agente de voz (Plano 9, fase 2b).

O lote é falado pelo nome da cozinha ("lote do dia 8"), nunca pelo código, salvo se pedirem. Aqui ficam:
- `resolver_lote`: o lote dito ("lote do dia 10", "dia 10", "segundo lote do dia 8", o código ou o `lote_id`
  vindo da separação) entre os candidatos; ambíguo vira `ConsultaInvalida` com `opcoes`;
- `separacao_falada`: a instrução de separação do núcleo (`vendas.lotes`) em texto para falar;
- `vencidos_txt` e `pedir_motivo`: o aviso do vencido (lote, dia em que venceu, motivo) — o motivo é sempre o
  que o dono disse; sem ele, o agente pergunta (nunca inventa);
- `propor_contar_lote` e `conferir_vencido` (conferência do vencido da caixa: as três respostas).

Nenhuma conta aqui: separação, sobras, avisos, validade e saldo vêm do núcleo (`vendas.lotes`, `estoque`).
"""

import re
from decimal import Decimal

from django.utils import timezone

from decisoes import consultas as dc
from estoque.lotes import MESES, ORDINAIS, dia_producao, nome_lote, vencida
from estoque.models import Lote
from estoque.servicos import porcoes, saldo_lote, validade_porcao
from nucleo.operacoes import RegraViolada

from .acoes import _decimal, _proposta
from .compras import _juntar, qtd, quando, reais
from .consultas import ConsultaInvalida, _inteiro, _normal

_MESES = [_normal(m) for m in MESES]
_ORDINAIS = {_normal(v): k for k, v in ORDINAIS.items()} | {"primeiro": 1}


# --- nome falado do lote ---------------------------------------------------------------

def nome(lote) -> str:
    """"lote do dia 8" (o nome da cozinha, igual ao das telas)."""
    return nome_lote(lote)


def _ordem(lote) -> int:
    n = _normal(nome(lote)).split()[0]
    return _ORDINAIS.get(n, 1)


def resolver_lote(dito, candidatos, *, oque="lote", lote_id=None):
    """O lote dito entre `candidatos` (Lotes): pelo `lote_id` (da separação), pelo nome falado ("lote do dia 8",
    "dia 8", "segundo lote do dia 8", "dia 28 de outubro") ou pelo código. Ambíguo ou fora da lista: erro claro."""
    candidatos = list(candidatos)
    if lote_id not in (None, ""):
        lid = _inteiro(lote_id, "lote_id")
        achado = [l for l in candidatos if l.id == lid]
        if not achado:
            raise ConsultaInvalida(f"Esse lote (número {lid}) não serve aqui: não é de {oque} com saldo.", 404)
        return achado[0]
    v = _normal(str(dito or ""))
    if not v:
        raise ConsultaInvalida(f"Diga de qual lote: o dia em que foi feito (ex.: lote do dia 8).")
    por_codigo = [l for l in candidatos if l.codigo and (_normal(l.codigo) == v or (len(v) >= 3 and v in _normal(l.codigo)))]
    if len(por_codigo) == 1:
        return por_codigo[0]
    numeros = re.findall(r"\d+", v)
    if not numeros:
        raise ConsultaInvalida(f"Não entendi o lote '{dito}'. Diga o dia em que foi feito (ex.: lote do dia 8).")
    dia = int(numeros[0])
    palavras = v.split()
    mes = next((_MESES.index(p) + 1 for p in palavras if p in _MESES), None)
    ano = next((int(n) for n in numeros[1:] if len(n) == 4), None)
    ordem = next((_ORDINAIS[p] for p in palavras if p in _ORDINAIS), None)
    achados = [l for l in candidatos if dia_producao(l).day == dia
               and (mes is None or dia_producao(l).month == mes) and (ano is None or dia_producao(l).year == ano)]
    if mes is None and achados:  # sem o mês: o dia mais recente com esse número (o deste mês, se houver)
        recente = max(dia_producao(l) for l in achados)
        achados = [l for l in achados if dia_producao(l) == recente]
    if ordem is not None:
        achados = [l for l in achados if _ordem(l) == ordem]
    if len(achados) == 1:
        return achados[0]
    if not achados:
        tem = _juntar(sorted({nome(l) for l in candidatos})) if candidatos else "nenhum"
        raise ConsultaInvalida(f"Não há {dito} de {oque} com saldo. Lotes com saldo: {tem}.", 404,
                               opcoes=[nome(l) for l in candidatos][:8])
    raise ConsultaInvalida(f"Há mais de um lote do dia {dia} de {oque}; pergunte qual.", 409,
                           opcoes=[nome(l) for l in achados])


def lotes_da_apresentacao(a) -> list:
    """Lotes do produto na forma da apresentação com saldo na conservação dela (vencidos inclusive)."""
    ids = [p["lote_id"] for p in porcoes(item=a.produto) if p["estado"] == a.estado]
    return list(Lote.objects.select_related("item").filter(id__in=ids, forma=a.forma).order_by("criado_em", "id"))


def lotes_indicados(a, pedidos) -> list[dict] | None:
    """[{lote | lote_id, unidades}] falados → [{lote_id, unidades}] para o núcleo. O agente não completa a conta:
    o que faltar para o item, o núcleo tira pelo que vence primeiro."""
    if not pedidos:
        return None
    if isinstance(pedidos, dict):
        pedidos = [pedidos]
    candidatos = lotes_da_apresentacao(a)
    oque = f"{a.produto.nome} {a.forma} {a.estado}"
    saida = []
    for p in pedidos:
        p = dict(p)
        lote = resolver_lote(p.get("lote"), candidatos, oque=oque, lote_id=p.get("lote_id"))
        saida.append({"lote_id": lote.id, "unidades": _inteiro(p.get("unidades"), "unidades do lote")})
    return saida


# --- separação falada ------------------------------------------------------------------

_AVISOS_FALADOS = ("deixado", "falta", "so_vencido", "vencido_sem_motivo")


def _falavel(t):
    from .decisoes import falavel

    return falavel(t)


def _linha_dados(l) -> dict:
    return {"apresentacao": l["apresentacao"], "produto": l["produto"], "forma": l["forma"],
            "conservacao": l["estado"], "unidades": float(l["unidades"]), "falta": float(l["falta"]),
            **({"item_encomenda_id": l["item_encomenda_id"]} if "item_encomenda_id" in l else {}),
            "lotes": [{"lote_id": x["lote_id"], "lote": x["nome"], "unidades": float(x["unidades"]),
                       "sobra": float(x["sobra"]), "validade": x["validade"].isoformat() if x["validade"] else None,
                       "vencido": x["vencido"]} for x in l["lotes"]],
            "deixados": [{"lote_id": d["lote_id"], "lote": d["nome"], "unidades": float(d["unidades"]),
                          "validade": d["validade"].isoformat() if d["validade"] else None} for d in l["deixados"]]}


def separacao_falada(sep) -> str:
    """O `texto` de cada linha da separação e os avisos que importam (deixado, falta, só vencido, vencido sem
    motivo), como se fala. "Vence hoje/amanhã" já está no texto da linha."""
    partes = [_falavel(l["texto"]) for l in sep["linhas"]]
    partes += [_falavel(a["texto"]) for a in sep["avisos"] if a["tipo"] in _AVISOS_FALADOS]
    return " ".join(partes)


def separacao_curta(sep) -> str:
    """Para a proposta, que já disse produto e quantidade: só o lote ("Sai do lote do dia 8, que vence amanhã") e
    os mesmos avisos da separação falada. Com mais de um produto, o nome volta para dizer qual sai de onde."""
    def lote(l):
        return _falavel(l["de_onde"]) or "não há de onde pegar"

    linhas = sep["linhas"]
    if len(linhas) == 1:
        partes = [f"Sai {lote(linhas[0])}."]
    else:
        partes = ["De onde sai: " + "; ".join(f"{l['produto']} {l['forma']} {l['estado']}, {lote(l)}"
                                               for l in linhas) + "."]
    partes += [_falavel(a["texto"]) for a in sep["avisos"] if a["tipo"] in _AVISOS_FALADOS]
    return " ".join(partes)


def separacao_resposta(sep, **extra) -> dict:
    texto = separacao_falada(sep)
    if sep["precisa_motivo"]:
        texto += " Para sair de lote vencido, pergunte o motivo ao dono."
    return {**extra, "data_venda": sep["data_venda"].isoformat(), "completo": sep["completo"],
            "precisa_motivo": sep["precisa_motivo"], "linhas": [_linha_dados(l) for l in sep["linhas"]],
            "avisos": [{"tipo": a["tipo"], "texto": _falavel(a["texto"]), **({"lote_id": a["lote_id"]} if "lote_id" in a
                                                                              else {})} for a in sep["avisos"]],
            "texto": texto}


def vencidos_da_separacao(sep) -> list[tuple]:
    """[(nome, validade)] dos lotes vencidos que a separação tira (no dia da venda)."""
    return [(x["nome"], x["validade"]) for l in sep["linhas"] for x in l["lotes"] if x["vencido"]]


# --- vencido com motivo ------------------------------------------------------------------

def vencido_frase(nome_, validade, motivo, *, de="") -> str:
    """"Atenção, lote vencido: o lote do dia 8 de Coxinha venceu em 12 de novembro; vai com o motivo: X"."""
    return (f"Atenção, lote vencido: o {nome_}{f' de {de}' if de else ''} venceu {quando(validade)}; "
            f"vai com o motivo: {(motivo or '').strip().rstrip('.')}")


def vencidos_txt(pares, motivo) -> str:
    """Frases do vencido para a proposta (vazio se nada vencido). `pares` = [(nome, validade, de)]."""
    if not pares:
        return ""
    return ". " + ". ".join(vencido_frase(n, v, motivo, de=de) for n, v, de in pares)


def porcao_vencida(lote, estado, hoje=None):
    """(nome, validade, item) se a porção venceu hoje; senão None. Só leitura do núcleo."""
    hoje = hoje or timezone.localdate()
    v = validade_porcao(lote, estado)
    return (nome(lote), v, lote.item.nome) if vencida(v, hoje) else None


def pedir_motivo(propor):
    """Roda a proposta; se o núcleo recusar porque o lote venceu e falta o motivo, devolve a pergunta falada
    (`precisa_motivo`) em vez do erro cru. O motivo é sempre o que o dono disser."""
    try:
        return propor()
    except RegraViolada as e:
        msg = str(e)
        if "informe o motivo" not in msg:
            raise
        raise ConsultaInvalida(_falavel(msg) + " Pergunte o motivo ao dono (nunca invente) e chame de novo com "
                               "motivo_vencido.", 422, precisa_motivo=True) from None


def checar_motivo_na_separacao(sep):
    if sep["precisa_motivo"]:
        avisos = [_falavel(a["texto"]) for a in sep["avisos"] if a["tipo"] == "vencido_sem_motivo"]
        raise ConsultaInvalida(" ".join(avisos) + " Pergunte o motivo ao dono (nunca invente) e chame de novo com "
                               "motivo_vencido.", 422, precisa_motivo=True)


# --- contagem do lote (nível 2) ----------------------------------------------------------------

def _porcao_txt(lote, estado) -> str:
    return (f"o {nome(lote)} de {lote.item.nome}" + (f", {lote.forma}" if lote.item.tipo == "produto" else "")
            + (f", {estado}" if estado else ""))


def _contagem_resumo(lote, estado):
    def resumir(r):
        base = r["unidade_base"]
        fala = (lambda q: _un(q)) if base == "un" else (lambda q: qtd(q, base))
        dif = Decimal(str(r["diferenca"]))
        t = (f"Contagem d{_porcao_txt(lote, estado)}: o sistema tinha {fala(r['antes'])} e foi contado "
             f"{fala(r['contado'])}")
        if dif == 0:
            return t + ". Bate: nada muda no estoque, fica só anotado"
        t += (f"; ajusta {fala(abs(dif))} a " + ("menos" if dif < 0 else "mais")
              + f" ({reais(abs(Decimal(str(r['valor']))))} em mercadoria)")
        if r["reservas_liberadas"]:
            t += ". Isso libera reserva de encomenda desse lote: depois complete a reserva com outro lote"
        return t
    return resumir


def _un(q) -> str:
    from .vendas import _un as un

    return un(q)


def propor_contar_lote(*, contado, motivo, produto="", lote="", conservacao="", forma="", lote_id=None,
                       autor, canal):
    from .vendas import _porcao_para_perda

    if lote_id not in (None, "") and not (produto or "").strip():
        l = Lote.objects.select_related("item").filter(id=_inteiro(lote_id, "lote_id")).first()
        if l is None:
            raise ConsultaInvalida("Lote não encontrado.", 404)
        estados = [p["estado"] for p in porcoes(item=l.item) if p["lote_id"] == l.id]
        if (conservacao or "").strip():
            from .acoes import _estado
            estados = [_estado(conservacao)]
        if len(estados) != 1:
            raise ConsultaInvalida("Diga a conservação do lote contado.", 409, opcoes=estados)
        estado = estados[0]
    else:
        i, x = _porcao_para_perda(produto, conservacao=conservacao, forma=forma, lote=lote, lote_id=lote_id)
        l, estado = Lote.objects.select_related("item").get(id=x["lote_id"]), x["estado"]
    if (motivo or "").strip() == "":
        raise ConsultaInvalida("Qual o motivo da contagem? (ex.: contei o freezer, conferência do vencido)")
    c = _decimal(contado, "contado")
    return _proposta("ajustar_contagem", {"lote_id": l.id, "estado": estado, "contado": c, "motivo": motivo},
                     _contagem_resumo(l, estado), autor, canal)


# --- conferência do vencido (caixa de decisões) ---------------------------------------------

_RESPOSTAS = (("ja_saiu", ("vend", "usad", "ja saiu", "ja foi", "ja foram", "saiu", "sairam")),
              ("nao_sei", ("nao sei", "sei la", "contar", "conta", "nao lembro")),
              ("estao_aqui", ("aqui", "esta", "estao", "tem ainda", "ainda tem", "sobrou")))


def _resposta(valor) -> str:
    v = _normal(valor or "").replace("_", " ")
    for chave, sinais in _RESPOSTAS:
        if any(s in v for s in sinais):
            return chave
    raise ConsultaInvalida("'resposta' é uma das três: já foram vendidas, estão aqui ou não sei.")


def pergunta_conferencia(d) -> str:
    """A decisão `lotes_vencidos` dita como pergunta: "o lote do dia 8 de Coxinha venceu ontem com 18 unidades
    no estoque; ainda estão aí? Já foram vendidas, estão aqui ou não sabe?" (números e datas do núcleo)."""
    det = d.get("detalhes") or {}
    lote = Lote.objects.select_related("item").filter(id=det.get("lote_id")).first()
    if lote is None:
        return ""
    produto = lote.item.tipo == "produto"
    base = det.get("unidade_base") or lote.item.unidade_base
    saldo = Decimal(str(det.get("saldo") or 0))
    quanto = _un(saldo) if base == "un" else qtd(saldo, base)
    saiu = "Já foram vendidas" if produto else "Já foram usadas"
    validade = det.get("validade")
    venceu = f"venceu {quando(validade)}" if validade else "venceu"
    return (f"Conferência do vencido: {_porcao_txt(lote, det.get('estado') or '')}, {venceu} com {quanto} no "
            f"estoque. Ainda estão aí? {saiu}, estão aqui ou não sabe?")


def conferir_vencido(*, decisao_id, resposta, destino="", motivo="", contado=None, autor, canal):
    from .decisoes import _decisao, _ja_decidida
    from .vendas import _destino_perda, propor_perda_lote

    d = _decisao(decisao_id)
    if d["origem"] != "lotes_vencidos":
        raise ConsultaInvalida(f"O número {d['decisao_id']} não é conferência de vencido.", 409)
    if d["situacao"] != "pendente":
        raise ConsultaInvalida(_ja_decidida(d), 409)
    det = d["detalhes"]
    lote = Lote.objects.select_related("item").filter(id=det.get("lote_id")).first()
    if lote is None:
        raise ConsultaInvalida("Lote não encontrado.", 404)
    estado = det.get("estado") or ""
    qual = _porcao_txt(lote, estado)
    r = _resposta(resposta)
    produto = lote.item.tipo == "produto"
    if r == "ja_saiu" and not produto:
        r = "nao_sei"  # ingrediente "já foi usado": conta o que sobrou e ajusta
    base = {"decisao_id": d["decisao_id"], "lote_id": lote.id, "lote": nome(lote), "conservacao": estado}
    if r == "ja_saiu":
        return {**base, "proximo": "registrar_venda",
                "texto": (f"Então registre a venda d{qual} com a data em que aconteceu: pergunte quantas, de que "
                          "jeito, para quem e em que dia, e chame registrar_venda com esse lote em 'lotes' (lote_id "
                          f"{lote.id}) e a 'data'. Se a venda foi depois de vencer, vai precisar do motivo.")}
    if r == "estao_aqui":
        if not (destino or "").strip() or not (motivo or "").strip():
            falta = _juntar([x for x, ok in (("o destino (descarte, consumo da equipe, doação ou perda)", destino),
                                             ("o motivo", motivo)) if not (ok or "").strip()])
            raise ConsultaInvalida(f"Estão aqui: pergunte {falta} d{qual}.", 422, **base)
        saldo = saldo_lote(lote, estado)
        if saldo <= 0:
            raise ConsultaInvalida(f"{qual[0].upper() + qual[1:]} já está zerado no estoque.", 409)
        return {**propor_perda_lote(lote, estado, saldo, lote.item.unidade_base, motivo, _destino_perda(destino),
                                    autor=autor, canal=canal), **base}
    if contado in (None, ""):
        raise ConsultaInvalida(f"Peça para contar quantas há de fato d{qual} e chame de novo com 'contado'.", 422,
                               **base)
    texto_motivo = (motivo or "").strip() or f"conferência do vencido (número {d['decisao_id']})"
    return {**_proposta("ajustar_contagem", {"lote_id": lote.id, "estado": estado, "contado": _decimal(contado, "contado"),
                                             "motivo": texto_motivo}, _contagem_resumo(lote, estado), autor, canal),
            **base}
