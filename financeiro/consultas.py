"""Consultas de contas a pagar e a receber (só leitura), para telas e agente.

As consultas antigas continuam sendo de contas a pagar (`tipo="pagar"` por padrão); as de receber
passam `tipo="receber"` ou usam as funções `*_receber` / `devido_por_cliente` / `recebimentos`.

Devolvem dicts com Decimal e date; quem expõe em JSON serializa
(ex.: DjangoJSONEncoder). Nenhuma conta é feita fora daqui e de `servicos`.
"""

import calendar
from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from .models import AvisoAjuste, CategoriaDespesa, Conta, DespesaDoMes, DespesaMensal, Pagamento, Parcela
from .servicos import pago_parcela, situacao_parcela


def _parcela(p, hoje) -> dict:
    pago = pago_parcela(p)
    situacao = situacao_parcela(p)
    return {
        "parcela_id": p.id, "conta_id": p.conta_id, "tipo": p.conta.tipo, "compra_id": p.conta.compra_id,
        "fornecedor_id": p.conta.fornecedor_id, "fornecedor": str(p.conta.fornecedor or ""),
        "venda_id": p.conta.venda_id, "cliente_id": p.conta.cliente_id, "cliente": str(p.conta.cliente or ""),
        "descricao": p.conta.descricao, "origem": p.conta.origem, "categoria_id": p.conta.categoria_id,
        "categoria": str(p.conta.categoria or ""), "competencia": p.conta.competencia, "numero": p.numero, "de": p.conta.parcelas.count(),
        "valor": p.valor, "pago": pago, "saldo": Decimal("0") if situacao == "cancelada" else p.valor - pago,
        "vencimento": p.vencimento, "dias": (p.vencimento - hoje).days, "situacao": situacao,
        "vencida": situacao in ("aberta", "parcial") and p.vencimento < hoje,
    }


def parcelas_em_aberto(*, ate=None, fornecedor_id=None, cliente_id=None, tipo="pagar", origem=None,
                       hoje=None) -> list[dict]:
    """Parcelas abertas ou parcialmente pagas, por vencimento. `ate` limita o vencimento (inclusive);
    `origem` ("compra", "despesa", "venda") filtra de onde a conta nasceu."""
    hoje = hoje or timezone.localdate()
    qs = (Parcela.objects.select_related("conta__fornecedor", "conta__cliente", "conta__categoria")
          .filter(conta__cancelada=False, conta__tipo=tipo))
    if origem:
        qs = qs.filter(conta__origem=origem)
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
    """Saldo devedor por fornecedor, do maior para o menor (só contas de compra; despesas em `despesas_em_aberto`)."""
    hoje = hoje or timezone.localdate()
    soma = defaultdict(lambda: {"devido": Decimal("0"), "vencido": Decimal("0"), "parcelas": 0})
    nomes = {}
    for d in parcelas_em_aberto(tipo="pagar", origem="compra", hoje=hoje):
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


# ---------- despesas (Plano 8) ----------

ZERO = Decimal("0")


def categorias_despesa(*, ativas=True) -> list[dict]:
    qs = CategoriaDespesa.objects.all()
    if ativas:
        qs = qs.filter(ativa=True)
    return [{"categoria_id": c.id, "nome": c.nome, "indireta": c.indireta, "ativa": c.ativa} for c in qs]


def despesas_mensais(*, ativas=None) -> list[dict]:
    """Despesas mensais cadastradas (`ativas=None`: todas)."""
    qs = DespesaMensal.objects.select_related("categoria")
    if ativas is not None:
        qs = qs.filter(ativa=ativas)
    return [{"despesa_id": d.id, "nome": d.nome, "categoria_id": d.categoria_id, "categoria": d.categoria.nome,
             "indireta": d.categoria.indireta, "dia_vencimento": d.dia_vencimento,
             "valor_previsto": d.valor_previsto, "ativa": d.ativa} for d in qs]


def _situacao_conta(conta) -> tuple[str, Decimal | None, Decimal, Decimal | None]:
    """(situação, valor, pago, saldo) de uma conta de despesa de uma parcela; sem conta = "sem_valor"."""
    if conta is None:
        return "sem_valor", None, ZERO, None
    p = conta.parcelas.get()
    pago = pago_parcela(p)
    situacao = situacao_parcela(p)
    return situacao, conta.total, pago, ZERO if situacao == "cancelada" else p.valor - pago


