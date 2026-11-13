"""Relatório do período (RF-REL-02, PRD §16) — só leitura, sem contabilidade formal.

Cada número tem a definição no plano (`docs/superpowers/plans/2026-11-13-plano-7-custos.md`, "Definições").
O que o sistema não registra (despesas, indiretos, tributos, ajuste de óleo) fica em `nao_inclui`; o que tem
dado duvidoso fica em `ressalvas`. Nada é contado como zero por falta de dado.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from compras.models import Compra
from estoque.models import Movimento
from financeiro.consultas import contas_vencidas, pagamentos, parcelas_em_aberto, recebimentos
from nucleo.operacoes import RegraViolada
from producao.models import Producao
from vendas.consultas import frituras, vendas
from vendas.models import Encomenda, Venda

from .consultas import _agrupar, _linhas_venda, _somar, previsto_realizado

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _inicio(d):
    return timezone.make_aware(datetime.combine(d, time.min))


def _no_periodo(qs, campo, de, ate):
    """Filtra um campo datetime pelos dias `de`..`ate` (inclusive, no fuso da cozinha)."""
    return qs.filter(**{f"{campo}__gte": _inicio(de), f"{campo}__lt": _inicio(ate + timedelta(days=1))})


def _soma(linhas, campo):
    return sum((l[campo] for l in linhas), ZERO)


def _vendas(de, ate, linhas) -> dict:
    v = vendas(de=de, ate=ate, incluir_canceladas=True)
    t = v["totais"]
    canceladas = [x for x in v["vendas"] if x["situacao"] == "cancelada"]
    return {
        "totais": _somar(linhas),
        "custo_gravado": t["custo"],  # inclui as linhas de custo duvidoso (o resultado usa este)
        "recebido_na_hora": t["recebido_na_hora"], "a_prazo": t["a_prazo"],
        "por_forma_pagamento": t["por_forma_pagamento"],
        "por_produto": _agrupar(linhas, "produto"), "por_cliente": _agrupar(linhas, "cliente"),
        "por_tabela": _agrupar(linhas, "tabela"), "por_dia": _agrupar(linhas, "dia"),
        "canceladas": {"vendas": len(canceladas), "total": _soma(canceladas, "total"),
                       "venda_ids": [x["venda_id"] for x in canceladas]},
    }


def _encomendas(de, ate) -> dict:
    criadas = list(_no_periodo(Encomenda.objects.all(), "criado_em", de, ate))
    entregues = Venda.objects.filter(encomenda__isnull=False, situacao="concluida", data__gte=de, data__lte=ate)
    canceladas = list(_no_periodo(Encomenda.objects.filter(situacao="cancelada"), "fim_operacao__criado_em", de, ate))
    return {"criadas": len(criadas), "valor_criadas": sum((e.total for e in criadas), ZERO),
            "sinais": sum((e.sinal for e in criadas), ZERO),
            "entregues": entregues.count(), "valor_entregues": sum((x.total for x in entregues), ZERO),
            "canceladas": len(canceladas), "valor_canceladas": sum((e.total for e in canceladas), ZERO)}


def _producao(de, ate) -> dict:
    pr = previsto_realizado(de=de, ate=ate)
    por_motivo = defaultdict(int)
    for d in pr["producoes"]:
        if d["perdas"]:
            por_motivo[d["perda_motivo"] or "sem motivo"] += d["perdas"]
    fr = frituras(de=de, ate=ate)
    por_produto = defaultdict(lambda: {"frituras": 0, "fritas": 0, "boas": 0, "perdas": 0, "custo_total": ZERO})
    for f in fr:
        g = por_produto[f["produto"]]
        g["frituras"] += 1
        g["fritas"] += f["fritas"]
        g["boas"] += f["boas"]
        g["perdas"] += f["perdas"]
        g["custo_total"] += f["custo_total"]
    return {
        "producoes": len(pr["producoes"]), "unidades": sum(d["unidades"] for d in pr["producoes"]),
        "boas": sum(d["boas"] or 0 for d in pr["producoes"]), "perdas": sum(d["perdas"] or 0 for d in pr["producoes"]),
        "custo_real": sum((d["custo_real"] for d in pr["producoes"]), ZERO),
        "custo_pendente": pr["fora"]["custo_pendente"], "perdas_por_motivo": dict(por_motivo),
        "por_produto": pr["por_produto"],
        "frituras": {"frituras": len(fr), "fritas": sum(f["fritas"] for f in fr), "boas": sum(f["boas"] for f in fr),
                     "perdas": sum(f["perdas"] for f in fr), "custo_total": _soma(fr, "custo_total"),
                     "por_produto": [{"produto": k, **v} for k, v in sorted(por_produto.items())]},
        "canceladas": _no_periodo(Producao.objects.filter(status="cancelada"), "encerrada_em", de, ate).count(),
    }


def _perdas(de, ate, producao) -> dict:
    """Perdas e descartes com valor: movimentos "perda" (custo do lote) e vendas canceladas com destino
    perda (custo gravado na venda). As perdas dentro de uma produção ou fritura só têm unidades: o custo
    delas já está no custo por unidade do lote que saiu."""
    movs = (_no_periodo(Movimento.objects.filter(tipo="perda"), "criado_em", de, ate)
            .select_related("item", "lote"))
    por_motivo = defaultdict(lambda: {"movimentos": 0, "valor": ZERO, "itens": defaultdict(lambda: ZERO)})
    lista = []
    for m in movs:
        q = -m.quantidade
        valor = (q * m.lote.custo_unitario).quantize(CENT, ROUND_HALF_UP)
        g = por_motivo[m.motivo]
        g["movimentos"] += 1
        g["valor"] += valor
        g["itens"][(m.item.nome, m.item.unidade_base)] += q
        lista.append({"movimento_id": m.id, "data": timezone.localtime(m.criado_em).date(), "item_id": m.item_id,
                      "item": m.item.nome, "unidade_base": m.item.unidade_base, "lote_id": m.lote_id,
                      "estado": m.estado, "quantidade": q, "valor": valor, "motivo": m.motivo})
    canc = list(_no_periodo(Venda.objects.filter(situacao="cancelada", destino="perda"),
                            "cancelamento_operacao__criado_em", de, ate))
    valor_mov = _soma(lista, "valor")
    valor_canc = sum((v.custo for v in canc), ZERO)
    return {
        "movimentos": lista,
        "por_motivo": [{"motivo": k, "movimentos": g["movimentos"], "valor": g["valor"],
                        "itens": [{"item": i, "unidade_base": u, "quantidade": q} for (i, u), q in g["itens"].items()]}
                       for k, g in sorted(por_motivo.items(), key=lambda x: -x[1]["valor"])],
        "valor_movimentos": valor_mov,
        "vendas_canceladas": {"vendas": len(canc), "valor": valor_canc, "venda_ids": [v.id for v in canc]},
        "valor_total": valor_mov + valor_canc,
        "unidades_producao": producao["perdas"], "unidades_fritura": producao["frituras"]["perdas"],
    }


def _compras(de, ate) -> dict:
    qs = Compra.objects.exclude(status="cancelada").filter(data__gte=de, data__lte=ate).select_related("fornecedor")
    por = defaultdict(lambda: {"compras": 0, "total": ZERO})
    for c in qs:
        por[c.fornecedor.nome]["compras"] += 1
        por[c.fornecedor.nome]["total"] += c.total
    return {"compras": sum(g["compras"] for g in por.values()), "total": sum((g["total"] for g in por.values()), ZERO),
            "por_fornecedor": [{"fornecedor": k, **g} for k, g in sorted(por.items(), key=lambda x: -x[1]["total"])],
            "observacao": "Compra de item estocável não é despesa (RN-33): o custo aparece quando o item é usado "
                          "e vendido."}


def _dinheiro(de, ate) -> dict:
    """O que foi anotado como entrando e saindo (o sistema não movimenta dinheiro)."""
    a_vista = sum((v.recebido_na_hora for v in Venda.objects.filter(data__gte=de, data__lte=ate)), ZERO)
    sinais = sum((e.sinal for e in _no_periodo(Encomenda.objects.all(), "criado_em", de, ate)), ZERO)
    receb = sum((r["valor_pago"] for r in recebimentos(de=de, ate=ate)), ZERO)
    pagos = sum((p["valor_pago"] for p in pagamentos(de=de, ate=ate)), ZERO)
    dev_vendas = sum((v.valor_devolvido for v in _no_periodo(Venda.objects.filter(situacao="cancelada"),
                                                             "cancelamento_operacao__criado_em", de, ate)), ZERO)
    dev_sinais = sum((e.sinal_devolvido for e in _no_periodo(Encomenda.objects.filter(situacao="cancelada"),
                                                             "fim_operacao__criado_em", de, ate)), ZERO)
    entrou = a_vista + sinais + receb
    saiu = pagos + dev_vendas + dev_sinais
    return {"entrou": entrou, "vendas_a_vista": a_vista, "sinais": sinais, "recebimentos": receb,
            "saiu": saiu, "pagamentos": pagos, "devolvido_vendas": dev_vendas, "devolvido_sinais": dev_sinais,
            "saldo": entrou - saiu}


def _posicao(hoje) -> dict:
    pagar, receber = parcelas_em_aberto(hoje=hoje), parcelas_em_aberto(tipo="receber", hoje=hoje)
    return {"hoje": hoje,
            "a_pagar": _soma(pagar, "saldo"), "a_pagar_vencido": _soma(contas_vencidas(hoje=hoje), "saldo"),
            "a_receber": _soma(receber, "saldo"),
            "a_receber_vencido": _soma(contas_vencidas(tipo="receber", hoje=hoje), "saldo")}


def relatorio_periodo(*, de, ate, hoje=None) -> dict:
    """Vendas, encomendas, produção, perdas, compras, dinheiro anotado, posição das contas e resultado simples
    do período `de`..`ate` (dias, inclusive). A posição das contas é a de hoje (o que está em aberto agora).

    `resultado.resultado` = receita das vendas concluídas − custo gravado nessas vendas − perdas com valor.
    Não é lucro: não inclui despesas, indiretos, tributos nem ajuste de óleo (`resultado.nao_inclui`)."""
    if ate < de:
        raise RegraViolada("O fim do período vem antes do início.")
    hoje = hoje or timezone.localdate()
    linhas = _linhas_venda(de, ate)
    bloco_vendas = _vendas(de, ate, linhas)
    producao = _producao(de, ate)
    perdas = _perdas(de, ate, producao)
    receita = bloco_vendas["totais"]["receita"]
    custo = bloco_vendas["custo_gravado"]
    ressalvas = []
    fora = bloco_vendas["totais"]["fora"]
    if fora["linhas"]:
        ressalvas.append(f"{fora['linhas']} linha(s) de venda com custo duvidoso "
                         f"({', '.join(sorted(fora['motivos']))}): o custo gravado pode estar baixo.")
    if producao["custo_pendente"]:
        ressalvas.append(f"{len(producao['custo_pendente'])} produção(ões) com custo pendente de conciliação.")
    return {
        "de": de, "ate": ate, "dias": (ate - de).days + 1,
        "vendas": bloco_vendas, "encomendas": _encomendas(de, ate), "producao": producao, "perdas": perdas,
        "compras": _compras(de, ate), "dinheiro": _dinheiro(de, ate), "posicao": _posicao(hoje),
        "resultado": {
            "receita": receita, "custo_vendido": custo, "perdas": perdas["valor_total"],
            "resultado": receita - custo - perdas["valor_total"],
            "resultado_pct": ((receita - custo - perdas["valor_total"]) * 100 / receita).quantize(
                Decimal("0.1"), ROUND_HALF_UP) if receita else None,
            "rotulo": "estimado",
            "nao_inclui": ["despesas (aluguel, gás, energia, salários): o sistema ainda não registra despesas",
                           "indiretos de fabricação rateados", "tributos sobre a venda", "ajuste de óleo"],
        },
        "ressalvas": ressalvas,
    }
