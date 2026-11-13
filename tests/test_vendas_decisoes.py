"""Plano 6 na caixa de decisões e no resumo do dia: encomenda sem estoque, recebíveis vencidos, sobras fritas."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.utils import timezone

from cadastros.models import Item
from cadastros.servicos import salvar_cliente
from decisoes.consultas import decisoes, resumo_do_dia
from decisoes.geradores import rodar_rotina
from decisoes.servicos import aprovar_decisao
from estoque.models import CriterioValidade, Lote, Movimento
from estoque.servicos import disponivel
from producao.fritura import registrar_fritura
from vendas.servicos import criar_encomenda, registrar_venda, salvar_apresentacao

pytestmark = pytest.mark.django_db

HOJE = timezone.localdate()


def dia(n):
    return HOJE + dt.timedelta(days=n)


@pytest.fixture
def coxinha():
    return Item.objects.create(nome="Coxinha 150 g", tipo="produto", unidade_base="un", oleo_ref_un=D("0.05"))


def lote(produto, n, *, validade, forma="cru", estado="congelado"):
    l = Lote.objects.create(item=produto, forma=forma, validade=validade, custo_unitario=D("0.60"))
    Movimento.objects.create(tipo="entrada_producao", item=produto, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado=estado, validade=validade)
    return l


def caixa(origem):
    return decisoes(origem=origem)


def test_encomenda_sem_estoque_avisa_e_depois_propoe_completar_a_reserva(coxinha):
    a = salvar_apresentacao(produto_id=coxinha.id, nome="unidade", forma="cru", estado="congelado", unidades=1,
                            preco_varejo=D("2"), autor="dono")["apresentacao_id"]
    j = salvar_cliente(nome="João", autor="dono")["cliente_id"]
    e = criar_encomenda(cliente_id=j, entrega_data=dia(2), itens=[{"apresentacao_id": a, "quantidade": 30}],
                        autor="dono")["encomenda_id"]
    criar_encomenda(cliente_id=j, entrega_data=dia(10), itens=[{"apresentacao_id": a, "quantidade": 5}],
                    autor="dono")  # longe demais: fica fora da caixa
    rodar_rotina()
    [aviso] = caixa("encomenda_sem_estoque")
    assert aviso["tipo"] == "aviso" and "falta reservar 30 un de Coxinha 150 g cru congelado" in aviso["texto"]
    lote(coxinha, 50, validade=dia(20))
    rodar_rotina()
    [d] = caixa("encomenda_sem_estoque")
    assert d["tipo"] == "decisao" and d["operacao"] == "completar_reserva" and "Há 30 un" in d["texto"]
    assert d["parametros"] == {"encomenda_id": e}
    aprovar_decisao(decisao_id=d["decisao_id"], autor="dono")
    assert disponivel(coxinha) == 20
    rodar_rotina()
    assert caixa("encomenda_sem_estoque") == []


def test_recebivel_vencido_e_sobra_frita_viram_aviso_e_entram_no_resumo(coxinha):
    CriterioValidade.objects.create(produto=coxinha, forma="frito", estado="fresco", dias=2)
    cru = lote(coxinha, 40, validade=dia(30))
    a = salvar_apresentacao(produto_id=coxinha.id, nome="unidade", forma="cru", estado="congelado", unidades=1,
                            preco_varejo=D("5"), autor="dono")["apresentacao_id"]
    j = salvar_cliente(nome="Bar do Zé", autor="dono")["cliente_id"]
    registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 10}], condicao="a_prazo", cliente_id=j,
                    parcelas=[{"valor": "50", "vencimento": dia(-3)}], autor="dono")
    registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 2}], forma_pagamento="pix", autor="dono")
    criar_encomenda(cliente_id=j, entrega_data=HOJE, itens=[{"apresentacao_id": a, "quantidade": 4}], autor="dono")
    registrar_fritura(lote_id=cru.id, estado="congelado", quantidade=6, boas=6, autor="dono")
    rodar_rotina()
    [r] = caixa("receber_vencidas")
    assert r["texto"].startswith("Bar do Zé está devendo R$ 50,00")
    assert caixa("sobras_fritas") == []  # frito hoje: só amanhã vira aviso
    rodar_rotina(hoje=dia(1))
    [s] = caixa("sobras_fritas")
    assert "Sobraram 6 un de Coxinha 150 g fritos" in s["texto"]
    t = resumo_do_dia()["totais"]
    assert (t["vendas_hoje"], t["valor_vendas_hoje"]) == (2, D("60"))
    assert (t["receber_vencidas"], t["valor_receber_vencidas"]) == (1, D("50"))
    assert (t["encomendas_hoje"], t["encomendas_sem_estoque"], t["sobras_fritas"]) == (1, 0, 1)
    assert t["contas_vencidas"] == 0  # contas a pagar não misturam recebíveis
    r = resumo_do_dia()
    assert r["encomendas"]["hoje"][0]["situacao"] == "pronta" and r["receber"]["total_a_receber"] == D("50")
