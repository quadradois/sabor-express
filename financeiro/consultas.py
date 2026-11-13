"""Consultas de contas a pagar e a receber (só leitura), para telas e agente.

As consultas antigas continuam sendo de contas a pagar (`tipo="pagar"` por padrão); as de receber
passam `tipo="receber"` ou usam as funções `*_receber` / `devido_por_cliente` / `recebimentos`.

Devolvem dicts com Decimal e date; quem expõe em JSON serializa
(ex.: DjangoJSONEncoder). Nenhuma conta é feita fora daqui e de `servicos`.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import AvisoAjuste, Pagamento, Parcela
from .servicos import pago_parcela, situacao_parcela


def _parcela(p, hoje) -> dict:
    pago = pago_parcela(p)
    situacao = situacao_parcela(p)
    return {
        "parcela_id": p.id, "conta_id": p.conta_id, "tipo": p.conta.tipo, "compra_id": p.conta.compra_id,
        "fornecedor_id": p.conta.fornecedor_id, "fornecedor": str(p.conta.fornecedor or ""),
        "venda_id": p.conta.venda_id, "cliente_id": p.conta.cliente_id, "cliente": str(p.conta.cliente or ""),
        "descricao": p.conta.descricao, "numero": p.numero, "de": p.conta.parcelas.count(),
        "valor": p.valor, "pago": pago, "saldo": Decimal("0") if situacao == "cancelada" else p.valor - pago,
        "vencimento": p.vencimento, "dias": (p.vencimento - hoje).days, "situacao": situacao,
        "vencida": situacao in ("aberta", "parcial") and p.vencimento < hoje,
    }


def parcelas_em_aberto(*, ate=None, fornecedor_id=None, cliente_id=None, tipo="pagar", hoje=None) -> list[dict]:
    """Parcelas abertas ou parcialmente pagas, por vencimento. `ate` limita o vencimento (inclusive)."""
    hoje = hoje or timezone.localdate()
    qs = Parcela.objects.select_related("conta__fornecedor", "conta__cliente").filter(conta__cancelada=False,
                                                                                     conta__tipo=tipo)
    if ate:
        qs = qs.filter(vencimento__lte=ate)
    if fornecedor_id:
        qs = qs.filter(conta__fornecedor_id=fornecedor_id)
    if cliente_id:
        qs = qs.filter(conta__cliente_id=cliente_id)
    return [d for d in (_parcela(p, hoje) for p in qs) if d["situacao"] in ("aberta", "parcial")]


def contas_vencidas(*, tipo="pagar", hoje=None) -> list[dict]:
    hoje = hoje or timezone.localdate()
    return [d for d in parcelas_em_aberto(tipo=tipo, hoje=hoje) if d["vencida"]]


def contas_a_vencer(*, dias=7, tipo="pagar", hoje=None) -> list[dict]:
    """Parcelas em aberto que vencem de hoje até hoje + dias (as vencidas ficam em `contas_vencidas`)."""
    hoje = hoje or timezone.localdate()
    return [d for d in parcelas_em_aberto(ate=hoje + timedelta(days=dias), tipo=tipo, hoje=hoje)
            if not d["vencida"]]


def receber_em_aberto(*, cliente_id=None, hoje=None) -> list[dict]:
    """Parcelas a receber abertas ou parciais (RF-FIN-06), por vencimento."""
    return parcelas_em_aberto(cliente_id=cliente_id, tipo="receber", hoje=hoje)


def receber_vencidas(*, hoje=None) -> list[dict]:
    return contas_vencidas(tipo="receber", hoje=hoje)


def receber_a_vencer(*, dias=7, hoje=None) -> list[dict]:
    return contas_a_vencer(dias=dias, tipo="receber", hoje=hoje)


def devido_por_cliente(*, hoje=None) -> list[dict]:
    """Quanto cada cliente deve (`devido`) e quanto disso já venceu (`vencido`), do maior para o menor."""
    hoje = hoje or timezone.localdate()
    soma = defaultdict(lambda: {"devido": Decimal("0"), "vencido": Decimal("0"), "parcelas": 0})
    nomes = {}
    for d in receber_em_aberto(hoje=hoje):
        s = soma[d["cliente_id"]]
        s["devido"] += d["saldo"]
        s["vencido"] += d["saldo"] if d["vencida"] else 0
        s["parcelas"] += 1
        nomes[d["cliente_id"]] = d["cliente"]
    saida = [{"cliente_id": c, "cliente": nomes[c], **v} for c, v in soma.items()]
    return sorted(saida, key=lambda x: (-x["devido"], x["cliente"]))


def devido_por_fornecedor(*, hoje=None) -> list[dict]:
    """Saldo devedor por fornecedor, do maior para o menor."""
    hoje = hoje or timezone.localdate()
    soma = defaultdict(lambda: {"devido": Decimal("0"), "vencido": Decimal("0"), "parcelas": 0})
    nomes = {}
    for d in parcelas_em_aberto(tipo="pagar", hoje=hoje):
        s = soma[d["fornecedor_id"]]
        s["devido"] += d["saldo"]
        s["vencido"] += d["saldo"] if d["vencida"] else 0
        s["parcelas"] += 1
        nomes[d["fornecedor_id"]] = d["fornecedor"]
    saida = [{"fornecedor_id": f, "fornecedor": nomes[f], **v} for f, v in soma.items()]
    return sorted(saida, key=lambda x: (-x["devido"], x["fornecedor"]))


def detalhe_conta(conta) -> dict:
    hoje = timezone.localdate()
    return {
        "conta_id": conta.id, "tipo": conta.tipo, "venda_id": conta.venda_id, "cliente_id": conta.cliente_id,
        "descricao": conta.descricao, "total": conta.total, "cancelada": conta.cancelada,
        "parcelas": [{**_parcela(p, hoje), "pagamentos": [_pagamento(pg) for pg in p.pagamentos.order_by("id")]}
                     for p in conta.parcelas.select_related("conta__fornecedor", "conta__cliente")],
        "avisos": [_aviso(a) for a in conta.avisos.order_by("id")],
    }


def _pagamento(pg) -> dict:
    return {"pagamento_id": pg.id, "parcela_id": pg.parcela_id, "valor": pg.valor, "valor_pago": pg.valor_pago,
            "data": pg.data, "forma": pg.forma, "diferenca": pg.diferenca, "diferenca_tipo": pg.diferenca_tipo,
            "diferenca_motivo": pg.diferenca_motivo, "estornado": pg.estorno_operacao_id is not None,
            "motivo_estorno": pg.motivo_estorno}


def pagamentos(*, de=None, ate=None, fornecedor_id=None, cliente_id=None, tipo="pagar",
               incluir_estornados=False) -> list[dict]:
    """Pagamentos (ou, com `tipo="receber"`, recebimentos) anotados por período (RF-FIN-10)."""
    qs = (Pagamento.objects.select_related("parcela__conta__fornecedor", "parcela__conta__cliente")
          .filter(parcela__conta__tipo=tipo).order_by("data", "id"))
    if de:
        qs = qs.filter(data__gte=de)
    if ate:
        qs = qs.filter(data__lte=ate)
    if fornecedor_id:
        qs = qs.filter(parcela__conta__fornecedor_id=fornecedor_id)
    if cliente_id:
        qs = qs.filter(parcela__conta__cliente_id=cliente_id)
    if not incluir_estornados:
        qs = qs.filter(estorno_operacao__isnull=True)
    return [{**_pagamento(pg), "fornecedor": str(pg.parcela.conta.fornecedor or ""),
             "cliente": str(pg.parcela.conta.cliente or ""), "venda_id": pg.parcela.conta.venda_id,
             "descricao": pg.parcela.conta.descricao} for pg in qs]


def recebimentos(*, de=None, ate=None, cliente_id=None, incluir_estornados=False) -> list[dict]:
    """Recebimentos de clientes anotados por período (RF-FIN-10)."""
    return pagamentos(de=de, ate=ate, cliente_id=cliente_id, tipo="receber", incluir_estornados=incluir_estornados)


def _aviso(a) -> dict:
    return {"aviso_id": a.id, "conta_id": a.conta_id, "compra_id": a.conta.compra_id, "texto": a.texto,
            "criado_em": a.criado_em, "resolvido": a.resolvido_operacao_id is not None, "observacao": a.observacao}


def avisos_de_ajuste(*, abertos=True) -> list[dict]:
    qs = AvisoAjuste.objects.select_related("conta").order_by("criado_em", "id")
    if abertos:
        qs = qs.filter(resolvido_operacao__isnull=True)
    return [_aviso(a) for a in qs]
