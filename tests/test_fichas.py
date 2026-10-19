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


def test_produto_sem_proporcoes():
    with pytest.raises(RegraViolada, match="proporção"):
        validar_ficha(Ficha.objects.create(nome="X", tipo="produto"))

def test_produto_valido_passa():
    p = Ficha.objects.create(nome="Coxinha", tipo="produto")
    Proporcao.objects.create(ficha=p, preparacao=prep("Massa"), percentual=D("60"), ordem=1)
    Proporcao.objects.create(ficha=p, preparacao=prep("Recheio"), percentual=D("40"), ordem=2)
    validar_ficha(p)

def test_autorreferencia_e_circular():
    a = prep("Caldo")
    ComponentePreparacao.objects.create(ficha=a, preparacao=a, quantidade_g=D("5"), ordem=1)
    with pytest.raises(RegraViolada, match="circular"):
        validar_ficha(a)

def test_alvo_de_tipo_errado():
    p = Ficha.objects.create(nome="Coxinha", tipo="produto")
    outro = Ficha.objects.create(nome="Kit", tipo="produto")
    Proporcao.objects.create(ficha=p, preparacao=outro, percentual=D("100"), ordem=1)
    with pytest.raises(RegraViolada, match="Kit"):
        validar_ficha(p)

def test_produto_com_item_e_recusado():
    sal = Item.objects.create(nome="Sal", tipo="ingrediente", unidade_base="g")
    p = Ficha.objects.create(nome="Coxinha", tipo="produto")
    ComponenteItem.objects.create(ficha=p, item=sal, quantidade=D("1"))
    with pytest.raises(RegraViolada, match="Produto"):
        validar_ficha(p)

def test_preparacao_com_proporcao_e_recusada():
    m = prep("Massa")
    Proporcao.objects.create(ficha=m, preparacao=prep("Outra"), percentual=D("100"))
    with pytest.raises(RegraViolada, match="proporções"):
        validar_ficha(m)

def test_percentual_deve_ser_positivo():
    from django.db import IntegrityError, transaction
    p = Ficha.objects.create(nome="Coxinha", tipo="produto")
    with pytest.raises(IntegrityError), transaction.atomic():
        Proporcao.objects.create(ficha=p, preparacao=prep("Massa"), percentual=D("0"))
