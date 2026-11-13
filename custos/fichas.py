"""Custo estimado da ficha técnica (RF-FIC-02, RF-CUS-05, RN-23, CA-14) — só leitura.

Referência de um item = custo unitário da **última compra aprovada** (não cancelada) até o dia `em` (RN-23,
`compras.consultas.ultimo_custo`). Item nunca comprado não tem referência: o custo fica **incompleto**
(`completo=False`, valor `None`, item em `faltando`) — nunca vira zero.

Cascata (a mesma de `fichas.escala`): o produto (um tamanho, design §6.3.7) usa `peso_g × percentual` de
cada preparação; a preparação escala itens e sub-preparações por `gramas ÷ rendimento_g`. O custo de
ingredientes é Σ(quantidade × referência) de todas as linhas de item da cascata. Óleo e indiretos de
referência por unidade (`Item.oleo_ref_un`, `Item.indireto_ref_un`) aparecem separados (RF-CUS-05).
"""

from decimal import ROUND_HALF_UP, Decimal

from cadastros.models import Item
from compras.consultas import ultimo_custo
from fichas.models import Ficha
from fichas.validacao import validar_ficha
from nucleo.operacoes import RegraViolada

ZERO = Decimal("0")
Q3, Q4 = Decimal("0.001"), Decimal("0.0001")

INCLUI_INGREDIENTES = "ingredientes pela última compra de cada um"
NAO_INCLUI_SEMPRE = ["perdas da produção (o estimado supõe que todas as unidades saem boas)",
                     "embalagem de venda (entra na margem da apresentação)",
                     "tributos e despesas comerciais"]


def _q(v, casas=Q4):
    return None if v is None else v.quantize(casas, ROUND_HALF_UP)


class _Referencias:
    """Uma consulta de última compra por item, por cálculo."""

    def __init__(self, em):
        self.em, self._cache = em, {}

    def __call__(self, item_id):
        if item_id not in self._cache:
            self._cache[item_id] = ultimo_custo(item_id, ate=self.em)
        return self._cache[item_id]


def _blocos(prep, gramas, refs, saida):
    """Pós-ordem, como `fichas.escala._expandir`: sub-preparações antes de quem as usa."""
    validar_ficha(prep)
    fator = gramas / prep.rendimento_g
    for c in prep.subpreparacoes.select_related("preparacao").order_by("ordem", "id"):
        _blocos(c.preparacao, c.quantidade_g * fator, refs, saida)
    itens = []
    for c in prep.itens.select_related("item").order_by("ordem", "id"):
        q = c.quantidade * fator
        r = refs(c.item_id)
        itens.append({"item_id": c.item_id, "item": c.item.nome, "unidade_base": c.item.unidade_base,
                      "quantidade": q, "referencia": r["custo_unitario"] if r else None,
                      "compra_id": r["compra_id"] if r else None, "data_compra": r["data"] if r else None,
                      "fornecedor": r["fornecedor"] if r else "",
                      "custo": q * r["custo_unitario"] if r else None})
    saida.append({"ficha_id": prep.id, "nome": prep.nome, "gramas": gramas, "itens": itens})


def _fechar(blocos) -> dict:
    """Soma os blocos: total exato (ou None se faltar referência), o conhecido, e o que faltou."""
    faltando, conhecido = {}, ZERO
    for b in blocos:
        conhecidos = [i["custo"] for i in b["itens"] if i["custo"] is not None]
        b["custo_conhecido"] = sum(conhecidos, ZERO)
        b["completo"] = len(conhecidos) == len(b["itens"])
        b["custo"] = b["custo_conhecido"] if b["completo"] else None
        conhecido += b["custo_conhecido"]
        for i in b["itens"]:
            if i["custo"] is None:
                faltando.setdefault(i["item_id"], {"item_id": i["item_id"], "item": i["item"],
                                                   "motivo": "nunca comprado"})
    completo = not faltando
    return {"completo": completo, "total": conhecido if completo else None, "conhecido": conhecido,
            "faltando": sorted(faltando.values(), key=lambda f: f["item"])}


def _arredondar(blocos):
    return [{**b, "gramas": _q(b["gramas"], Q3), "custo": _q(b["custo"]), "custo_conhecido": _q(b["custo_conhecido"]),
             "itens": [{**i, "quantidade": _q(i["quantidade"], Q3), "custo": _q(i["custo"])} for i in b["itens"]]}
            for b in blocos]


