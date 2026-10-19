import html as _html
from decimal import Decimal as D
import pytest
from cadastros.models import Item
from estoque.models import Movimento

pytestmark = pytest.mark.django_db

def texto(r):
    return _html.unescape(r.content.decode())

def test_gera_receita(client, dono, coxinha):
    r = client.get("/receita/", {"ficha": coxinha.id, "unidades": 50, "peso": "150"})
    html = texto(r)
    assert r.status_code == 200
    assert "7,5 kg" in html and "Recheio" in html and "Massa" in html
    assert html.index("Recheio") < html.index("Massa") < html.index("Empanamento")
    assert "falta 1,98 kg" in html   # frango sem estoque

@pytest.mark.parametrize("unidades,peso", [("0", "150"), ("50", "0"), ("-3", "150")])
def test_pedido_invalido_mostra_erro(client, dono, coxinha, unidades, peso):
    r = client.get("/receita/", {"ficha": coxinha.id, "unidades": unidades, "peso": peso})
    assert r.status_code == 200 and "maior que zero" in texto(r)

def test_entrada_duplo_envio_gera_um_movimento(client, dono):
    sal = Item.objects.create(nome="Sal", tipo="ingrediente", unidade_base="g", controla_validade=False)
    dados = {"item": sal.id, "quantidade": "1", "unidade": "kg", "custo_total": "3,50",
             "motivo": "estoque inicial", "chave": "form-abc"}
    client.post("/estoque/entrada/", dados)
    client.post("/estoque/entrada/", dados)
    assert Movimento.objects.count() == 1

def test_entrada_sem_fator_mostra_mensagem(client, dono):
    ovo = Item.objects.create(nome="Ovo", tipo="ingrediente", unidade_base="un", controla_validade=False)
    r = client.post("/estoque/entrada/", {"item": ovo.id, "quantidade": "1", "unidade": "dz",
                                          "custo_total": "10", "motivo": "x", "chave": "form-def"})
    assert "Cadastre o fator de 'dz' para 'Ovo'" in texto(r)

@pytest.fixture
def sal(db):
    return Item.objects.create(nome="Sal", tipo="ingrediente", unidade_base="g", controla_validade=False)

def entrada(client, sal, **kw):
    dados = {"item": sal.id, "quantidade": "1", "unidade": "kg", "custo_total": "3,50",
             "motivo": "estoque inicial", "chave": "form-x"} | kw
    return client.post("/estoque/entrada/", dados)

def test_entrada_recusa_ponto_decimal(client, dono, sal):
    r = entrada(client, sal, quantidade="1.500")
    assert "Use vírgula para decimais (ex.: 1,5)." in texto(r) and not Movimento.objects.exists()

def test_entrada_numero_enorme_vira_erro_de_formulario(client, dono, sal):
    r = entrada(client, sal, quantidade="1e30")
    assert r.status_code == 200 and "errorlist" in texto(r) and not Movimento.objects.exists()

def test_entrada_mesma_chave_outra_quantidade_recusa(client, dono, sal):
    entrada(client, sal, quantidade="1", chave="k")
    r = entrada(client, sal, quantidade="5", chave="k")
    assert "Esta chave já foi usada para outra operação." in texto(r)
    assert Movimento.objects.count() == 1

def test_entrada_recusada_registra_erro(client, dono, sal):
    from nucleo.models import RegistroOperacao
    r = entrada(client, sal, motivo=" ")
    assert "Informe o motivo da entrada." in texto(r)
    assert RegistroOperacao.objects.get().status == "erro"

def test_entrada_unidade_maiuscula(client, dono, sal):
    entrada(client, sal, unidade="Kg")
    assert Movimento.objects.get().quantidade == D("1000")

def test_entrada_nao_lista_item_inativo(client, dono, sal):
    Item.objects.create(nome="Velho", tipo="ingrediente", unidade_base="g", ativo=False)
    html = texto(client.get("/estoque/entrada/"))
    assert "Sal" in html and "Velho" not in html
