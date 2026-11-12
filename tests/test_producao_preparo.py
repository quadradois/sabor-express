from decimal import Decimal as D

import pytest
from estoque.servicos import entrada_manual, saldo
from nucleo.operacoes import RegraViolada
from producao.models import Cronometro, Producao
from producao.servicos import (cancelar_producao, iniciar_cronometro, ir_para_etapa, iniciar_producao,
                               parar_cronometro, registrar_peso, usar_previsto_restantes)

pytestmark = pytest.mark.django_db


@pytest.fixture
def producao(bolinha):
    f = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    entrada_manual(item_id=f.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra", autor="dono")
    return Producao.objects.get(id=iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"])


def test_usei_o_previsto(producao):
    l = producao.linhas.get()
    registrar_peso(linha_id=l.id, usado=None, autor="dono")
    l.refresh_from_db()
    assert l.usado == l.previsto


def test_peso_negativo_recusado_e_zero_aceito(producao):
    l = producao.linhas.get()
    with pytest.raises(RegraViolada, match="O peso não pode ser negativo."):
        registrar_peso(linha_id=l.id, usado=D("-1"), autor="dono")
    registrar_peso(linha_id=l.id, usado=D("0"), autor="dono")
    l.refresh_from_db()
    assert l.usado == 0


def test_nao_sai_do_mise_en_place_sem_pesar(producao):
    with pytest.raises(RegraViolada, match="Pese ou marque 'usei o previsto' em: Farinha de trigo."):
        ir_para_etapa(producao_id=producao.id, indice=1, autor="dono")


def test_avanca_e_volta(producao):
    assert usar_previsto_restantes(producao_id=producao.id, autor="dono") == {"linhas": 1}
    for i in (1, 2, 1):
        ir_para_etapa(producao_id=producao.id, indice=i, autor="dono")
        producao.refresh_from_db()
        assert producao.etapa_atual == i
    with pytest.raises(RegraViolada, match="Etapa inexistente."):
        ir_para_etapa(producao_id=producao.id, indice=99, autor="dono")


def test_cronometros_simultaneos_sobrevivem_a_troca_de_etapa(producao):
    usar_previsto_restantes(producao_id=producao.id, autor="dono")
    for n in ("massa", "forno"):
        iniciar_cronometro(producao_id=producao.id, nome=n, segundos=600, autor="dono")
    antes = list(producao.cronometros.values_list("fim", flat=True))
    ir_para_etapa(producao_id=producao.id, indice=1, autor="dono")
    assert list(producao.cronometros.values_list("fim", "parado_em")) == [(f, None) for f in antes]
    c = producao.cronometros.first()
    parar_cronometro(cronometro_id=c.id, autor="dono")
    parar_cronometro(cronometro_id=c.id, autor="dono")
    assert Cronometro.objects.get(id=c.id).parado_em is not None


def test_cronometro_exige_segundos_positivos(producao):
    with pytest.raises(RegraViolada):
        iniciar_cronometro(producao_id=producao.id, nome="x", segundos=0, autor="dono")


def test_cancelar_nao_mexe_no_estoque(producao):
    f = producao.linhas.get().item
    antes = saldo(f)
    with pytest.raises(RegraViolada, match="Informe o motivo do cancelamento."):
        cancelar_producao(producao_id=producao.id, motivo=" ", autor="dono")
    cancelar_producao(producao_id=producao.id, motivo="errei", autor="dono")
    producao.refresh_from_db()
    assert (producao.status, producao.motivo_cancelamento) == ("cancelada", "errei") and producao.encerrada_em
    assert saldo(f) == antes
    with pytest.raises(RegraViolada, match="Esta produção já foi encerrada."):
        registrar_peso(linha_id=producao.linhas.get().id, usado=None, autor="dono")