def _despesa_do_mes(dm, hoje) -> dict:
    situacao, valor, pago, saldo = _situacao_conta(dm.conta)
    return {"despesa_do_mes_id": dm.id, "despesa_id": dm.despesa_id, "despesa": dm.despesa.nome,
            "categoria_id": dm.despesa.categoria_id, "categoria": dm.despesa.categoria.nome,
            "indireta": dm.despesa.categoria.indireta, "competencia": dm.competencia, "vencimento": dm.vencimento,
            "dias": (dm.vencimento - hoje).days, "conta_id": dm.conta_id,
            "parcela_id": dm.conta.parcelas.get().id if dm.conta else None,
            "valor_previsto": dm.despesa.valor_previsto, "valor": valor, "pago": pago, "saldo": saldo,
            "situacao": situacao,
            "vencida": situacao in ("sem_valor", "aberta", "parcial") and dm.vencimento < hoje}


def _avulsa(conta, hoje) -> dict:
    situacao, valor, pago, saldo = _situacao_conta(conta)
    p = conta.parcelas.get()
    return {"conta_id": conta.id, "parcela_id": p.id, "descricao": conta.descricao,
            "categoria_id": conta.categoria_id, "categoria": str(conta.categoria or ""),
            "indireta": bool(conta.categoria and conta.categoria.indireta), "competencia": conta.competencia,
            "vencimento": p.vencimento, "valor": valor, "pago": pago, "saldo": saldo, "situacao": situacao,
            "vencida": situacao in ("aberta", "parcial") and p.vencimento < hoje,
            "motivo_cancelamento": conta.motivo_cancelamento}


def _avulsas(de, ate, *, canceladas=False):
    qs = (Conta.objects.filter(origem="despesa", despesa_do_mes__isnull=True, competencia__gte=de,
                               competencia__lte=ate).select_related("categoria").order_by("competencia", "id"))
    return qs if canceladas else qs.filter(cancelada=False)


def _ultimo_dia(competencia):
    return competencia.replace(day=calendar.monthrange(competencia.year, competencia.month)[1])


def despesas_do_mes(*, competencia=None, hoje=None) -> dict:
    """As despesas de um mês (`competencia`: qualquer dia do mês; padrão o mês de hoje): as mensais geradas
    para o mês (com a situação: sem_valor, aberta, parcial, paga, cancelada) e as avulsas com competência no
    mês. `totais.falta_pagar` = saldo do que tem valor; `sem_valor` = quantas ainda não têm valor (não entram
    em nenhuma soma: o total do mês fica `completo=False`)."""
    hoje = hoje or timezone.localdate()
    comp = (competencia or hoje).replace(day=1)
    mensais = [_despesa_do_mes(dm, hoje) for dm in DespesaDoMes.objects.filter(competencia=comp)
               .select_related("despesa__categoria", "conta").order_by("vencimento", "despesa__nome")]
    avulsas = [_avulsa(c, hoje) for c in _avulsas(comp, _ultimo_dia(comp), canceladas=True)]
    validas = [d for d in mensais + avulsas if d["situacao"] not in ("cancelada", "sem_valor")]
    sem_valor = [d for d in mensais if d["situacao"] == "sem_valor"]
    return {"competencia": comp, "mensais": mensais, "avulsas": avulsas,
            "totais": {"valor": sum((d["valor"] for d in validas), ZERO),
                       "pago": sum((d["pago"] for d in validas), ZERO),
                       "falta_pagar": sum((d["saldo"] for d in validas), ZERO),
                       "sem_valor": len(sem_valor), "completo": not sem_valor,
                       "vencidas": sum(d["vencida"] for d in mensais + avulsas)}}


def despesas_sem_valor(*, ate=None, hoje=None) -> list[dict]:
    """Despesas mensais geradas que ainda não têm valor (nem pagamento), por vencimento. `ate` limita o
    vencimento (inclusive)."""
    hoje = hoje or timezone.localdate()
    qs = DespesaDoMes.objects.filter(conta__isnull=True).select_related("despesa__categoria")
    if ate:
        qs = qs.filter(vencimento__lte=ate)
    return [_despesa_do_mes(dm, hoje) for dm in qs.order_by("vencimento", "despesa__nome")]


