"""Plano 7, fase 2a: telas de custos, margens, ranking, previsto × realizado e relatório (somente leitura)."""
import datetime as dt
import html as _html
import re
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Fornecedor, Item
from compras.servicos import registrar_compra
from estoque.models import CriterioValidade, Lote, Movimento
from estoque.servicos import entrada_manual
from fichas.models import Ficha
from producao.models import Producao
from producao.servicos import concluir_producao, iniciar_producao, registrar_peso
from vendas.servicos import registrar_venda, salvar_apresentacao

pytestmark = pytest.mark.django_db
HOJE = timezone.localdate()


def limpo(r):
    """O texto da página como se lê na tela: sem tags e com espaços simples."""
    return " ".join(re.sub(r"<[^>]+>", " ", _html.unescape(r.content.decode())).split())


def comprar_farinha(valor="10"):
    farinha = Item.objects.get(nome="Farinha de trigo")
    f = Fornecedor.objects.create(nome="Atacadão")
    registrar_compra(fornecedor_id=f.id, data_compra=HOJE, total=D(valor), condicao="a_vista", autor="dono",
                     linhas=[{"item_id": farinha.id, "quantidade": D("2"), "unidade": "kg", "valor": D(valor)}])
    return farinha


def vender_coxinha(custo="0.60", quantidade=10):
    salgado = Item.objects.create(nome="Coxinha 150 g", tipo="produto", unidade_base="un")
    l = Lote.objects.create(item=salgado, forma="cru", validade=HOJE + dt.timedelta(days=30), custo_unitario=D(custo))
    Movimento.objects.create(tipo="entrada_producao", item=salgado, lote=l, quantidade=100, quantidade_informada=100,
                             unidade_informada="un", fator=1, motivo="teste", estado="congelado", validade=l.validade)
    apr = salvar_apresentacao(produto_id=salgado.id, nome="unidade", forma="cru", estado="congelado", unidades=1,
                              preco_varejo=D("5"), autor="dono")["apresentacao_id"]
    return registrar_venda(itens=[{"apresentacao_id": apr, "quantidade": quantidade}], data_venda=HOJE,
                           forma_pagamento="pix", autor="dono")["venda_id"]


@pytest.fixture
def producao_concluida(bolinha):
    farinha = comprar_farinha()
    entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("12"), motivo="estoque", autor="dono")
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"]
    [linha] = Producao.objects.get(id=p).linhas.all()
    registrar_peso(linha_id=linha.id, usado=D("1100"), autor="dono")
    concluir_producao(producao_id=p, quantidade_boa=9, perdas=1, perda_motivo="rasgou", estado="resfriado", autor="dono")
    return p


# ---------- acesso ----------

def urls(bolinha):
    massa = Ficha.objects.get(nome="Massa simples")
    farinha = Item.objects.get(nome="Farinha de trigo")
    return [reverse(n) for n in ("custos", "margens", "ranking", "previsto_realizado", "relatorio")] + [
        reverse("custo_produto", args=[bolinha.id]), reverse("custo_preparacao", args=[massa.id]),
        reverse("evolucao_preco", args=[farinha.id]), reverse("previsto_producao", args=[1])]


def test_telas_exigem_login(client, bolinha):
    for u in urls(bolinha):
        r = client.get(u)
        assert r.status_code == 302 and "/entrar/" in r.url, u


def test_telas_abrem_logado(client, dono, bolinha, producao_concluida):
    vender_coxinha()
    for u in urls(bolinha)[:-1] + [reverse("previsto_producao", args=[producao_concluida])]:
        assert client.get(u).status_code == 200, u
    for agrupar in ("produto", "apresentacao", "cliente", "tabela", "dia"):
        assert client.get(reverse("margens"), {"agrupar": agrupar}).status_code == 200, agrupar
    for ordem in ("receita", "unidades", "margem"):
        assert client.get(reverse("ranking"), {"ordem": ordem}).status_code == 200, ordem
    for periodo in ("hoje", "ontem", "semana", "semana_passada", "mes", "mes_passado", "ultimos_7", "ultimos_30"):
        for nome in ("margens", "ranking", "previsto_realizado", "relatorio"):
            assert client.get(reverse(nome), {"periodo": periodo}).status_code == 200, (nome, periodo)
    assert client.get(reverse("previsto_realizado"), {"produto": bolinha.id}).status_code == 200


