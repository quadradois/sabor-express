from decimal import Decimal as D

import pytest
from django.utils import timezone

from cadastros.models import Item
from cadastros.servicos import salvar_fornecedor
from compras.servicos import receber_compra, registrar_compra
from estoque.models import ConsumoPendente, Lote, Movimento
from estoque.servicos import consumos_pendentes, entrada_manual, saldo, saldo_lote
from nucleo.operacoes import RegraViolada
from producao.models import Producao
from producao.servicos import (conciliar_consumo, concluir_producao, iniciar_producao, origem,
                               usar_previsto_restantes)

pytestmark = pytest.mark.django_db


@pytest.fixture
def farinha(bolinha):
    return bolinha.ficha.proporcoes.get().preparacao.itens.get().item


def produzir_sem_farinha(bolinha, **concluir):
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono",
                         pendente_justificativa="nota do atacadão ainda não lançada")["producao_id"]
    usar_previsto_restantes(producao_id=p, autor="dono")
    return p, concluir_producao(producao_id=p, quantidade_boa=9, perdas=1, perda_motivo="rasgou", estado="resfriado",
                                validade_manual=timezone.localdate(), justificativa="teste", autor="dono", **concluir)


def comprar_farinha(farinha, kg="2", valor="10"):
    f = salvar_fornecedor(nome="Atacadão", autor="dono")["fornecedor_id"]
    r = registrar_compra(fornecedor_id=f, data_compra=timezone.localdate(), total=D(valor), condicao="a_vista",
                         linhas=[{"item_id": farinha.id, "quantidade": D(kg), "unidade": "kg", "valor": D(valor)}],
                         autor="dono")
    return receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": r["linhas"][0]["linha_id"],
                                                             "quantidade": D(kg)}], autor="dono")


def test_sem_justificativa_continua_recusando(bolinha):
    with pytest.raises(RegraViolada, match="Falta 1 kg de 'Farinha de trigo'"):
        iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")


def test_conclui_com_consumo_pendente_sem_estoque_negativo(bolinha, farinha):
    entrada_manual(item_id=farinha.id, quantidade=D("400"), unidade="g", custo_total=D("2"), motivo="sobra",
                   autor="dono")
    p, r = produzir_sem_farinha(bolinha)
    assert r["custo_pendente"] and D(r["custo_total"]) == D("2.00")  # só o que havia em estoque
    [pend] = consumos_pendentes()
    assert (pend["quantidade"], pend["producao_id"]) == (D("600"), p)
    assert saldo(farinha) == 0  # nunca negativo (DEC-F2-005)


def test_recebimento_propoe_e_conciliacao_fecha_o_custo(bolinha, farinha):
    p, r = produzir_sem_farinha(bolinha)
    assert D(r["custo_total"]) == 0
    rec = comprar_farinha(farinha)
    [c] = rec["conciliaveis"]  # RF-EST-07: o recebimento propõe o vínculo
    lote = Lote.objects.get(id=c["lote_id"])
    assert c["item"] == "Farinha de trigo" and D(c["quantidade"]) == D("1000")
    feito = conciliar_consumo(pendente_id=c["pendente_id"], lote_id=lote.id, autor="dono")
    assert D(feito["custo"]) == D("5.00") and feito["custo_pendente"] is False
    prod = Producao.objects.get(id=p)
    assert (prod.custo_total, prod.custo_unitario, prod.custo_pendente) == (D("5.00"), D("0.5556"), False)
    assert prod.lote.custo_unitario == D("0.5556")
    assert saldo_lote(lote) == D("1000") and consumos_pendentes() == []
    assert (lote, D("1000")) in origem(prod.lote)  # rastreio inclui o lote conciliado
    with pytest.raises(RegraViolada, match="já foi conciliado"):  # uma única vez (DEC-F2-033)
        conciliar_consumo(pendente_id=c["pendente_id"], lote_id=lote.id, autor="dono")


def test_conciliacao_recusa_lote_errado_ou_sem_saldo(bolinha, farinha):
    produzir_sem_farinha(bolinha)
    pend = ConsumoPendente.objects.get()
    oleo = Item.objects.create(nome="Óleo", tipo="insumo", unidade_base="mL", controla_validade=False)
    outro = entrada_manual(item_id=oleo.id, quantidade=D("1"), unidade="L", custo_total=D("9"), motivo="x",
                           autor="dono")["lote_id"]
    with pytest.raises(RegraViolada, match="não é de 'Farinha de trigo'"):
        conciliar_consumo(pendente_id=pend.id, lote_id=outro, autor="dono")
    pouco = entrada_manual(item_id=farinha.id, quantidade=D("500"), unidade="g", custo_total=D("3"), motivo="x",
                           autor="dono")["lote_id"]
    with pytest.raises(RegraViolada, match="só tem 500 g"):
        conciliar_consumo(pendente_id=pend.id, lote_id=pouco, autor="dono")
    assert not Movimento.objects.filter(tipo="consumo_producao").exists()
    [p] = consumos_pendentes()
    assert p["lotes_possiveis"] == []  # nenhum lote cobre os 1000 g
