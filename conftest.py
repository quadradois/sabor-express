from decimal import Decimal as D

import pytest
from cadastros.models import Item
from fichas.models import Ficha, ComponenteItem, Proporcao, Etapa
from django.contrib.auth import get_user_model


@pytest.fixture
def dono(client, db):
    user = get_user_model().objects.create_user("dono", password="x")
    client.force_login(user)
    return user


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