def test_inexistentes_dao_404(client, dono, bolinha):
    farinha = Item.objects.get(nome="Farinha de trigo")
    assert client.get(reverse("custo_produto", args=[farinha.id])).status_code == 404  # não é produto
    assert client.get(reverse("custo_produto", args=[9999])).status_code == 404
    assert client.get(reverse("custo_preparacao", args=[9999])).status_code == 404
    assert client.get(reverse("evolucao_preco", args=[9999])).status_code == 404
    assert client.get(reverse("previsto_producao", args=[9999])).status_code == 404


def test_menu_da_tela_hoje_tem_custos_e_relatorios(client, dono):
    t = limpo(client.get(reverse("inicio")))
    assert "Custos e relatórios" in t


# ---------- custos ----------

def test_ingrediente_nunca_comprado_mostra_o_que_falta_e_nao_zero(client, dono, bolinha):
    t = limpo(client.get(reverse("custos")))
    assert "incompleto: falta comprar Farinha de trigo" in t
    assert "Cru (ingredientes + indiretos)" not in t  # o custo do produto não é inventado
    d = limpo(client.get(reverse("custo_produto", args=[bolinha.id])))
    assert "incompleto: falta comprar Farinha de trigo (nunca comprado)" in d and "não é o custo do produto" in d
    assert "nunca comprado" in d
    p = limpo(client.get(reverse("custo_preparacao", args=[Ficha.objects.get(nome="Massa simples").id])))
    assert "incompleto: falta comprar Farinha de trigo" in p


def test_custo_completo_com_a_compra_de_referencia(client, dono, bolinha):
    farinha = comprar_farinha()  # R$ 0,005 por g; bolinha de 100 g = 100 g de massa
    t = limpo(client.get(reverse("custos")))
    assert "incompleto" not in t and "R$ 0,5000" in t and "R$ 0,5500" in t  # cru e frito
    d = limpo(client.get(reverse("custo_produto", args=[bolinha.id])))
    assert "estimado" in d and "Massa simples" in d and "Atacadão" in d and "R$ 0,5000" in d
    assert reverse("evolucao_preco", args=[farinha.id]) in client.get(reverse("custo_produto", args=[bolinha.id])).content.decode()
    p = limpo(client.get(reverse("custo_preparacao", args=[Ficha.objects.get(nome="Massa simples").id])))
    assert "Por kg: R$ 5,00" in p


def test_evolucao_de_preco_do_item(client, dono, bolinha):
    farinha = comprar_farinha("10")
    f = Fornecedor.objects.get(nome="Atacadão")
    registrar_compra(fornecedor_id=f.id, data_compra=HOJE + dt.timedelta(days=1), total=D("12"), condicao="a_vista",
                     autor="dono", linhas=[{"item_id": farinha.id, "quantidade": D("2"), "unidade": "kg", "valor": D("12")}])
    t = limpo(client.get(reverse("evolucao_preco", args=[farinha.id])))
    assert "Preço de Farinha de trigo" in t and "+20,0%" in t and "R$ 0,0060" in t
    assert "Nenhuma compra" in limpo(client.get(reverse("evolucao_preco", args=[farinha.id]), {"de": "2999-01-01"}))
    assert client.get(reverse("evolucao_preco", args=[farinha.id]), {"de": "lixo"}).status_code == 200


# ---------- margens e ranking ----------

def test_margens_rotulo_estimada_e_o_que_nao_inclui(client, dono, bolinha):
    vender_coxinha("0.60", 10)  # R$ 50 de venda, custo R$ 6: margem 44 = 88,0%
    t = limpo(client.get(reverse("margens"), {"periodo": "hoje"}))
    assert "estimada" in t and "Não inclui:" in t and "tributos" in t
    assert "R$ 44,00" in t and "88,0%" in t and "Coxinha 150 g" in t
    assert "Período anterior" in t and "Margem estimada dos preços de hoje" in t


def test_margens_fora_da_margem_com_o_motivo(client, dono, bolinha):
    vender_coxinha("0", 4)  # lote sem custo: a venda entra na receita, mas não na margem
    t = limpo(client.get(reverse("margens"), {"periodo": "hoje"}))
    assert "Fora da margem" in t and "1 linha(s)" in t and "R$ 20,00" in t
    assert "Sem margem para estimar" in t


