from decimal import Decimal as D
import pytest
from cadastros.models import Item, Conversao
from cadastros.unidades import para_base
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db

@pytest.fixture
def farinha(): return Item.objects.create(nome="Farinha de trigo", tipo="ingrediente", unidade_base="g")
@pytest.fixture
def oleo(): return Item.objects.create(nome="Óleo", tipo="insumo", unidade_base="mL")
@pytest.fixture
def ovo(): return Item.objects.create(nome="Ovo", tipo="ingrediente", unidade_base="un")

def test_padroes_fixos(farinha, oleo):
    assert para_base(farinha, D("1.8"), "kg") == D("1800")
    assert para_base(farinha, D("250"), "g") == D("250")
    assert para_base(oleo, D("2.7"), "L") == D("2700")

def test_conversao_cadastrada(ovo, oleo):
    Conversao.objects.create(item=ovo, unidade="dz", fator=D("12"))
    Conversao.objects.create(item=oleo, unidade="kg", fator=D("1087"))
    assert para_base(ovo, D("2.5"), "dz") == D("30")
    assert para_base(oleo, D("15"), "kg") == D("16305")

def test_sem_fator_recusa_com_mensagem(oleo, ovo):
    with pytest.raises(RegraViolada, match="Cadastre o fator de 'kg' para 'Ovo'"):
        para_base(ovo, D("1"), "kg")
    with pytest.raises(RegraViolada, match="Cadastre o fator de 'g' para 'Óleo'"):
        para_base(oleo, D("1"), "g")

def test_fator_zero_recusado_pelo_banco(ovo):
    from django.db import IntegrityError, transaction
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Conversao.objects.create(item=ovo, unidade="dz", fator=D("0"))

def test_unidade_ignora_maiusculas(farinha, ovo, oleo):
    assert para_base(farinha, D("1"), "Kg") == D("1000")
    assert para_base(farinha, D("1"), "KG") == D("1000")
    assert para_base(oleo, D("1"), "l") == D("1000")
    assert para_base(oleo, D("5"), "ML") == D("5")
    Conversao.objects.create(item=ovo, unidade="dz", fator=D("12"))
    assert para_base(ovo, D("1"), "DZ") == D("12")

def test_unidade_base_nao_muda_com_movimentos(farinha):
    from django.core.exceptions import ValidationError
    from estoque.servicos import entrada_manual
    farinha.controla_validade = False
    farinha.save()
    farinha.unidade_base = "un"
    farinha.full_clean()  # sem movimentos: pode
    farinha.unidade_base = "g"
    entrada_manual(item_id=farinha.id, quantidade=D("1"), unidade="kg", custo_total=D("1"), motivo="x", autor="dono")
    farinha.unidade_base = "un"
    with pytest.raises(ValidationError, match="unidade base"):
        farinha.full_clean()

def test_admin_unidade_base_somente_leitura_com_movimentos(farinha):
    from django.contrib.admin.sites import site
    from estoque.servicos import entrada_manual
    farinha.controla_validade = False
    farinha.save()
    admin = site._registry[Item]
    assert "unidade_base" not in admin.get_readonly_fields(None, farinha)
    entrada_manual(item_id=farinha.id, quantidade=D("1"), unidade="kg", custo_total=D("1"), motivo="x", autor="dono")
    assert "unidade_base" in admin.get_readonly_fields(None, farinha)
