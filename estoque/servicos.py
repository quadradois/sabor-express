from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from cadastros.models import Item
from cadastros.unidades import fator
from nucleo.operacoes import RegraViolada, executar

from .models import Lote, Movimento


def saldo(item) -> Decimal:
    return Movimento.objects.filter(item=item).aggregate(s=Sum("quantidade"))["s"] or Decimal("0")


def entrada_manual(*, item_id, quantidade, unidade, custo_total, motivo, lote_codigo="",
                   validade=None, autor, canal="web", chave=None) -> dict:
    parametros = {"item_id": item_id, "quantidade": quantidade, "unidade": unidade,
                  "custo_total": custo_total, "motivo": motivo, "lote_codigo": lote_codigo,
                  "validade": validade}

    def func(op):
        # validações dentro de executar: recusa também fica na trilha (status "erro")
        texto_motivo = (motivo or "").strip()
        if not texto_motivo:
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
        un, f = fator(item, unidade)
        qtd = (quantidade * f).quantize(Decimal("0.001"), ROUND_HALF_UP)
        if qtd <= 0:
            raise RegraViolada("A quantidade deve ser maior que zero.")
        custo = (custo_total / qtd).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        codigo = (lote_codigo or "").strip()
        lote = Lote.objects.create(item=item, codigo=codigo, sem_lote=not codigo,
                                   validade=validade, custo_unitario=custo)
        Movimento.objects.create(tipo="entrada_manual", item=item, lote=lote, quantidade=qtd,
                                 quantidade_informada=quantidade, unidade_informada=un, fator=f,
                                 motivo=texto_motivo, operacao=op)
        return {"lote_id": lote.id, "quantidade_base": qtd}

    return executar("entrada_manual", func, autor=autor, canal=canal, chave=chave,
                    parametros=parametros)
