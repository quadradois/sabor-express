from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.utils import timezone

from estoque.servicos import entrada_manual
from producao.servicos import iniciar_producao

pytestmark = pytest.mark.django_db
TOKEN = "segredo-de-teste"


@pytest.fixture(autouse=True)
def token(settings):
    settings.AGENTE_TOKEN = TOKEN


def get(client, url, **params):
    return client.get(url, params, HTTP_AUTHORIZATION=f"Bearer {TOKEN}")


@pytest.fixture
def farinha(bolinha):
    return bolinha.ficha.proporcoes.get().preparacao.itens.get().item


def test_sem_token_recusa(client, bolinha):
    assert client.get("/api/agente/estoque/").status_code == 401
    assert client.get("/api/agente/estoque/", HTTP_AUTHORIZATION="Bearer errado").status_code == 401


def test_token_nao_configurado_desliga_api(client, settings):
    settings.AGENTE_TOKEN = ""
    assert get(client, "/api/agente/estoque/").status_code == 503


def test_so_aceita_get(client):
    assert client.post("/api/agente/estoque/", HTTP_AUTHORIZATION=f"Bearer {TOKEN}").status_code == 405


def test_estoque_busca_sem_acento_e_mostra_saldo(client, farinha):
    farinha.estoque_minimo = D("5000")
    farinha.save()
    entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra", autor="dono")
    itens = get(client, "/api/agente/estoque/", busca="FARINHA de TRIGO").json()["itens"]
    assert len(itens) == 1
    assert itens[0]["saldo"]["texto"] == "2 kg"
    assert itens[0]["abaixo_do_minimo"] is True


def test_validades_lista_lote_perto_de_vencer(client, farinha):
    hoje = timezone.localdate()
    entrada_manual(item_id=farinha.id, quantidade=D("1"), unidade="kg", custo_total=D("5"), motivo="compra",
                   autor="dono", validade=hoje + timedelta(days=2))
    entrada_manual(item_id=farinha.id, quantidade=D("1"), unidade="kg", custo_total=D("5"), motivo="compra",
                   autor="dono", validade=hoje + timedelta(days=30))
    lotes = get(client, "/api/agente/validades/", dias=3).json()["lotes"]
    assert [l["dias_restantes"] for l in lotes] == [2]


def test_receita_aponta_falta(client, bolinha, farinha):
    entrada_manual(item_id=farinha.id, quantidade=D("500"), unidade="g", custo_total=D("3"), motivo="compra", autor="dono")
    r = get(client, "/api/agente/receita/", produto_id=bolinha.id, unidades=10).json()
    assert r["da_para_produzir"] is False
    assert r["ingredientes"][0]["necessario"]["texto"] == "1 kg"
    assert r["ingredientes"][0]["falta"]["texto"] == "500 g"


def test_receita_valida_parametros(client):
    assert get(client, "/api/agente/receita/", produto_id="x").status_code == 400
    assert get(client, "/api/agente/receita/", produto_id=999, unidades=1).status_code == 404


def test_producao_em_andamento(client, bolinha, farinha):
    entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra", autor="dono")
    pid = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"]
    lista = get(client, "/api/agente/producoes/").json()["producoes"]
    assert [p["id"] for p in lista] == [pid]
    p = get(client, f"/api/agente/producoes/{pid}/").json()
    assert p["etapa_atual"].startswith("mise en place")
    assert p["falta_pesar"][0]["previsto"]["texto"] == "1 kg"
