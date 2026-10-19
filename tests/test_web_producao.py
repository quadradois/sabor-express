import html as _html
from decimal import Decimal as D
import pytest
from cadastros.models import Item
from estoque.servicos import entrada_manual
from producao.models import Producao
from producao.servicos import iniciar_producao

pytestmark = pytest.mark.django_db


def texto(r):
    return _html.unescape(r.content.decode())


@pytest.fixture
def farinha_em_estoque(bolinha):
    f = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    entrada_manual(item_id=f.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra", autor="dono")


@pytest.fixture
def producao(bolinha, farinha_em_estoque):
    return Producao.objects.get(id=iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"])


def dados(b, chave="k1"):
    return {"produto": b.id, "unidades": 10, "forma": "cru", "chave": chave}


def test_nova_producao_mostra_receita_e_comeca(client, dono, bolinha, farinha_em_estoque):
    r = client.get("/producao/nova/", {"produto": bolinha.id, "unidades": 10, "forma": "cru"})
    assert "Massa simples" in texto(r) and "Começar preparo" in texto(r)
    r = client.post("/producao/nova/", dados(bolinha))
    assert r.status_code == 302 and Producao.objects.count() == 1
    assert client.get(r.url).status_code == 200


def test_comecar_com_falta_mostra_erro(client, dono, bolinha):
    r = client.post("/producao/nova/", dados(bolinha))
    assert "Dê entrada no estoque antes de começar." in texto(r) and not Producao.objects.exists()


def test_duplo_envio_uma_producao(client, dono, bolinha, farinha_em_estoque):
    client.post("/producao/nova/", dados(bolinha))
    client.post("/producao/nova/", dados(bolinha))
    assert Producao.objects.count() == 1


def test_outro_tamanho(client, dono, bolinha):
    r = client.post("/producao/tamanho/", {"ficha": bolinha.ficha.id, "peso": "25", "chave": "t1"})
    novo = Item.objects.get(nome="Bolinha 25 g")
    assert r.status_code == 302 and r.url == f"/producao/nova/?produto={novo.id}"


def test_lista_em_andamento(client, dono, producao):
    r = client.get("/producao/")
    assert f"/producao/{producao.id}/" in texto(r) and "Nova produção" in texto(r)
