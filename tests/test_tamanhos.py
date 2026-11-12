from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError

from cadastros.models import Item
from cadastros.servicos import criar_tamanho
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db


def test_criar_tamanho_cria_item_produto(coxinha):
    r = criar_tamanho(ficha_id=coxinha.id, peso_g=D("25"), autor="dono")
    i = Item.objects.get(id=r["item_id"])
    assert (i.nome, i.tipo, i.unidade_base, i.ficha, i.peso_g) == ("Coxinha de frango 25 g", "produto", "un", coxinha, D("25"))


def test_tamanho_repetido_recusado(coxinha):
    criar_tamanho(ficha_id=coxinha.id, peso_g=D("25"), autor="dono")
    with pytest.raises(RegraViolada, match="Esse tamanho já existe: Coxinha de frango 25 g."):
        criar_tamanho(ficha_id=coxinha.id, peso_g=D("25"), autor="dono")


def test_peso_decimal_no_nome(coxinha):
    assert criar_tamanho(ficha_id=coxinha.id, peso_g=D("12.5"), autor="dono")["nome"] == "Coxinha de frango 12,5 g"


def test_tamanho_peso_zero_recusado(coxinha):
    with pytest.raises(RegraViolada, match="maior que zero"):
        criar_tamanho(ficha_id=coxinha.id, peso_g=D("0"), autor="dono")


def test_tamanho_de_preparacao_recusado(coxinha):
    prep = coxinha.proporcoes.first().preparacao
    with pytest.raises(RegraViolada):
        criar_tamanho(ficha_id=prep.id, peso_g=D("25"), autor="dono")


def test_produto_sem_ficha_invalido():
    with pytest.raises(ValidationError):
        Item(nome="X", tipo="produto", unidade_base="un").full_clean()


def test_entrada_manual_nao_lista_produto(client, dono, bolinha):
    html = client.get("/estoque/entrada/").content.decode()
    assert "Bolinha 100 g" not in html and "Farinha de trigo" in html
