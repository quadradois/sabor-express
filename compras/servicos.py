"""Compras manuais, recebimento físico e pendências (PRD §7.3/7.4, FL-01/02/09).

Aprovar a compra, receber, a obrigação financeira e o pagamento são eventos
distintos (RN-04): cada um é uma operação própria pelo `executar()`.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from cadastros.models import Fornecedor, Item
from cadastros.unidades import fator
from estoque.models import ConsumoPendente, Lote, Movimento
from estoque.servicos import saldo_lote
from financeiro.models import Pagamento
from financeiro.servicos import abrir_conta, avisar_ajuste
from nucleo.operacoes import RegraViolada, executar
from nucleo.valores import data, decimal, reais
from web.templatetags.formato import dinheiro
from web.templatetags.formato import quantidade as fmt_qtd

from .models import Compra, LinhaCompra, Recebimento

MIL = Decimal("0.001")


# ---------- leitura (sem gravar) ----------

def recebido_linha(linha) -> Decimal:
    return (linha.recebimentos.filter(estorno_operacao__isnull=True)
            .aggregate(s=Sum("quantidade"))["s"] or Decimal("0"))


def pendente_linha(linha) -> Decimal:
    """Documentado − recebido − encerrado como não entregue (unidade base)."""
    if linha.compra.status == "cancelada":
        return Decimal("0")
    return linha.quantidade_base - recebido_linha(linha) - linha.encerrado


def custos_das_linhas(linhas, *, frete, desconto, acrescimo) -> list[Decimal]:
    """RN-20: (valor + rateio de frete e acréscimo − rateio de desconto) ÷ quantidade base, 4 casas.

    `linhas` = [(valor, quantidade_base)]. O rateio é proporcional ao valor da linha.
    """
    soma = sum(v for v, _ in linhas)
    extra = frete + acrescimo - desconto
    custos = []
    for valor, qtd in linhas:
        rateio = extra * valor / soma if soma else Decimal("0")
        custos.append(((valor + rateio) / qtd).quantize(Decimal("0.0001"), ROUND_HALF_UP))
    return custos


# ---------- apoio às operações ----------

def _fornecedor_ativo(fornecedor_id):
    f = Fornecedor.objects.filter(id=fornecedor_id).first()
    if f is None:
        raise RegraViolada("Fornecedor não encontrado.")
    if not f.ativo:
        raise RegraViolada(f"O fornecedor '{f.nome}' está inativo.")
    return f


def _item_compravel(item_id, rotulo):
    item = Item.objects.filter(id=item_id).first()
    if item is None:
        raise RegraViolada(f"{rotulo}: item não encontrado.")
    if not item.ativo:
        raise RegraViolada(f"{rotulo}: o item '{item.nome}' está inativo.")
    if item.tipo == "produto":
        raise RegraViolada(f"{rotulo}: '{item.nome}' é produzido aqui, não comprado.")
    return item


def _na_base(item, quantidade, unidade, rotulo):
    q = decimal(quantidade, "quantidade")
    if q <= 0:
        raise RegraViolada(f"{rotulo}: a quantidade deve ser maior que zero.")
    un, f = fator(item, unidade or item.unidade_base)
    base = (q * f).quantize(MIL, ROUND_HALF_UP)
    if base <= 0:
        raise RegraViolada(f"{rotulo}: a quantidade deve ser maior que zero.")
    return q, un, f, base


def _compra(compra_id):
    c = Compra.objects.select_related("fornecedor").filter(id=compra_id).first()
    if c is None:
        raise RegraViolada("Compra não encontrada.")
    return c


def _atualizar_status(compra):
    if compra.status == "cancelada":
        return
    linhas = list(compra.linhas.all())
    if any(pendente_linha(l) > 0 for l in linhas):
        compra.status = "parcial" if any(recebido_linha(l) > 0 for l in linhas) else "aprovada"
    else:
        compra.status = "encerrada" if any(l.encerrado > 0 for l in linhas) else "recebida"
    compra.save(update_fields=["status"])


def _entrada(op, *, tipo, item, q_inf, un, f, base, custo, lote_codigo, validade, motivo):
    codigo = (lote_codigo or "").strip()
    if item.controla_validade and not validade:
        raise RegraViolada(f"Informe a validade de '{item.nome}'.")
    lote = Lote.objects.create(item=item, codigo=codigo, sem_lote=not codigo, validade=validade, custo_unitario=custo)
    Movimento.objects.create(tipo=tipo, item=item, lote=lote, quantidade=base, quantidade_informada=q_inf,
                             unidade_informada=un, fator=f, motivo=motivo, validade=validade, operacao=op)
    return lote


def _conciliaveis(lotes) -> list[dict]:
    """Consumos pendentes que podem ser vinculados aos lotes que acabaram de entrar (RF-EST-07)."""
    saida = []
    for lote in lotes:
        for p in ConsumoPendente.objects.filter(item=lote.item, lote__isnull=True).order_by("criado_em", "id"):
            saida.append({"pendente_id": p.id, "item": lote.item.nome, "quantidade": p.quantidade,
                          "lote_id": lote.id, "producao_id": p.producao_id})
    return saida


# ---------- operações ----------

def registrar_compra(*, fornecedor_id, data_compra, linhas, total, condicao, parcelas=None, data_pagamento=None,
                     forma_pagamento="", frete=0, desconto=0, acrescimo=0, documento="", justificativa="",
                     autor, canal="web", chave=None) -> dict:
    """Lança e aprova uma compra num passo só (RF-CMP-01/10) e abre a conta a pagar (RF-FIN-01).

    `linhas` = [{"item_id", "quantidade", "unidade", "valor"}] — quantidade na unidade de compra
    (convertida pelas conversões do item) e valor total da linha em reais.
    `condicao` = "a_vista" (nasce paga, em `data_pagamento` ou na data da compra) ou "a_prazo"
    (`parcelas` = [{"valor", "vencimento"}], soma = total).
    """
    parametros = {"fornecedor_id": fornecedor_id, "data_compra": data_compra, "linhas": linhas, "total": total,
                  "condicao": condicao, "parcelas": parcelas, "data_pagamento": data_pagamento,
                  "forma_pagamento": forma_pagamento, "frete": frete, "desconto": desconto, "acrescimo": acrescimo,
                  "documento": documento, "justificativa": justificativa}

    def func(op):
        fornecedor = _fornecedor_ativo(fornecedor_id)
        quando = data(data_compra, "data_compra")
        if quando is None:
            raise RegraViolada("Informe a data da compra.")
        fr, de, ac, tot = (reais(v or 0, n) for v, n in
                           ((frete, "frete"), (desconto, "desconto"), (acrescimo, "acrescimo"), (total, "total")))
        if min(fr, de, ac) < 0:
            raise RegraViolada("Frete, desconto e acréscimo não podem ser negativos.")
        if tot <= 0:
            raise RegraViolada("O total da compra deve ser maior que zero. Mercadoria sem custo entra como bonificação.")
        if not linhas:
            raise RegraViolada("Informe ao menos um item da compra.")
        lidas = []
        for i, l in enumerate(linhas, 1):
            rotulo = f"Linha {i}"
            item = _item_compravel(l.get("item_id"), rotulo)
            q, un, f, base = _na_base(item, l.get("quantidade"), l.get("unidade"), rotulo)
            valor = reais(l.get("valor"), f"valor da linha {i}")
            if valor < 0:
                raise RegraViolada(f"{rotulo}: o valor não pode ser negativo.")
            lidas.append((item, q, un, f, base, valor))
        calculado = sum(x[5] for x in lidas) + fr + ac - de
        texto_just = (justificativa or "").strip()
        if calculado != tot and not texto_just:
            raise RegraViolada(f"Os itens somam {dinheiro(calculado)} e o total do documento é {dinheiro(tot)} "
                               f"(diferença de {dinheiro(tot - calculado)}). Justifique para aprovar.")
        doc = (documento or "").strip()
        ativas = Compra.objects.exclude(status="cancelada").filter(fornecedor=fornecedor)
        if doc and (dup := ativas.filter(documento__iexact=doc).first()):
            raise RegraViolada(f"Este documento já foi lançado na compra {dup.id}.")
        alertas = [f"Possível duplicata: a compra {c.id} é do mesmo fornecedor, na mesma data e com o mesmo total."
                   for c in ativas.filter(data=quando, total=tot)]
        custos = custos_das_linhas([(x[5], x[4]) for x in lidas], frete=fr, desconto=de, acrescimo=ac)
        compra = Compra.objects.create(fornecedor=fornecedor, data=quando, documento=doc, frete=fr, desconto=de,
                                       acrescimo=ac, total=tot, justificativa=texto_just if calculado != tot else "",
                                       operacao=op)
        criadas = [LinhaCompra.objects.create(compra=compra, item=item, quantidade=q, unidade=un, fator=f,
                                              quantidade_base=base, valor=valor, custo_unitario=custo, ordem=i)
                   for i, ((item, q, un, f, base, valor), custo) in enumerate(zip(lidas, custos), 1)]
        conta = abrir_conta(op, compra=compra, total=tot, condicao=condicao, parcelas=parcelas,
                            data_pagamento=data_pagamento, forma_pagamento=forma_pagamento)
        return {"compra_id": compra.id, "conta_id": conta.id, "total": tot, "alertas": alertas,
                "linhas": [{"linha_id": l.id, "item": l.item.nome, "quantidade_base": l.quantidade_base,
                            "custo_unitario": l.custo_unitario} for l in criadas]}

    return executar("registrar_compra", func, autor=autor, canal=canal, chave=chave, parametros=parametros)


def receber_compra(*, compra_id, linhas, autor, canal="web", chave=None) -> dict:
    """Recebimento físico, total ou parcial (RF-REC-01 a 03). Atômico: todas as linhas ou nenhuma (RN-08).

    `linhas` = [{"linha_id", "quantidade", "unidade" (padrão: a da compra), "lote_codigo", "validade"}].
    Cada linha recebida vira um lote novo com o custo unitário da linha (RN-21). Recusa excesso (RF-REC-08).
    """

    def func(op):
        compra = _compra(compra_id)
        if compra.status not in ("aprovada", "parcial"):
            raise RegraViolada(f"Esta compra não espera recebimento ({compra.get_status_display().lower()}).")
        if not linhas:
            raise RegraViolada("Informe ao menos um item recebido.")
        recebimentos = []
        for i, r in enumerate(linhas, 1):
            linha = LinhaCompra.objects.select_related("item", "compra").filter(id=r.get("linha_id"),
                                                                                compra=compra).first()
            if linha is None:
                raise RegraViolada(f"Item {i}: não é uma linha desta compra.")
            item = linha.item
            q, un, f, base = _na_base(item, r.get("quantidade"), r.get("unidade") or linha.unidade, item.nome)
            pendente = pendente_linha(linha)
            if base > pendente:
                raise RegraViolada(f"'{item.nome}': só faltam receber {fmt_qtd(pendente, item.unidade_base)}. "
                                   "O excesso entra como bonificação (sem custo) ou numa nova compra.")
            lote = _entrada(op, tipo="entrada_compra", item=item, q_inf=q, un=un, f=f, base=base,
                            custo=linha.custo_unitario, lote_codigo=r.get("lote_codigo"),
                            validade=data(r.get("validade"), "validade"), motivo=f"Compra {compra.id}")
            recebimentos.append(Recebimento.objects.create(linha=linha, lote=lote, quantidade=base, operacao=op))
        _atualizar_status(compra)
        return {"compra_id": compra.id, "status": compra.status,
                "recebimentos": [{"recebimento_id": r.id, "linha_id": r.linha_id, "lote_id": r.lote_id,
                                  "quantidade_base": r.quantidade} for r in recebimentos],
                "conciliaveis": _conciliaveis([r.lote for r in recebimentos])}

    return executar("receber_compra", func, autor=autor, canal=canal, chave=chave,
                    parametros={"compra_id": compra_id, "linhas": linhas})


def encerrar_pendencia(*, compra_id, motivo, linha_ids=None, autor, canal="web", chave=None) -> dict:
    """O fornecedor não vai entregar o resto (RF-REC-04): encerra a pendência e avisa para ajustar a conta.

    Sem `linha_ids`, encerra todas as linhas pendentes. O valor devido não muda (RN-09).
    """

    def func(op):
        compra = _compra(compra_id)
        if compra.status not in ("aprovada", "parcial"):
            raise RegraViolada("Esta compra não tem pendência de recebimento.")
        texto = (motivo or "").strip()
        if not texto:
            raise RegraViolada("Informe o motivo.")
        qs = compra.linhas.select_related("item", "compra")
        if linha_ids:
            qs = qs.filter(id__in=linha_ids)
        encerradas = []
        for l in qs:
            p = pendente_linha(l)
            if p > 0:
                l.encerrado += p
                l.motivo_encerramento = texto
                l.save(update_fields=["encerrado", "motivo_encerramento"])
                encerradas.append((l, p))
        if not encerradas:
            raise RegraViolada("Não há pendência para encerrar.")
        _atualizar_status(compra)
        lista = ", ".join(f"{fmt_qtd(p, l.item.unidade_base)} de {l.item.nome}" for l, p in encerradas)
        aviso = avisar_ajuste(op, compra.conta, f"Compra {compra.id}: não entregue {lista} ({texto}). "
                                                "O valor da conta não mudou; ajuste no pagamento se houver abatimento.")
        return {"compra_id": compra.id, "status": compra.status, "aviso_id": aviso.id,
                "linhas": [{"linha_id": l.id, "encerrado": p} for l, p in encerradas]}

    return executar("encerrar_pendencia", func, autor=autor, canal=canal, chave=chave,
                    parametros={"compra_id": compra_id, "motivo": motivo, "linha_ids": linha_ids})


def estornar_recebimento(*, recebimento_id, motivo, autor, canal="web", chave=None) -> dict:
    """Desfaz um recebimento lançado errado (RF-REC-06), só se nada do lote foi usado. A pendência volta."""

    def func(op):
        r = Recebimento.objects.select_related("lote__item", "linha__compra").filter(id=recebimento_id).first()
        if r is None:
            raise RegraViolada("Recebimento não encontrado.")
        if not (motivo or "").strip():
            raise RegraViolada("Informe o motivo do estorno.")
        if r.estorno_operacao_id:
            raise RegraViolada("Este recebimento já foi estornado.")
        lote = r.lote
        if Movimento.objects.filter(lote=lote).exclude(tipo="entrada_compra").exists() or \
                ConsumoPendente.objects.filter(lote=lote).exists():
            raise RegraViolada("Parte deste lote já foi usada: corrija por ajuste ou devolução ao fornecedor.")
        Movimento.objects.create(tipo="estorno_recebimento", item=lote.item, lote=lote, quantidade=-r.quantidade,
                                 quantidade_informada=r.quantidade, unidade_informada=lote.item.unidade_base,
                                 fator=Decimal("1"), motivo=f"Estorno: {motivo.strip()}", operacao=op)
        r.estorno_operacao, r.motivo_estorno = op, motivo.strip()
        r.save(update_fields=["estorno_operacao", "motivo_estorno"])
        compra = r.linha.compra
        _atualizar_status(compra)  # a quantidade estornada volta a ficar pendente
        return {"recebimento_id": r.id, "compra_id": compra.id, "status": compra.status}

    return executar("estornar_recebimento", func, autor=autor, canal=canal, chave=chave,
                    parametros={"recebimento_id": recebimento_id, "motivo": motivo})


def devolver_ao_fornecedor(*, lote_id, quantidade, motivo, unidade=None, autor, canal="web", chave=None) -> dict:
    """Devolução ao fornecedor (RF-REC-07): baixa do lote com motivo e aviso de ajuste na conta (sem recalcular)."""

    def func(op):
        lote = Lote.objects.select_related("item").filter(id=lote_id).first()
        if lote is None:
            raise RegraViolada("Lote não encontrado.")
        texto = (motivo or "").strip()
        if not texto:
            raise RegraViolada("Informe o motivo da devolução.")
        r = Recebimento.objects.select_related("linha__compra__conta").filter(lote=lote).first()
        if r is None:
            raise RegraViolada("Este lote não veio de uma compra.")
        item = lote.item
        q, un, f, base = _na_base(item, quantidade, unidade, item.nome)
        disponivel = saldo_lote(lote)
        if base > disponivel:
            raise RegraViolada(f"O lote só tem {fmt_qtd(disponivel, item.unidade_base)} de '{item.nome}'.")
        Movimento.objects.create(tipo="devolucao_fornecedor", item=item, lote=lote, quantidade=-base,
                                 quantidade_informada=q, unidade_informada=un, fator=f,
                                 motivo=f"Devolução: {texto}", operacao=op)
        compra = r.linha.compra
        aviso = avisar_ajuste(op, compra.conta, f"Compra {compra.id}: devolvido {fmt_qtd(base, item.unidade_base)} "
                                                f"de {item.nome} ({texto}). O valor da conta não mudou; "
                                                "ajuste no pagamento se houver abatimento.")
        return {"lote_id": lote.id, "quantidade_base": base, "saldo_lote": saldo_lote(lote), "aviso_id": aviso.id}

    return executar("devolver_ao_fornecedor", func, autor=autor, canal=canal, chave=chave,
                    parametros={"lote_id": lote_id, "quantidade": quantidade, "unidade": unidade, "motivo": motivo})


def receber_bonificacao(*, item_id, quantidade, unidade, motivo, lote_codigo="", validade=None, compra_id=None,
                        autor, canal="web", chave=None) -> dict:
    """Mercadoria a mais, sem cobrança (RF-REC-08): lote próprio a custo zero."""

    def func(op):
        texto = (motivo or "").strip()
        if not texto:
            raise RegraViolada("Informe o motivo da bonificação.")
        item = _item_compravel(item_id, "Bonificação")
        q, un, f, base = _na_base(item, quantidade, unidade, item.nome)
        if compra_id is not None:
            texto = f"Compra {_compra(compra_id).id}: {texto}"
        lote = _entrada(op, tipo="bonificacao", item=item, q_inf=q, un=un, f=f, base=base, custo=Decimal("0"),
                        lote_codigo=lote_codigo, validade=data(validade, "validade"), motivo=f"Bonificação — {texto}")
        return {"lote_id": lote.id, "quantidade_base": base, "conciliaveis": _conciliaveis([lote])}

    return executar("receber_bonificacao", func, autor=autor, canal=canal, chave=chave,
                    parametros={"item_id": item_id, "quantidade": quantidade, "unidade": unidade, "motivo": motivo,
                                "lote_codigo": lote_codigo, "validade": validade, "compra_id": compra_id})


def cancelar_compra(*, compra_id, motivo, autor, canal="web", chave=None) -> dict:
    """Cancela compra lançada errado (RF-CMP-15): só sem recebimento e sem pagamento; cancela a conta junto."""

    def func(op):
        compra = _compra(compra_id)
        texto = (motivo or "").strip()
        if not texto:
            raise RegraViolada("Informe o motivo do cancelamento.")
        if compra.status == "cancelada":
            raise RegraViolada("Esta compra já foi cancelada.")
        if Recebimento.objects.filter(linha__compra=compra, estorno_operacao__isnull=True).exists():
            raise RegraViolada("Esta compra já tem recebimento: estorne o recebimento antes de cancelar.")
        if Pagamento.objects.filter(parcela__conta__compra=compra, estorno_operacao__isnull=True).exists():
            raise RegraViolada("Esta compra já tem pagamento anotado: estorne o pagamento antes de cancelar.")
        compra.status, compra.motivo_cancelamento = "cancelada", texto
        compra.save(update_fields=["status", "motivo_cancelamento"])
        conta = compra.conta
        conta.cancelada, conta.motivo_cancelamento = True, texto
        conta.save(update_fields=["cancelada", "motivo_cancelamento"])
        return {"compra_id": compra.id, "conta_id": conta.id}

    return executar("cancelar_compra", func, autor=autor, canal=canal, chave=chave,
                    parametros={"compra_id": compra_id, "motivo": motivo})
