"""Consultas de vendas, encomendas, preços, estoque para venda, necessidade de produção e sobras
(só leitura), para telas, agente e resumo do dia. Devolvem Decimal, date e time; nada grava.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from cadastros.models import Cliente
from estoque.models import Lote
from estoque.servicos import livre_porcao, porcoes
from producao.models import Fritura

from .models import Apresentacao, Encomenda, Venda

ZERO = Decimal("0")


def clientes(*, ativos=True) -> list[dict]:
    qs = Cliente.objects.order_by("nome")
    if ativos:
        qs = qs.filter(ativo=True)
    return [{"cliente_id": c.id, "nome": c.nome, "contato": c.contato, "ativo": c.ativo} for c in qs]


# ---------- estoque para venda ----------

def estoque_para_venda(*, produto_id=None, hoje=None) -> list[dict]:
    """Por produto, forma e conservação: saldo, reservado, vencido e livre (o que dá para vender agora)."""
    hoje = hoje or timezone.localdate()
    grupos = defaultdict(lambda: {"saldo": ZERO, "reservado": ZERO, "vencido": ZERO, "livre": ZERO})
    lotes = Lote.objects.filter(item__tipo="produto").select_related("item").in_bulk()
    for p in porcoes(hoje=hoje):
        lote = lotes.get(p["lote_id"])
        if lote is None or (produto_id and lote.item_id != produto_id):
            continue
        g = grupos[(lote.item_id, lote.item.nome, lote.forma, p["estado"])]
        g["saldo"] += p["saldo"]
        if p["vencido"]:
            g["vencido"] += p["saldo"]
        else:
            livre = livre_porcao(lote, p["estado"])
            g["livre"] += livre
            g["reservado"] += p["saldo"] - livre
    return [{"produto_id": k[0], "produto": k[1], "forma": k[2], "estado": k[3], **v}
            for k, v in sorted(grupos.items(), key=lambda x: (x[0][1], x[0][2], x[0][3]))]


def _livres(hoje):
    return {(e["produto_id"], e["forma"], e["estado"]): e["livre"] for e in estoque_para_venda(hoje=hoje)}


def apresentacoes(*, produto_id=None, ativas=True, hoje=None) -> list[dict]:
    """Tabela de preços (RF-CAD-04) com quanto dá para vender agora de cada apresentação."""
    hoje = hoje or timezone.localdate()
    livres = _livres(hoje)
    qs = Apresentacao.objects.select_related("produto", "embalagem").order_by("produto__nome", "unidades", "nome")
    if produto_id:
        qs = qs.filter(produto_id=produto_id)
    if ativas:
        qs = qs.filter(ativo=True, produto__ativo=True)
    saida = []
    for a in qs:
        livre = livres.get((a.produto_id, a.forma, a.estado), ZERO)
        saida.append({"apresentacao_id": a.id, "produto_id": a.produto_id, "produto": a.produto.nome, "nome": a.nome,
                      "descricao": str(a), "forma": a.forma, "estado": a.estado, "unidades": a.unidades,
                      "preco_varejo": a.preco_varejo, "preco_atacado": a.preco_atacado,
                      "embalagem_id": a.embalagem_id, "embalagem": str(a.embalagem or ""), "embalagens": a.embalagens,
                      "ativo": a.ativo, "livre_unidades": livre, "livre_apresentacoes": int(livre // a.unidades)})
    return saida


# ---------- vendas ----------

def _venda(v) -> dict:
    conta = getattr(v, "conta", None)
    return {"venda_id": v.id, "data": v.data, "cliente_id": v.cliente_id, "cliente": str(v.cliente or ""),
            "tabela": v.tabela, "condicao": v.condicao, "forma_pagamento": v.forma_pagamento, "total": v.total,
            "recebido_na_hora": v.recebido_na_hora, "a_prazo": conta.total if conta else ZERO, "custo": v.custo,
            "encomenda_id": v.encomenda_id, "situacao": v.situacao, "motivo_cancelamento": v.motivo_cancelamento,
            "destino": v.destino, "valor_devolvido": v.valor_devolvido, "conta_id": conta.id if conta else None,
            "linhas": [{"apresentacao_id": l.apresentacao_id, "apresentacao": str(l.apresentacao),
                        "produto_id": l.apresentacao.produto_id, "produto": l.apresentacao.produto.nome,
                        "quantidade": l.quantidade, "unidades": l.quantidade * l.unidades_por,
                        "preco_tabela": l.preco_tabela, "preco": l.preco, "total": l.total, "custo": l.custo}
                       for l in v.linhas.select_related("apresentacao__produto")]}


def vendas(*, de=None, ate=None, cliente_id=None, incluir_canceladas=False) -> dict:
    """Vendas por período (dias, inclusive) com os totais já somados (RF-REL-02). Canceladas ficam fora
    dos totais; com `incluir_canceladas` aparecem na lista. `margem_estimada` = (total − custo) ÷ total,
    sem tributos, despesas e indiretos (RF-CUS-06)."""
    qs = Venda.objects.select_related("cliente", "conta", "encomenda").order_by("data", "id")
    if de:
        qs = qs.filter(data__gte=de)
    if ate:
        qs = qs.filter(data__lte=ate)
    if cliente_id:
        qs = qs.filter(cliente_id=cliente_id)
    if not incluir_canceladas:
        qs = qs.filter(situacao="concluida")
    lista = [_venda(v) for v in qs]
    validas = [v for v in lista if v["situacao"] == "concluida"]
    total = sum((v["total"] for v in validas), ZERO)
    custo = sum((v["custo"] for v in validas), ZERO)
    por_forma, por_produto = defaultdict(lambda: ZERO), defaultdict(lambda: {"unidades": 0, "total": ZERO})
    for v in validas:
        if v["recebido_na_hora"]:
            por_forma[v["forma_pagamento"] or "não informada"] += v["recebido_na_hora"]
        for l in v["linhas"]:
            p = por_produto[l["produto"]]
            p["unidades"] += l["unidades"]
            p["total"] += l["total"]
    return {"vendas": lista, "totais": {
        "vendas": len(validas), "total": total, "custo": custo,
        "recebido_na_hora": sum((v["recebido_na_hora"] for v in validas), ZERO),
        "a_prazo": sum((v["a_prazo"] for v in validas), ZERO),
        "margem_estimada": ((total - custo) / total).quantize(Decimal("0.001")) if total else None,
        "por_forma_pagamento": dict(por_forma),
        "por_produto": [{"produto": k, **v} for k, v in sorted(por_produto.items(), key=lambda x: -x[1]["total"])],
        "canceladas": sum(v["situacao"] == "cancelada" for v in lista)}}


def vendas_do_dia(*, hoje=None) -> dict:
    hoje = hoje or timezone.localdate()
    return vendas(de=hoje, ate=hoje)


def detalhe_venda(venda_id) -> dict | None:
    v = Venda.objects.select_related("cliente", "encomenda").filter(id=venda_id).first()
    return None if v is None else _venda(v)


# ---------- encomendas ----------

def _encomenda(e, hoje) -> dict:
    itens, falta = [], ZERO
    for ie in e.itens.select_related("apresentacao__produto"):
        res = ie.reservas.filter(situacao__in=("ativa", "baixada")).aggregate(s=Sum("quantidade"))["s"] or ZERO
        f = max(Decimal(ie.unidades) - res, ZERO)
        falta += f
        itens.append({"item_encomenda_id": ie.id, "apresentacao_id": ie.apresentacao_id,
                      "apresentacao": str(ie.apresentacao), "produto_id": ie.apresentacao.produto_id,
                      "produto": ie.apresentacao.produto.nome,
                      "forma": ie.apresentacao.forma, "estado": ie.apresentacao.estado,
                      "quantidade": ie.quantidade, "unidades": ie.unidades, "preco": ie.preco,
                      "preco_tabela": ie.preco_tabela, "total": ie.total, "reservado": res, "falta": f})
    situacao = e.situacao if e.situacao != "aberta" else ("pronta" if falta == 0 else "aberta")
    venda = getattr(e, "venda", None)
    return {"encomenda_id": e.id, "cliente_id": e.cliente_id, "cliente": e.cliente.nome,
            "entrega_data": e.entrega_data, "entrega_hora": e.entrega_hora, "dias": (e.entrega_data - hoje).days,
            "modo": e.modo, "observacao": e.observacao, "tabela": e.tabela, "total": e.total, "sinal": e.sinal,
            "sinal_forma": e.sinal_forma, "saldo": e.total - e.sinal, "situacao": situacao, "falta": falta,
            "itens": itens, "venda_id": venda.id if venda else None, "criada_em": e.criado_em,
            "motivo_cancelamento": e.motivo_cancelamento, "sinal_devolvido": e.sinal_devolvido}


def encomendas(*, situacao="abertas", de=None, ate=None, cliente_id=None, hoje=None) -> list[dict]:
    """Encomendas por dia de entrega (RF-VEN-11). `situacao`: "abertas" (aberta ou pronta, padrão),
    "aberta", "pronta", "entregue", "cancelada" ou None (todas). `de`/`ate` filtram o dia da entrega."""
    hoje = hoje or timezone.localdate()
    qs = Encomenda.objects.select_related("cliente").order_by("entrega_data", "entrega_hora", "id")
    if situacao in ("abertas", "aberta", "pronta"):
        qs = qs.filter(situacao="aberta")
    elif situacao:
        qs = qs.filter(situacao=situacao)
    if de:
        qs = qs.filter(entrega_data__gte=de)
    if ate:
        qs = qs.filter(entrega_data__lte=ate)
    if cliente_id:
        qs = qs.filter(cliente_id=cliente_id)
    lista = [_encomenda(e, hoje) for e in qs]
    if situacao in ("aberta", "pronta"):
        lista = [e for e in lista if e["situacao"] == situacao]
    return lista


def encomendas_do_dia(*, hoje=None) -> list[dict]:
    """Encomendas abertas (ou prontas) para entregar hoje."""
    hoje = hoje or timezone.localdate()
    return encomendas(de=hoje, ate=hoje, hoje=hoje)


def detalhe_encomenda(encomenda_id) -> dict | None:
    e = Encomenda.objects.select_related("cliente").filter(id=encomenda_id).first()
    return None if e is None else _encomenda(e, timezone.localdate())


def necessidade_producao(*, dias=3, hoje=None) -> list[dict]:
    """O que falta para atender as encomendas abertas até hoje + `dias` (RF-VEN-06), por produto, forma e
    conservação: `falta` (pedido − reservado), `livre` (estoque que já dá para reservar com
    `completar_reserva`) e `a_produzir` = falta − livre. Não cria produção (DEC-F2-019)."""
    hoje = hoje or timezone.localdate()
    livres = _livres(hoje)
    grupos = {}
    for e in encomendas(ate=hoje + timedelta(days=dias), hoje=hoje):
        for i in e["itens"]:
            if i["falta"] <= 0:
                continue
            chave = (i["produto_id"], i["forma"], i["estado"])
            g = grupos.setdefault(chave, {"produto_id": i["produto_id"], "produto": i["produto"],
                                          "forma": i["forma"], "estado": i["estado"], "falta": ZERO,
                                          "primeira_entrega": e["entrega_data"], "encomendas": []})
            g["falta"] += i["falta"]
            g["primeira_entrega"] = min(g["primeira_entrega"], e["entrega_data"])
            if e["encomenda_id"] not in g["encomendas"]:
                g["encomendas"].append(e["encomenda_id"])
    saida = []
    for chave, g in grupos.items():
        livre = livres.get(chave, ZERO)
        saida.append({**g, "livre": livre, "a_produzir": max(g["falta"] - livre, ZERO)})
    return sorted(saida, key=lambda g: (g["primeira_entrega"], g["produto"], g["forma"], g["estado"]))


# ---------- fritura e sobras ----------

def frituras(*, de=None, ate=None) -> list[dict]:
    qs = Fritura.objects.select_related("lote_origem__item", "lote").order_by("criado_em", "id")
    if de:
        qs = qs.filter(criado_em__date__gte=de)
    if ate:
        qs = qs.filter(criado_em__date__lte=ate)
    return [{"fritura_id": f.id, "produto": f.lote_origem.item.nome, "lote_origem_id": f.lote_origem_id,
             "lote_id": f.lote_id, "fritas": f.quantidade, "boas": f.boas, "perdas": f.perdas,
             "perda_motivo": f.perda_motivo, "custo_total": f.custo_total, "custo_unitario": f.custo_unitario,
             "criado_em": f.criado_em} for f in qs]


def sobras_fritas(*, hoje=None, ate_ontem=False) -> list[dict]:
    """Porções de lotes fritos com saldo (RF-FRI-03): o que sobrou e precisa de destino (perda ou
    outro permitido). `ate_ontem=True` só traz os fritos de dias anteriores (a rotina avisa esses)."""
    hoje = hoje or timezone.localdate()
    fritos = Lote.objects.filter(forma="frito").in_bulk()
    saida = []
    for p in porcoes(hoje=hoje):
        lote = fritos.get(p["lote_id"])
        if lote is None:
            continue
        criado = timezone.localtime(lote.criado_em).date()
        if ate_ontem and criado >= hoje:
            continue
        saida.append({**p, "frito_em": criado, "reservado": p["saldo"] - livre_porcao(lote, p["estado"])})
    return saida


def lotes_para_fritar(*, produto_id, hoje=None) -> list[dict]:
    """Porções cruas do produto que podem ir para a fritura (não vencidas, com unidades livres), da que vence
    primeiro (RN-18): a primeira é a sugestão de `registrar_fritura`."""
    hoje = hoje or timezone.localdate()
    crus = Lote.objects.filter(item_id=produto_id, forma="cru").in_bulk()
    saida = []
    for p in porcoes(item=produto_id, hoje=hoje):
        lote = crus.get(p["lote_id"])
        if lote is None or p["vencido"]:
            continue
        livre = livre_porcao(lote, p["estado"])
        if livre > 0:
            saida.append({**p, "livre": livre, "custo_unitario": lote.custo_unitario})
    return saida
