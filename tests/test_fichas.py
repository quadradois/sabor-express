from decimal import Decimal as D
import pytest
from cadastros.models import Item
from fichas.models import Ficha, ComponenteItem, ComponentePreparacao, Proporcao
from fichas.validacao import validar_ficha
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db

def prep(nome, rend="1000"):
    return Ficha.objects.create(nome=nome, tipo="preparacao", rendimento_g=D(rend))

def test_proporcoes_devem_somar_100():
    p = Ficha.objects.create(nome="Coxinha", tipo="produto")
    Proporcao.objects.create(ficha=p, preparacao=prep("Massa"), percentual=D("60"), ordem=1)
    Proporcao.objects.create(ficha=p, preparacao=prep("Recheio"), percentual=D("30"), ordem=2)
    with pytest.raises(RegraViolada, match="somam 90"):
        validar_ficha(p)

def test_preparacao_exige_rendimento_positivo():
    with pytest.raises(RegraViolada, match="rendimento"):
        validar_ficha(Ficha.objects.create(nome="Massa", tipo="preparacao", rendimento_g=D("0")))

def test_ciclo_entre_preparacoes_e_recusado():
    a, b = prep("Caldo"), prep("Massa")
    ComponentePreparacao.objects.create(ficha=b, preparacao=a, quantidade_g=D("600"), ordem=1)
    ComponentePreparacao.objects.create(ficha=a, preparacao=b, quantidade_g=D("10"), ordem=1)
    with pytest.raises(RegraViolada, match="circular"):
        validar_ficha(a)

def test_ficha_valida_passa():
    sal = Item.objects.create(nome="Sal", tipo="ingrediente", unidade_base="g", controla_validade=False)
    m = prep("Massa")
    ComponenteItem.objects.create(ficha=m, item=sal, quantidade=D("8"), ordem=1)
    validar_ficha(m)