def despesas_em_aberto(*, hoje=None) -> dict:
    """O que falta pagar de despesas: parcelas de despesa abertas (como `parcelas_em_aberto`) e as despesas
    do mês ainda sem valor. `vencidas` são as que já passaram do vencimento (das duas listas)."""
    hoje = hoje or timezone.localdate()
    abertas = parcelas_em_aberto(origem="despesa", hoje=hoje)
    sem_valor = despesas_sem_valor(hoje=hoje)
    return {"parcelas": abertas, "sem_valor": sem_valor,
            "vencidas": [d for d in abertas if d["vencida"]] + [d for d in sem_valor if d["vencida"]],
            "total": sum((d["saldo"] for d in abertas), ZERO), "completo": not sem_valor}


def despesas_vencidas(*, hoje=None) -> list[dict]:
    return despesas_em_aberto(hoje=hoje)["vencidas"]


def _meses(de, ate):
    m = de.replace(day=1)
    while m <= ate:
        yield m
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)


def despesas_periodo(*, de, ate, hoje=None) -> dict:
    """Despesas por competência no período `de`..`ate` (dias, inclusive), por categoria.

    Regra (Plano 8): a despesa mensal pertence ao mês (competência), não ao dia em que foi paga; em um período
    que pega só parte do mês, entra a fração dos dias (valor × dias do período no mês ÷ dias do mês) e
    `rateado=True`. A despesa avulsa entra inteira no dia da sua competência. Canceladas ficam fora. Mês sem
    valor informado não vira zero: vai para `faltando` e `completo=False`."""
    hoje = hoje or timezone.localdate()
    mensais, faltando, rateado = [], [], False
    for comp in _meses(de, ate):
        fim = _ultimo_dia(comp)
        dias_mes = fim.day
        dias = (min(fim, ate) - max(comp, de)).days + 1
        for dm in (DespesaDoMes.objects.filter(competencia=comp).select_related("despesa__categoria", "conta")
                   .order_by("despesa__nome")):
            d = _despesa_do_mes(dm, hoje)
            if d["situacao"] == "cancelada":
                continue
            if d["situacao"] == "sem_valor":
                faltando.append({"despesa_do_mes_id": dm.id, "despesa": dm.despesa.nome, "competencia": comp,
                                 "categoria": dm.despesa.categoria.nome, "motivo": "sem valor informado"})
                continue
            parcial = dias < dias_mes
            rateado = rateado or parcial
            valor = d["valor"] if not parcial else (d["valor"] * dias / dias_mes).quantize(Decimal("0.01"),
                                                                                         ROUND_HALF_UP)
            mensais.append({**d, "valor_mes": d["valor"], "dias": dias, "dias_mes": dias_mes, "valor": valor})
    avulsas = [_avulsa(c, hoje) for c in _avulsas(de, ate)]
    por = {}
    for d in mensais + avulsas:
        g = por.setdefault(d["categoria_id"], {"categoria_id": d["categoria_id"], "categoria": d["categoria"],
                                               "indireta": d["indireta"], "valor": ZERO, "lancamentos": 0})
        g["valor"] += d["valor"]
        g["lancamentos"] += 1
    for f in faltando:
        cat = next((c for c in por.values() if c["categoria"] == f["categoria"]), None)
        if cat is not None:
            cat["completo"] = False
    por_categoria = sorted(por.values(), key=lambda g: (-g["valor"], g["categoria"]))
    for g in por_categoria:
        g.setdefault("completo", True)
    total = sum((g["valor"] for g in por_categoria), ZERO)
    ressalvas = [f"Despesa mensal {f['despesa']} sem valor informado em {f['competencia']:%m/%Y}: "
                 f"não entrou na soma." for f in faltando]
    sem_pagamento = [d["despesa"] for d in mensais if d["situacao"] in ("aberta", "parcial")]
    if sem_pagamento:
        ressalvas.append("Ainda sem pagamento anotado (entraram pelo valor previsto ou informado): "
                         + ", ".join(sem_pagamento) + ".")
    if rateado:
        ressalvas.append("Período parcial: as despesas mensais entram rateadas pelos dias do período no mês.")
    if not DespesaMensal.objects.exists():
        ressalvas.append("Nenhuma despesa mensal cadastrada (luz, gás, internet, mão de obra...).")
    return {"de": de, "ate": ate, "total": total,
            "indiretas": sum((g["valor"] for g in por_categoria if g["indireta"]), ZERO),
            "completo": not faltando, "rateado": rateado, "por_categoria": por_categoria, "mensais": mensais,
            "avulsas": avulsas, "faltando": faltando, "ressalvas": ressalvas}
