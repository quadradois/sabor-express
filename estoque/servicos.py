from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import F, Min, Sum
from django.utils import timezone

from cadastros.models import Item
from cadastros.unidades import fator
from nucleo.operacoes import RegraViolada, executar

from web.templatetags.formato import quantidade as fmt_qtd

from .models import ESTADOS, CriterioValidade, Lote, Movimento


def saldo(item) -> Decimal:
    return Movimento.objects.filter(item=item).aggregate(s=Sum("quantidade"))["s"] or Decimal("0")


def saldo_lote(lote, estado: str = "") -> Decimal:
    return Movimento.objects.filter(lote=lote, estado=estado).aggregate(s=Sum("quantidade"))["s"] or Decimal("0")


def validade_porcao(lote, estado: str = ""):
    v = Movimento.objects.filter(lote=lote, estado=estado, quantidade__gt=0).aggregate(v=Min("validade"))["v"]
    return v or lote.validade


def alocar_fefo(item, quantidade: Decimal, *, hoje) -> list:
    lotes = (Lote.objects.filter(item=item).exclude(validade__lt=hoje)
             .order_by(F("validade").asc(nulls_last=True), "criado_em", "id"))
    falta, saida = quantidade, []
    for l in lotes:
        s = saldo_lote(l)
        if s <= 0:
            continue
        q = min(s, falta)
        saida.append((l, q))
        falta -= q
        if falta <= 0:
            return saida
    raise RegraViolada(f"Falta {fmt_qtd(falta, item.unidade_base)} de '{item.nome}' no estoque.")


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
                                 motivo=texto_motivo, validade=validade, operacao=op)
        return {"lote_id": lote.id, "quantidade_base": qtd}

    return executar("entrada_manual", func, autor=autor, canal=canal, chave=chave,
                    parametros=parametros)


def calcular_validade(produto, forma: str, estado: str, *, hoje, manual, justificativa: str):
    c = CriterioValidade.objects.filter(produto=produto, forma=forma, estado=estado).first()
    if c:
        return hoje + timedelta(days=c.dias), False
    if not manual:
        raise RegraViolada(f"Sem critério de validade para '{produto.nome}' {forma} {estado}: informe a validade.")
    if not (justificativa or "").strip():
        raise RegraViolada("Justifique a validade informada.")
    return manual, True


def transferir_estado(*, lote_id, quantidade, de, para, validade_manual=None, justificativa="",
                      autor, canal="web", chave=None) -> dict:
    parametros = {"lote_id": lote_id, "quantidade": quantidade, "de": de, "para": para,
                  "validade_manual": validade_manual, "justificativa": justificativa}

    def func(op):
        hoje = timezone.localdate()
        if quantidade <= 0:
            raise RegraViolada("A quantidade deve ser maior que zero.")
        if de == para:
            raise RegraViolada("Os estados de origem e destino devem ser diferentes.")
        if {de, para} - {e for e, _ in ESTADOS}:
            raise RegraViolada("Estado inválido.")
        try:
            lote = Lote.objects.select_related("item").get(id=lote_id)
        except Lote.DoesNotExist:
            raise RegraViolada("Lote não encontrado.")
        v = validade_porcao(lote, de)
        if v and v < hoje:
            raise RegraViolada("Lote vencido só aceita descarte.")
        if quantidade > saldo_lote(lote, de):
            raise RegraViolada(f"Só há {fmt_qtd(saldo_lote(lote, de), lote.item.unidade_base)} em {de}.")
        nova, manual = calcular_validade(lote.item, lote.forma, para, hoje=hoje, manual=validade_manual,
                                         justificativa=justificativa)
        for estado, q, val, man in ((de, -quantidade, None, False), (para, quantidade, nova, manual)):
            Movimento.objects.create(tipo="transferencia_estado", item=lote.item, lote=lote, quantidade=q,
                                     quantidade_informada=q, unidade_informada="un", fator=Decimal("1"),
                                     motivo=f"{de} → {para}", estado=estado, validade=val,
                                     validade_manual=man, operacao=op)
        return {"lote_id": lote.id, "validade": nova.isoformat(), "validade_manual": manual}

    return executar("transferir_estado", func, autor=autor, canal=canal, chave=chave, parametros=parametros)
