"""Consultas de compras e recebimento (só leitura), para telas e agente.

Devolvem dicts com Decimal e date; quem expõe em JSON serializa
(ex.: DjangoJSONEncoder). Quantidades na unidade base do item.
"""

from django.utils import timezone

from financeiro.consultas import detalhe_conta

from .models import Compra, LinhaCompra
from .servicos import pendente_linha, recebido_linha

ABERTAS = ("aprovada", "parcial")


def _linha(l, hoje) -> dict:
    return {
        "linha_id": l.id, "item_id": l.item_id, "item": l.item.nome, "unidade_base": l.item.unidade_base,
        "quantidade": l.quantidade, "unidade": l.unidade, "fator": l.fator, "documentado": l.quantidade_base,
        "recebido": recebido_linha(l), "encerrado": l.encerrado, "pendente": pendente_linha(l),
        "motivo_encerramento": l.motivo_encerramento, "valor": l.valor, "custo_unitario": l.custo_unitario,
        "dias": (hoje - l.compra.data).days,
    }


def compras_em_aberto(*, fornecedor_id=None) -> list[dict]:
    """Compras aprovadas ou parcialmente recebidas, da mais antiga para a mais nova."""
    hoje = timezone.localdate()
    qs = Compra.objects.select_related("fornecedor").filter(status__in=ABERTAS).order_by("data", "id")
    if fornecedor_id:
        qs = qs.filter(fornecedor_id=fornecedor_id)
    return [{"compra_id": c.id, "fornecedor": c.fornecedor.nome, "data": c.data, "total": c.total,
             "status": c.status, "dias": (hoje - c.data).days,
             "pendentes": [d for d in (_linha(l, hoje) for l in c.linhas.select_related("item", "compra"))
                           if d["pendente"] > 0]} for c in qs]


def falta_receber(*, compra_id=None, item_id=None) -> list[dict]:
    """Linhas com pendência de recebimento e a idade em dias (RF-REC-05). Indisponível para uso (RN-03)."""
    hoje = timezone.localdate()
    qs = (LinhaCompra.objects.select_related("item", "compra__fornecedor")
          .filter(compra__status__in=ABERTAS).order_by("compra__data", "compra_id", "ordem"))
    if compra_id:
        qs = qs.filter(compra_id=compra_id)
    if item_id:
        qs = qs.filter(item_id=item_id)
    return [{**d, "compra_id": l.compra_id, "fornecedor": l.compra.fornecedor.nome}
            for l in qs if (d := _linha(l, hoje))["pendente"] > 0]


def detalhe_compra(compra_id) -> dict | None:
    c = Compra.objects.select_related("fornecedor", "operacao").filter(id=compra_id).first()
    if c is None:
        return None
    hoje = timezone.localdate()
    linhas = list(c.linhas.select_related("item", "compra"))
    return {
        "compra_id": c.id, "fornecedor_id": c.fornecedor_id, "fornecedor": c.fornecedor.nome, "data": c.data,
        "documento": c.documento, "frete": c.frete, "desconto": c.desconto, "acrescimo": c.acrescimo,
        "total": c.total, "soma_itens": sum(l.valor for l in linhas), "justificativa": c.justificativa,
        "status": c.status, "status_texto": c.get_status_display(), "motivo_cancelamento": c.motivo_cancelamento,
        "aprovada_por": c.operacao.autor, "aprovada_em": c.operacao.criado_em, "canal": c.operacao.canal,
        "linhas": [{**_linha(l, hoje), "recebimentos": [
            {"recebimento_id": r.id, "lote_id": r.lote_id, "lote_codigo": r.lote.codigo, "validade": r.lote.validade,
             "quantidade": r.quantidade, "recebido_em": r.criado_em, "estornado": r.estorno_operacao_id is not None,
             "motivo_estorno": r.motivo_estorno} for r in l.recebimentos.select_related("lote").order_by("id")]}
            for l in linhas],
        "conta": detalhe_conta(c.conta),
    }


def possiveis_duplicatas(*, fornecedor_id, data_compra, total, documento="") -> list[dict]:
    """Para avisar antes de lançar (RN-05 c/d): mesmo documento, ou mesmo fornecedor + data + total."""
    qs = Compra.objects.exclude(status="cancelada").filter(fornecedor_id=fornecedor_id)
    achadas = {c.id: c for c in qs.filter(data=data_compra, total=total)}
    if (documento or "").strip():
        achadas.update({c.id: c for c in qs.filter(documento__iexact=documento.strip())})
    return [{"compra_id": c.id, "data": c.data, "total": c.total, "documento": c.documento,
             "bloqueia": bool(documento and c.documento.lower() == documento.strip().lower())}
            for c in sorted(achadas.values(), key=lambda c: c.id)]


def ultimo_custo(item_id) -> dict | None:
    """Custo de referência (RN-23): custo unitário da última compra aprovada do item; None se nunca comprado."""
    l = (LinhaCompra.objects.select_related("compra__fornecedor").exclude(compra__status="cancelada")
         .filter(item_id=item_id).order_by("-compra__data", "-compra_id", "-id").first())
    if l is None:
        return None
    return {"custo_unitario": l.custo_unitario, "compra_id": l.compra_id, "data": l.compra.data,
            "fornecedor": l.compra.fornecedor.nome}
