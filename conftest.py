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


@pytest.fixture
def bolinha():
    from cadastros.servicos import criar_tamanho
    farinha = item("Farinha de trigo")
    massa = prep("Massa simples")
    ComponenteItem.objects.create(ficha=massa, item=farinha, quantidade=D("1000"), ordem=1)
    Etapa.objects.create(ficha=massa, ordem=1, instrucao="Sove a massa", tempo_seg=300)
    p = Ficha.objects.create(nome="Bolinha", tipo="produto")
    Proporcao.objects.create(ficha=p, preparacao=massa, percentual=D("100"), ordem=1)
    Etapa.objects.create(ficha=p, ordem=1, instrucao="Modele as bolinhas")
    r = criar_tamanho(ficha_id=p.id, peso_g=D("100"), oleo_ref_un=D("0.05"), autor="teste")
    return Item.objects.get(id=r["item_id"])


@pytest.fixture
def lote_produzido(bolinha):
    from estoque.models import CriterioValidade, Lote
    from estoque.servicos import entrada_manual
    from producao.servicos import concluir_producao, iniciar_producao, usar_previsto_restantes
    farinha = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra", autor="dono")
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"]
    usar_previsto_restantes(producao_id=p, autor="dono")
    r = concluir_producao(producao_id=p, quantidade_boa=9, perdas=1, perda_motivo="rasgou", estado="resfriado", autor="dono")
    return Lote.objects.get(id=r["lote_id"])