def custo_estimado(*, produto_id, em=None) -> dict:
    """Custo estimado de **uma unidade** do produto (um tamanho), pela ficha vigente e pelas referências do dia
    `em` (padrão: hoje, a última compra). Recusa com `RegraViolada` se o produto não existe ou a ficha é inválida.

    `ingredientes` = Σ(quantidade por unidade × referência), `None` se faltar referência (ver `faltando`;
    `ingredientes_conhecido` soma só o que tem referência). `custo_cru` = ingredientes + indiretos (se houver
    referência); `custo_frito` = custo_cru + óleo de referência (`None` sem óleo). `inclui`/`nao_inclui`
    dizem o que entra (RF-CUS-06)."""
    produto = Item.objects.select_related("ficha").filter(id=produto_id, tipo="produto").first()
    if produto is None or produto.ficha_id is None:
        raise RegraViolada("Produto não encontrado.")
    ficha = produto.ficha
    validar_ficha(ficha)
    refs, blocos = _Referencias(em), []
    for p in ficha.proporcoes.select_related("preparacao").order_by("ordem", "id"):
        _blocos(p.preparacao, produto.peso_g * p.percentual / 100, refs, blocos)
    soma = _fechar(blocos)
    ingredientes = soma["total"]
    indiretos, oleo = produto.indireto_ref_un, produto.oleo_ref_un
    inclui, nao_inclui = [INCLUI_INGREDIENTES], list(NAO_INCLUI_SEMPRE)
    if indiretos is not None:
        inclui.append("indiretos de referência por unidade (mão de obra, gás, energia)")
    else:
        nao_inclui.insert(0, "indiretos (mão de obra, gás, energia): sem valor de referência cadastrado")
    custo_cru = None if ingredientes is None else ingredientes + (indiretos or ZERO)
    custo_frito = None if custo_cru is None or oleo is None else custo_cru + oleo
    versao = ficha.versoes.last()
    return {
        "produto_id": produto.id, "produto": produto.nome, "ficha_id": ficha.id, "ficha": ficha.nome,
        "versao": versao.numero if versao else None, "peso_g": produto.peso_g, "em": em,
        "completo": soma["completo"], "faltando": soma["faltando"],
        "ingredientes": _q(ingredientes), "ingredientes_conhecido": _q(soma["conhecido"]),
        "indiretos": indiretos, "oleo": oleo, "custo_cru": _q(custo_cru), "custo_frito": _q(custo_frito),
        "inclui": inclui, "nao_inclui": nao_inclui, "blocos": _arredondar(blocos),
    }


def custos_estimados(*, ativos=True, em=None) -> list[dict]:
    """`custo_estimado` de cada produto (tamanho), por nome. Ficha inválida não derruba a lista: o produto
    vem com `erro` (a mensagem do núcleo) e sem números."""
    qs = Item.objects.filter(tipo="produto", ficha__isnull=False).order_by("nome")
    if ativos:
        qs = qs.filter(ativo=True)
    saida = []
    for p in qs:
        try:
            saida.append(custo_estimado(produto_id=p.id, em=em))
        except RegraViolada as e:
            saida.append({"produto_id": p.id, "produto": p.nome, "erro": str(e), "completo": False})
    return saida


def custo_preparacao(*, ficha_id, gramas=None, em=None) -> dict:
    """Custo estimado de uma preparação (massa, recheio...) para `gramas` (padrão: o rendimento da ficha),
    em cascata pelas sub-preparações. `por_kg` = total ÷ gramas × 1000. Mesmas regras de `custo_estimado`."""
    prep = Ficha.objects.filter(id=ficha_id, tipo="preparacao").first()
    if prep is None:
        raise RegraViolada("Preparação não encontrada.")
    validar_ficha(prep)
    g = Decimal(str(gramas)) if gramas not in (None, "") else prep.rendimento_g
    if g <= 0:
        raise RegraViolada("A quantidade deve ser maior que zero.")
    blocos = []
    _blocos(prep, g, _Referencias(em), blocos)
    soma = _fechar(blocos)
    return {"ficha_id": prep.id, "nome": prep.nome, "rendimento_g": prep.rendimento_g, "gramas": _q(g, Q3),
            "em": em, "completo": soma["completo"], "faltando": soma["faltando"], "total": _q(soma["total"]),
            "conhecido": _q(soma["conhecido"]),
            "por_kg": _q(soma["total"] / g * 1000) if soma["total"] is not None else None,
            "blocos": _arredondar(blocos)}