def test_margem_da_tabela_de_preco_incompleta_e_completa(client, dono, bolinha):
    salvar_apresentacao(produto_id=bolinha.id, nome="unidade", forma="cru", estado="resfriado", unidades=1,
                        preco_varejo=D("2"), autor="dono")
    t = limpo(client.get(reverse("margens")))
    assert "incompleto: falta comprar Farinha de trigo" in t and "sem custo completo não dá para estimar" in t
    comprar_farinha()  # custo 0,5000: margem 1,50 = 75,0%
    t = limpo(client.get(reverse("margens")))
    assert "R$ 1,50" in t and "75,0%" in t
    assert "75,0%" in limpo(client.get(reverse("custo_produto", args=[bolinha.id])))


def test_periodo_invalido_nao_quebra(client, dono, bolinha):
    for nome in ("margens", "ranking", "previsto_realizado", "relatorio"):
        r = client.get(reverse(nome), {"periodo": "lixo"})
        assert r.status_code == 200 and "Período desconhecido: lixo" in limpo(r), nome
        r = client.get(reverse(nome), {"de": "lixo"})
        assert r.status_code == 200 and "data inválida" in limpo(r), nome
        r = client.get(reverse(nome), {"de": "2026-02-01", "ate": "2026-01-01"})
        assert r.status_code == 200 and "fim do período vem antes do início" in limpo(r), nome
        assert client.get(reverse(nome), {"de": "2026-01-01", "ate": "2026-01-31"}).status_code == 200
    assert client.get(reverse("margens"), {"agrupar": "cor"}).status_code == 200
    assert client.get(reverse("ranking"), {"ordem": "cor"}).status_code == 200


def test_ranking_com_participacao_e_acumulado(client, dono, bolinha):
    vender_coxinha("0.60", 10)
    t = limpo(client.get(reverse("ranking"), {"periodo": "hoje"}))
    assert "Coxinha 150 g" in t and "100,0%" in t and "R$ 50,00" in t and "estimada" in t
    assert "Nenhuma venda" in limpo(client.get(reverse("ranking"), {"periodo": "ontem"}))


# ---------- previsto × realizado ----------

def test_previsto_realizado_lista_e_detalhe(client, dono, bolinha, producao_concluida):
    t = limpo(client.get(reverse("previsto_realizado"), {"periodo": "hoje"}))
    assert "Bolinha" in t and "90,0%" in t and "R$ 5,00" in t and "R$ 6,60" in t
    d = limpo(client.get(reverse("previsto_producao", args=[producao_concluida])))
    assert "9 boas de 10 planejadas" in d and "90,0%" in d and "+10,0%" in d and "+32,0%" in d
    assert "Farinha de trigo" in d
    pagina = client.get(reverse("producao", args=[producao_concluida])).content.decode()
    assert reverse("previsto_producao", args=[producao_concluida]) in pagina


def test_producao_sem_compra_fica_fora_da_comparacao_de_custo(client, dono, bolinha):
    farinha = Item.objects.get(nome="Farinha de trigo")
    entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("12"), motivo="estoque", autor="dono")
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"]
    [linha] = Producao.objects.get(id=p).linhas.all()
    registrar_peso(linha_id=linha.id, usado=D("1000"), autor="dono")
    concluir_producao(producao_id=p, quantidade_boa=10, estado="resfriado", autor="dono")
    t = limpo(client.get(reverse("previsto_realizado"), {"periodo": "hoje"}))
    assert "Fora da comparação de custo" in t and "Sem previsto" in t and "Custo sem comparação" in t
    d = limpo(client.get(reverse("previsto_producao", args=[p])))
    assert "Sem custo previsto: falta compra de Farinha de trigo" in d


# ---------- relatório ----------

def test_relatorio_do_periodo(client, dono, bolinha, producao_concluida):
    vender_coxinha("0.60", 10)
    t = limpo(client.get(reverse("relatorio"), {"periodo": "hoje"}))
    for trecho in ("estimado", "antes das despesas", "Não é lucro", "R$ 50,00", "R$ 44,00", "Perdas com valor",
                   "Compras", "Dinheiro anotado", "Contas em aberto hoje", "Produção e fritura", "Encomendas",
                   "despesas (aluguel"):
        assert trecho in t, trecho
    assert "1 produção(ões)" in t and "estimada" in t
