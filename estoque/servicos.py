from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from cadastros.models import Item
from cadastros.unidades import para_base
from nucleo.operacoes import RegraViolada, executar

from .models import Lote, Movimento


def saldo(item) -> Decimal:
    return Movimento.objects.filter(item=item).aggregate(s=Sum("quantidade"))["s"] or Decimal("0")


def entrada_manual(*, item_id, quantidade, unidade, custo_total, motivo, lote_codigo="",
                   validade=None, autor, canal="web", chave=None) -> dict:
    motivo = (motivo or "").strip()
    if not motivo:
        raise RegraViolada("Informe o motivo da entrada.")
    if quantidade <= 0:
        raise RegraViolada("A quantidade deve ser maior que zero.")
    try:
        item = Item.objects.get(id=item_id)
    except Item.DoesNotExist:
        raise RegraViolada("Item não encontrado.")
    if item.controla_validade and not validade:
        raise RegraViolada(f"Informe a validade de '{item.nome}'.")
    if custo_total < 0:
        raise RegraViolada("O custo total não pode ser negativo.")
    codigo = (lote_codigo or "").strip()

    def func(op):
        qtd = para_base(item, quantidade, unidade).quantize(Decimal("0.001"), ROUND_HALF_UP)
        if qtd <= 0:
            raise RegraViolada("A quantidade deve ser maior que zero.")
        custo = (custo_total / qtd).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        lote = Lote.objects.create(item=item, codigo=codigo, sem_lote=not codigo,
                                   validade=validade, custo_unitario=custo)
        Movimento.objects.create(tipo="entrada_manual", item=item, lote=lote, quantidade=qtd,
                                 motivo=motivo, operacao=op)
        return {"lote_id": lote.id, "quantidade_base": qtd}

    return executar("entrada_manual", func, autor=autor, canal=canal, chave=chave)
