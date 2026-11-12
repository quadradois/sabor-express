import datetime as dt
from decimal import Decimal as D

import pytest

from cadastros.models import Item
from cadastros.servicos import salvar_fornecedor
from compras.servicos import registrar_compra
from financeiro.consultas import (contas_a_vencer, contas_vencidas, detalhe_conta, devido_por_fornecedor,
                                  pagamentos, parcelas_em_aberto)
from financeiro.models import Conta, Pagamento, Parcela
from financeiro.servicos import dividir_parcelas, estornar_pagamento, registrar_pagamento, situacao_parcela
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db

HOJE = dt.date(2026, 11, 12)


@pytest.fixture
def conta_300():
    """Compra de R$ 300 em 3 parcelas de R$ 100 (CA-36): vencida há 2 dias, vence em 5 e em 35."""
    f = salvar_fornecedor(nome="Atacadão", autor="dono")["fornecedor_id"]
    farinha = Item.objects.create(nome="Farinha", tipo="ingrediente", unidade_base="g", controla_validade=False)
    venc = [HOJE - dt.timedelta(days=2), HOJE + dt.timedelta(days=5), HOJE + dt.timedelta(days=35)]
    r = registrar_compra(fornecedor_id=f, data_compra=HOJE - dt.timedelta(days=10), total=D("300"),
                         linhas=[{"item_id": farinha.id, "quantidade": D("50"), "unidade": "kg", "valor": D("300")}],
                         condicao="a_prazo", parcelas=[{"valor": D("100"), "vencimento": v} for v in venc],
                         autor="dono")
    return Conta.objects.get(id=r["conta_id"])


def p(conta, n):
    return Parcela.objects.get(conta=conta, numero=n)


def test_dividir_parcelas_soma_o_total():
    s = dividir_parcelas(D("100"), 3, HOJE)
    assert [x["valor"] for x in s] == [D("33.33"), D("33.33"), D("33.34")]
    assert [x["vencimento"] for x in s] == [HOJE, HOJE + dt.timedelta(days=30), HOJE + dt.timedelta(days=60)]


def test_pagamento_parcial_e_vencida_derivada(conta_300):
    r = registrar_pagamento(parcela_id=p(conta_300, 1).id, valor=D("60"), autor="dono")
    assert (r["situacao"], D(r["saldo"])) == ("parcial", D("40"))
    [v] = contas_vencidas(hoje=HOJE)
    assert (v["numero"], v["saldo"], v["situacao"], v["de"]) == (1, D("40"), "parcial", 3)
    assert [x["numero"] for x in contas_a_vencer(dias=7, hoje=HOJE)] == [2]
    [f] = devido_por_fornecedor(hoje=HOJE)
    assert (f["fornecedor"], f["devido"], f["vencido"], f["parcelas"]) == ("Atacadão", D("240"), D("40"), 3)
    registrar_pagamento(parcela_id=p(conta_300, 1).id, autor="dono")  # sem valor: quita o saldo
    assert situacao_parcela(p(conta_300, 1)) == "paga" and contas_vencidas(hoje=HOJE) == []


def test_nao_paga_mais_que_o_saldo(conta_300):
    with pytest.raises(RegraViolada, match=r"passa do saldo da parcela \(R\$ 100,00\)"):
        registrar_pagamento(parcela_id=p(conta_300, 1).id, valor=D("100.01"), autor="dono")
    registrar_pagamento(parcela_id=p(conta_300, 1).id, valor=D("100"), autor="dono")
    with pytest.raises(RegraViolada, match="já está paga"):
        registrar_pagamento(parcela_id=p(conta_300, 1).id, valor=D("1"), autor="dono")


def test_diferenca_juros_e_desconto(conta_300):
    with pytest.raises(RegraViolada, match="juros, multa ou desconto"):
        registrar_pagamento(parcela_id=p(conta_300, 1).id, diferenca=D("2"), autor="dono")
    with pytest.raises(RegraViolada, match="motivo da diferença"):
        registrar_pagamento(parcela_id=p(conta_300, 1).id, diferenca=D("2"), diferenca_tipo="multa", autor="dono")
    r = registrar_pagamento(parcela_id=p(conta_300, 1).id, diferenca=D("2"), diferenca_tipo="multa",
                            diferenca_motivo="paguei atrasado", autor="dono")
    assert (D(r["valor"]), D(r["valor_pago"]), r["situacao"]) == (D("100"), D("102"), "paga")
    r = registrar_pagamento(parcela_id=p(conta_300, 2).id, diferenca=D("6"), diferenca_tipo="desconto",
                            diferenca_motivo="1 kg não entregue", autor="dono")
    assert (D(r["valor_pago"]), r["situacao"]) == (D("94"), "paga")


def test_estorno_volta_a_parcela_ao_estado_anterior(conta_300):
    # CA-38: o original continua visível, a parcela volta ao estado anterior
    r = registrar_pagamento(parcela_id=p(conta_300, 1).id, valor=D("100"), autor="dono")
    with pytest.raises(RegraViolada, match="motivo do estorno"):
        estornar_pagamento(pagamento_id=r["pagamento_id"], motivo="", autor="dono")
    e = estornar_pagamento(pagamento_id=r["pagamento_id"], motivo="era de outra conta", autor="dono")
    assert (e["situacao"], D(e["saldo"])) == ("aberta", D("100"))
    assert Pagamento.objects.count() == 1 and pagamentos() == []
    [pg] = pagamentos(incluir_estornados=True)
    assert pg["estornado"] and pg["motivo_estorno"] == "era de outra conta"
    with pytest.raises(RegraViolada, match="já foi estornado"):
        estornar_pagamento(pagamento_id=r["pagamento_id"], motivo="de novo", autor="dono")
    registrar_pagamento(parcela_id=p(conta_300, 1).id, valor=D("100"), autor="dono")  # lança o correto
    assert situacao_parcela(p(conta_300, 1)) == "paga"
    assert len(detalhe_conta(conta_300)["parcelas"][0]["pagamentos"]) == 2


def test_pagamento_idempotente(conta_300):
    a = registrar_pagamento(parcela_id=p(conta_300, 1).id, valor=D("50"), autor="dono", chave="pg-1")
    b = registrar_pagamento(parcela_id=p(conta_300, 1).id, valor=D("50"), autor="dono", chave="pg-1")
    assert a == b and Pagamento.objects.count() == 1
    with pytest.raises(RegraViolada, match="chave já foi usada"):
        registrar_pagamento(parcela_id=p(conta_300, 1).id, valor=D("40"), autor="dono", chave="pg-1")


def test_valores_como_texto_vindos_do_agente(conta_300):
    r = registrar_pagamento(parcela_id=p(conta_300, 1).id, valor="25.50", data_pagamento="2026-11-10", autor="dono")
    assert r["saldo"] == "74.50" and Pagamento.objects.get().data == dt.date(2026, 11, 10)
    with pytest.raises(RegraViolada, match="Valor inválido"):
        registrar_pagamento(parcela_id=p(conta_300, 1).id, valor="dez", autor="dono")
