from decimal import Decimal as D
import datetime as dt
import pytest
from cadastros.models import Item
from estoque.servicos import entrada_manual
from fichas.models import Ficha, ComponenteItem, ComponentePreparacao, Proporcao, Etapa
from fichas.escala import escalar
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db

def item(nome, base="g"): return Item.objects.create(nome=nome, tipo="ingrediente", unidade_base=base, controla_validade=False)
def prep(nome, rend="1000"): return Ficha.objects.create(nome=nome, tipo="preparacao", rendimento_g=D(rend))

@pytest.fixture
def coxinha():
    farinha, caldo_frango, frango, requeijao, rosca = item("Farinha de trigo"), item("Caldo", "mL"), item("Frango"), item("Requeijão"), item("Farinha de rosca")
    massa, recheio, emp = prep("Massa"), prep("Recheio"), prep("Empanamento")
    ComponenteItem.objects.create(ficha=massa, item=caldo_frango, quantidade=D("600"), ordem=1)
    ComponenteItem.objects.create(ficha=massa, item=farinha, quantidade=D("400"), ordem=2)
    ComponenteItem.objects.create(ficha=recheio, item=frango, quantidade=D("800"), ordem=1)
    ComponenteItem.objects.create(ficha=recheio, item=requeijao, quantidade=D("120"), ordem=2)
    ComponenteItem.objects.create(ficha=emp, item=rosca, quantidade=D("700"), ordem=1)
    ComponenteItem.objects.create(ficha=emp, item=farinha, quantidade=D("300"), ordem=2)
    p = Ficha.objects.create(nome="Coxinha de frango", tipo="produto")
    Proporcao.objects.create(ficha=p, preparacao=recheio, percentual=D("33"), ordem=1)
    Proporcao.objects.create(ficha=p, preparacao=massa, percentual=D("60"), ordem=2)
    Proporcao.objects.create(ficha=p, preparacao=emp, percentual=D("7"), ordem=3)
    Etapa.objects.create(ficha=p, ordem=1, instrucao="Modele as coxinhas")
    return p

def test_totais_e_ordem_dos_blocos(coxinha):
    r = escalar(coxinha, 50, D("150"))
    assert r.total_g == D("7500")
    assert [(b.nome, b.total_g) for b in r.blocos] == [
        ("Recheio", D("2475")), ("Massa", D("4500")), ("Empanamento", D("525")), ("Montagem", D("7500"))]
    assert r.blocos[-1].linhas == [] and r.blocos[-1].etapas[0].instrucao == "Modele as coxinhas"

def test_ingredientes_escalados(coxinha):
    massa = escalar(coxinha, 50, D("150")).blocos[1]
    assert {l.nome: l.quantidade for l in massa.linhas} == {"Caldo": D("2700"), "Farinha de trigo": D("1800")}

def test_falta_considera_necessidade_total_do_item(coxinha):
    farinha = Item.objects.get(nome="Farinha de trigo")
    entrada_manual(item_id=farinha.id, quantidade=D("1.9"), unidade="kg", custo_total=D("10"), motivo="inicial", autor="dono")
    r = escalar(coxinha, 50, D("150"))
    # massa 1800 g + empanamento 157,5 g = 1957,5 g; saldo 1900 g
    linhas_farinha = [l for b in r.blocos for l in b.linhas if l.nome == "Farinha de trigo"]
    assert [l.falta for l in linhas_farinha] == [D("57.5"), D("57.5")]
    assert next(l for l in r.blocos[0].linhas if l.nome == "Frango").falta == D("1980")

def test_subpreparacao_vem_antes_da_preparacao_que_a_usa(coxinha):
    caldo_caseiro = prep("Caldo caseiro", "2000")
    agua = item("Água", "mL")
    ComponenteItem.objects.create(ficha=caldo_caseiro, item=agua, quantidade=D("2000"), ordem=1)
    ComponentePreparacao.objects.create(ficha=Ficha.objects.get(nome="Massa"), preparacao=caldo_caseiro, quantidade_g=D("100"), ordem=3)
    nomes = [b.nome for b in escalar(coxinha, 50, D("150")).blocos]
    assert nomes.index("Caldo caseiro") == nomes.index("Massa") - 1
    caldo = next(b for b in escalar(coxinha, 50, D("150")).blocos if b.nome == "Caldo caseiro")
    assert caldo.total_g == D("450") and caldo.linhas[0].quantidade == D("450")

@pytest.mark.parametrize("unidades,peso", [(0, D("150")), (50, D("0")), (-1, D("150"))])
def test_pedido_invalido(coxinha, unidades, peso):
    with pytest.raises(RegraViolada):
        escalar(coxinha, unidades, peso)

def test_so_ficha_de_produto(coxinha):
    with pytest.raises(RegraViolada, match="produto"):
        escalar(Ficha.objects.get(nome="Massa"), 10, D("100"))
