"""Plano 7, fase 2b: ferramentas do agente de voz para custos, margens, previsto × realizado e relatório.

Todas de leitura: nenhuma grava. O texto falado traz os números prontos (o modelo não faz conta), sempre
"estimada"/"antes das despesas", sem "R$", sem "15/11" e sem a palavra lucro."""

import json
import re
from datetime import timedelta
from decimal import Decimal as D

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone
from mcp.shared.memory import create_connected_server_and_client_session

from agente.custos import _periodo
from agente.ferramentas import REGISTRO, criar_servidor
from agente.models import Proposta
from cadastros.models import Fornecedor, Item
from cadastros.servicos import salvar_cliente
from compras.servicos import registrar_compra
from estoque.models import CriterioValidade, Lote, Movimento
from estoque.servicos import entrada_manual
from fichas.models import ComponenteItem, ComponentePreparacao, Ficha, Proporcao
from nucleo.models import RegistroOperacao
from producao.models import Producao
from producao.servicos import concluir_producao, iniciar_producao, registrar_peso, usar_previsto_restantes
from vendas.servicos import cancelar_venda, registrar_venda, salvar_apresentacao

pytestmark = pytest.mark.django_db
HOJE = timezone.localdate()
CUSTOS = {"ver_custo", "ver_margem", "ver_margem_tabela", "ver_mais_vendidos", "ver_previsto_realizado",
          "ver_relatorio", "ver_evolucao_preco"}


def dia(n):
    return HOJE + timedelta(days=n)


@async_to_sync
async def _sessao(acao):
    async with create_connected_server_and_client_session(criar_servidor()) as s:
        return await acao(s)


def chamar(ferramenta, **args):
    async def acao(s):
        return await s.call_tool(ferramenta, args)
    r = _sessao(acao)
    assert not r.isError, r.content
    return json.loads(r.content[0].text)


def ferramentas():
    async def acao(s):
        return (await s.list_tools()).tools
    return {t.name: t for t in _sessao(acao)}


def falado(r):
    """O texto da voz: sem "R$", sem "15/11", sem "lucro" e sem conta para o modelo fazer."""
    assert "erro" not in r, r
    t = r["texto"]
    assert "R$" not in t and not re.search(r"\d/\d", t) and "lucro" not in t.lower(), t
    return t


# --- cenário --------------------------------------------------------------------------

@pytest.fixture
def atacadao():
    return Fornecedor.objects.create(nome="Atacadão")


def ingrediente(nome, base="g"):
    return Item.objects.create(nome=nome, tipo="ingrediente", unidade_base=base, controla_validade=False)


def comprar(fornecedor, item, quantidade, unidade, valor, quando=HOJE):
    return registrar_compra(fornecedor_id=fornecedor.id, data_compra=quando, total=D(valor), condicao="a_vista",
                            linhas=[{"item_id": item.id, "quantidade": D(quantidade), "unidade": unidade,
                                     "valor": D(valor)}], autor="dono")


def preparacao(nome, rendimento, itens=(), subs=()):
    f = Ficha.objects.create(nome=nome, tipo="preparacao", rendimento_g=D(rendimento))
    for i, (item, q) in enumerate(itens):
        ComponenteItem.objects.create(ficha=f, item=item, quantidade=D(q), ordem=i)
    for i, (sub, g) in enumerate(subs):
        ComponentePreparacao.objects.create(ficha=f, preparacao=sub, quantidade_g=D(g), ordem=i)
    return f


def produto(nome, proporcoes, peso, oleo=None, indireto=None):
    ficha = Ficha.objects.create(nome=nome, tipo="produto")
    for i, (prep, pct) in enumerate(proporcoes):
        Proporcao.objects.create(ficha=ficha, preparacao=prep, percentual=D(pct), ordem=i)
    return Item.objects.create(nome=f"{nome} {peso} g", tipo="produto", unidade_base="un", ficha=ficha,
                               peso_g=D(peso), oleo_ref_un=oleo and D(oleo), indireto_ref_un=indireto and D(indireto))


@pytest.fixture
def coxinha_fichada(atacadao):
    """Coxinha 50 g em cascata (massa 60%, recheio 40% com tempero): 0,46 de ingredientes, 0,10 de indireto,
    0,05 de óleo → cru 0,56, frito 0,61 (conferido à mão em tests/test_custos.py)."""
    farinha, leite, frango, alho = ingrediente("Farinha"), ingrediente("Leite", "mL"), ingrediente("Frango"), \
        ingrediente("Alho")
    comprar(atacadao, farinha, "10", "kg", "45")
    comprar(atacadao, leite, "10", "L", "20")
    comprar(atacadao, frango, "5", "kg", "100")
    comprar(atacadao, alho, "1", "kg", "50")
    massa = preparacao("Massa", "10000", [(farinha, "4000"), (leite, "6000")])
    tempero = preparacao("Tempero", "100", [(alho, "100")])
    recheio = preparacao("Recheio", "1000", [(frango, "800")], [(tempero, "50")])
    return produto("Coxinha", [(massa, "60"), (recheio, "40")], "50", oleo="0.05", indireto="0.10")


@pytest.fixture
def salgado():
    return Item.objects.create(nome="Coxinha 150 g", tipo="produto", unidade_base="un", oleo_ref_un=D("0.05"))


@pytest.fixture
def caixa():
    c = Item.objects.create(nome="Caixa de papelão", tipo="embalagem", unidade_base="un", controla_validade=False)
    l = Lote.objects.create(item=c, codigo="CX", custo_unitario=D("1.00"))
    Movimento.objects.create(tipo="entrada_manual", item=c, lote=l, quantidade=10, quantidade_informada=10,
                             unidade_informada="un", fator=1, motivo="compra")
    return c


def lote(prod, n, *, custo="0.60", forma="cru", estado="congelado"):
    l = Lote.objects.create(item=prod, forma=forma, validade=dia(30), custo_unitario=D(custo))
    Movimento.objects.create(tipo="entrada_producao", item=prod, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado=estado, validade=l.validade)
    return l


def apresentacao(prod, nome="unidade", unidades=1, preco="5", atacado=None, forma="cru", estado="congelado", **kw):
    return salvar_apresentacao(produto_id=prod.id, nome=nome, forma=forma, estado=estado, unidades=unidades,
                               preco_varejo=D(preco), preco_atacado=atacado and D(atacado), autor="dono",
                               **kw)["apresentacao_id"]


def vender(apr, quantidade, *, preco=None, quando=HOJE, **kw):
    item = {"apresentacao_id": apr, "quantidade": quantidade}
    if preco is not None:
        item["preco"] = D(preco)
    return registrar_venda(itens=[item], data_venda=quando, autor="dono", **kw)["venda_id"]


@pytest.fixture
def vendas_de_hoje(salgado, caixa):
    """Venda A: 10 un a 5 reais (custo 6). Venda B: caixa com 25 no atacado por 38 em vez de 40 (custo 16), fiado
    para o João. Venda C: cancelada. Receita 88, custo 22, margem 66 (75%), desconto 2."""
    lote(salgado, 100)
    un = apresentacao(salgado)
    cx = apresentacao(salgado, "caixa com 25", 25, "45", atacado="40", embalagem_id=caixa.id, embalagens=1)
    joao = salvar_cliente(nome="João", autor="dono")["cliente_id"]
    vender(un, 10, forma_pagamento="pix")
    vender(cx, 1, preco="38", tabela="atacado", cliente_id=joao, condicao="a_prazo",
           parcelas=[{"valor": D("38"), "vencimento": dia(30)}])
    c = vender(un, 2, forma_pagamento="dinheiro")
    cancelar_venda(venda_id=c, motivo="cliente desistiu", autor="dono")


@pytest.fixture
def producao_com_desvio(bolinha, atacadao):
    """Bolinha 100 g (100% farinha). Referência: compra a 0,005/g; no estoque, farinha a 0,006/g. Planejadas 10
    (1.000 g previstos); usou 1.100 g; 9 boas, 1 rasgou. Previsto 5, real 6,60."""
    farinha = Item.objects.get(nome="Farinha de trigo")
    comprar(atacadao, farinha, "2", "kg", "10")
    entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("12"), motivo="estoque",
                   autor="dono")
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"]
    [linha] = Producao.objects.get(id=p).linhas.all()
    registrar_peso(linha_id=linha.id, usado=D("1100"), autor="dono")
    concluir_producao(producao_id=p, quantidade_boa=9, perdas=1, perda_motivo="rasgou", estado="resfriado",
                      autor="dono")
    return Producao.objects.get(id=p)


# --- registro e alçada -----------------------------------------------------------------

def test_ferramentas_de_custos_sao_so_leitura():
    nivel = {f.nome: f.nivel for f in REGISTRO}
    assert {n: nivel[n] for n in CUSTOS} == dict.fromkeys(CUSTOS, 0)
    t = ferramentas()
    assert len(t) == 88  # + 11 do Plano 8 (despesas e estudo de preço)
    assert all(t[n].annotations.readOnlyHint for n in CUSTOS)
    # preço, óleo e indiretos não mudam por voz; o sistema não sugere preço (ver_indireto_real só lê)
    assert not {n for n in nivel if any(p in n for p in ("sugerir", "mudar_preco", "oleo"))}
    assert {n for n in nivel if "indireto" in n} == {"ver_indireto_real"} and nivel["ver_indireto_real"] == 0


def test_periodos_falados():
    assert _periodo("esta semana")[0] == "semana"
    assert _periodo("mês passado")[0] == "mes_passado"
    assert _periodo("Últimos 30 dias")[0] == "ultimos_30"
    assert _periodo("semana_passada")[0] == "semana_passada"
    r = chamar("ver_margem", periodo="trimestre")
    assert "Não conheço o período" in r["erro"]
    for f in ("ver_mais_vendidos", "ver_relatorio", "ver_previsto_realizado"):
        assert "erro" in chamar(f, periodo="ano que vem")


# --- custo ------------------------------------------------------------------------------

def test_ver_custo_completo_em_cascata(coxinha_fichada):
    r = chamar("ver_custo", produto="coxinha")
    t = falado(r)
    assert (r["ingredientes"], r["custo_cru"], r["custo_frito"], r["completo"]) == (0.46, 0.56, 0.61, True)
    assert "Custo estimado de uma unidade de Coxinha 50 g, pela última compra de cada ingrediente" in t
    assert "46 centavos de ingredientes, mais 10 centavos de indiretos, o que dá 56 centavos cru" in t
    assert "frito, com 5 centavos de óleo, 61 centavos" in t
    assert "Não inclui perdas da produção, embalagem de venda e tributos e despesas comerciais." in t
    assert [p["preparacao"] for p in r["partes"]] == ["Massa", "Tempero", "Recheio"]


def test_ver_custo_sem_indireto_diz_que_nao_inclui(atacadao):
    farinha = ingrediente("Farinha")
    comprar(atacadao, farinha, "10", "kg", "45")
    massa = preparacao("Massa simples", "10000", [(farinha, "10000")])
    produto("Bolinha", [(massa, "100")], "50", oleo="0.05")
    t = falado(chamar("ver_custo", produto="bolinha"))
    assert "23 centavos de ingredientes cru; frito, com 5 centavos de óleo, 28 centavos" in t
    assert "Não inclui indiretos, perdas da produção" in t


def test_ver_custo_incompleto_nunca_diz_zero(atacadao):
    farinha, queijo = ingrediente("Farinha"), ingrediente("Queijo")
    comprar(atacadao, farinha, "10", "kg", "45")
    entrada_manual(item_id=queijo.id, quantidade=D("1"), unidade="kg", custo_total=D("40"), motivo="doação",
                   autor="dono")  # entrada manual não é referência
    massa = preparacao("Massa de queijo", "1000", [(farinha, "500"), (queijo, "500")])
    produto("Bolinha de queijo", [(massa, "100")], "20")
    r = chamar("ver_custo", produto="bolinha de queijo")
    t = falado(r)
    assert r["completo"] is False and r["ingredientes"] is None and r["custo_cru"] is None
    assert r["faltando"][0]["item"] == "Queijo"
    assert t == ("O custo estimado de Bolinha de queijo 20 g está incompleto: falta o preço de Queijo; nunca foi "
                 "comprado. Sem esse preço não dá para dizer o custo.")
    # a preparação também
    t = falado(chamar("ver_custo", produto="massa de queijo"))
    assert "incompleto: falta o preço de Queijo" in t and "zero" not in t


def test_ver_custo_da_preparacao_e_nome_inexistente_ou_ambiguo(coxinha_fichada, atacadao):
    t = falado(chamar("ver_custo", produto="massa"))
    assert t.startswith("Custo estimado de Massa, pela última compra de cada ingrediente: 30 reais a receita de 10 kg, "
                        "3 reais o quilo.")
    assert "Nenhum produto nem preparação" in chamar("ver_custo", produto="empada")["erro"]
    Item.objects.create(nome="Coxinha 150 g", tipo="produto", unidade_base="un", ficha=coxinha_fichada.ficha,
                        peso_g=D("150"))  # outro tamanho da mesma ficha
    r = chamar("ver_custo", produto="coxinha")
    assert sorted(r["opcoes"]) == ["Coxinha 150 g", "Coxinha 50 g"]


def test_ver_custo_com_ficha_invalida_devolve_o_erro_do_nucleo(atacadao):
    farinha = ingrediente("Farinha")
    comprar(atacadao, farinha, "1", "kg", "5")
    massa = preparacao("Massa", "1000", [(farinha, "1000")])
    produto("Torta", [(massa, "90")], "10")
    assert "somam 90%" in chamar("ver_custo", produto="torta")["erro"]


# --- margem -----------------------------------------------------------------------------

def test_ver_margem_compara_em_pontos(salgado):
    lote(salgado, 100)
    un = apresentacao(salgado)
    vender(un, 10, preco="10", quando=dia(-10))  # 100 de receita, 6 de custo: 94%
    vender(un, 10)  # 50 de receita, 6 de custo: 88%
    r = chamar("ver_margem", periodo="últimos 7 dias")
    t = falado(r)
    assert (r["totais"]["margem_pct"], r["anterior"]["margem_pct"], r["variacao"]["pontos"]) == (88.0, 94.0, -6.0)
    assert t.startswith("Margem estimada nos últimos 7 dias: 88 por cento, 44 reais sobre 50 reais de vendas com "
                        "custo. Em relação aos 7 dias anteriores, caiu 6 pontos; era 94 por cento.")
    assert "Descontos sobre a tabela" not in t  # o preço de 10 foi acima da tabela: não é desconto
    assert "É margem estimada: não inclui tributos sobre a venda" in t
    sem = falado(chamar("ver_margem", periodo="ultimos 7 dias", comparar=False))
    assert "caiu" not in sem and "88 por cento" in sem


def test_ver_margem_com_desconto_por_tabela_e_cliente(vendas_de_hoje):
    r = chamar("ver_margem", periodo="hoje", agrupar="tabela")
    t = falado(r)
    assert (r["totais"]["receita"], r["totais"]["margem"], r["totais"]["desconto"]) == (88, 66, 2)
    assert "Margem estimada hoje: 75 por cento, 66 reais sobre 88 reais de vendas com custo." in t
    assert "Não há margem estimada ontem para comparar." in t
    assert "Descontos sobre a tabela: 2 reais." in t
    assert "Por tabela: varejo, 88 por cento; atacado, 57,9 por cento." in t
    t = falado(chamar("ver_margem", periodo="hoje", agrupar="cliente", comparar=False))
    assert "Por cliente: Sem cliente (balcão), 88 por cento; João, 57,9 por cento." in t
    t = falado(chamar("ver_margem", periodo="ultimos 7 dias", agrupar="dia"))
    assert "Por dia: hoje, 75 por cento." in t


def test_ver_margem_diz_o_que_ficou_fora(salgado):
    pastel = Item.objects.create(nome="Pastel", tipo="produto", unidade_base="un")
    lote(salgado, 10)
    lote(pastel, 10, custo="0")  # entrou sem custo: a venda fica fora da margem
    vender(apresentacao(salgado), 10)
    vender(apresentacao(pastel, preco="4"), 5)
    r = chamar("ver_margem", periodo="hoje")
    t = falado(r)
    assert r["totais"]["fora"] == {"linhas": 1, "receita": 20.0, "motivos": {"custo zero gravado": 1}}
    assert "Margem estimada hoje: 88 por cento, 44 reais sobre 50 reais de vendas com custo." in t
    assert ("1 item de venda, somando 20 reais, ficou fora da margem porque o custo gravado não é confiável: "
            "1 com custo zero gravado.") in t
    assert "Pastel, sem margem estimada (custo não confiável)" in t


def test_ver_margem_sem_vendas(salgado):
    t = falado(chamar("ver_margem", periodo="semana passada"))
    assert t == "Na semana passada não há venda concluída, então não há margem estimada."
    assert "'agrupar'" in chamar("ver_margem", agrupar="cor")["erro"]


def test_ver_margem_tabela(bolinha, atacadao, caixa):
    farinha = Item.objects.get(nome="Farinha de trigo")
    comprar(atacadao, farinha, "2", "kg", "10")  # bolinha 100 g: 50 centavos de farinha
    apresentacao(bolinha, "caixa com 25", 25, "45", atacado="40", embalagem_id=caixa.id, embalagens=1)
    t = falado(chamar("ver_margem_tabela", produto="bolinha"))
    assert ("caixa com 25 de Bolinha 100 g, cru congelado: sem custo estimado, falta o preço de Caixa de papelão; "
            "nunca foi comprado") in t
    comprar(atacadao, caixa, "10", "un", "10")
    r = chamar("ver_margem_tabela")
    t = falado(r)
    [a] = r["apresentacoes"]
    assert (a["custo"], a["margem_varejo_pct"], a["margem_atacado_pct"]) == (13.5, 70.0, 66.3)
    assert ("caixa com 25 de Bolinha 100 g, cru congelado: custo estimado 13 reais e 50 centavos; no varejo, "
            "45 reais, margem estimada de 70 por cento, 31 reais e 50 centavos; no atacado, 40 reais, "
            "66,3 por cento.") in t
    assert "não inclui indiretos" in t
    sem_ficha = Item.objects.create(nome="Empada", tipo="produto", unidade_base="un")
    apresentacao(sem_ficha, preco="6")
    assert "unidade de Empada, cru congelado: sem custo estimado, o produto não tem ficha técnica" in \
        falado(chamar("ver_margem_tabela", produto="empada"))
    assert "Nenhum preço de tabela para 'quibe'" in chamar("ver_margem_tabela", produto="quibe")["erro"]


# --- ranking ----------------------------------------------------------------------------

def test_ver_mais_vendidos(salgado):
    pastel = Item.objects.create(nome="Pastel", tipo="produto", unidade_base="un")
    lote(salgado, 50)
    lote(pastel, 50, custo="2.00")
    vender(apresentacao(salgado), 10)  # receita 50, margem 44
    vender(apresentacao(pastel, preco="4"), 25)  # receita 100, margem 50
    t = falado(chamar("ver_mais_vendidos", periodo="mes"))
    assert t == ("Neste mês, pelo que vendeu em dinheiro: primeiro, Pastel, 100 reais, 66,7 por cento do total; "
                 "segundo, Coxinha 150 g, 50 reais, 33,3 por cento do total.")
    t = falado(chamar("ver_mais_vendidos", periodo="hoje", ordem="unidades"))
    assert t.startswith("Hoje, pelas unidades vendidas: primeiro, Pastel, 25 unidades")
    r = chamar("ver_mais_vendidos", periodo="hoje", ordem="o que dá mais lucro")
    t = falado(r)
    assert r["ordem"] == "margem"
    assert "primeiro, Pastel, 50 reais de margem estimada, 50 por cento" in t and "antes das despesas" in t
    assert falado(chamar("ver_mais_vendidos", periodo="ontem")) == "Ontem não há venda concluída."


# --- previsto × realizado -----------------------------------------------------------------

def test_ver_previsto_realizado_de_uma_producao(producao_com_desvio):
    r = chamar("ver_previsto_realizado", producao_id=producao_com_desvio.id)
    t = falado(r)
    assert (r["custo_previsto"], r["custo_real"], r["desvio_custo"], r["rendimento_pct"]) == (5, 6.6, 1.6, 90)
    p = producao_com_desvio.id
    assert t.startswith(f"Produção {p} de Bolinha 100 g, cru, concluída hoje: planejadas 10 unidades, saíram "
                        "9 boas e 1 perdida (rasgou), rendimento de 90 por cento. Custo previsto 5 reais, real "
                        "6 reais e 60 centavos: 1 real e 60 centavos a mais, 32 por cento acima.")
    assert "Por unidade boa, 73 centavos; o previsto era 50 centavos." in t
    assert "Farinha de trigo, usou 1,1 kg contra 1 kg, 10 por cento a mais." in t
    assert "não existe ou ainda não foi concluída" in chamar("ver_previsto_realizado", producao_id=999)["erro"]


def test_ver_previsto_realizado_do_periodo_com_producao_fora(producao_com_desvio, bolinha):
    p2 = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", pendente_justificativa="chega amanhã",
                          autor="dono")["producao_id"]
    usar_previsto_restantes(producao_id=p2, autor="dono")
    concluir_producao(producao_id=p2, quantidade_boa=10, estado="resfriado", autor="dono")
    r = chamar("ver_previsto_realizado", periodo="hoje", produto="bolinha")
    t = falado(r)
    assert r["fora"] == {"custo_pendente": [p2], "sem_previsto": []}
    assert t.startswith("Hoje, 2 produções concluídas de Bolinha 100 g. Bolinha 100 g: 2 produções, 20 unidades "
                        "planejadas, 19 boas e 1 perdida, rendimento de 95 por cento; custo previsto 5 reais, real "
                        "6 reais e 60 centavos, 1 real e 60 centavos a mais (32 por cento), comparando 1 produção.")
    assert "Ficaram fora da comparação de custo: 1 produção com custo pendente." in t
    assert falado(chamar("ver_previsto_realizado", periodo="ontem")) == "Ontem, nenhuma produção concluída."


def test_producao_sem_compra_nao_tem_previsto(bolinha):
    farinha = Item.objects.get(nome="Farinha de trigo")
    entrada_manual(item_id=farinha.id, quantidade=D("1"), unidade="kg", custo_total=D("6"), motivo="estoque",
                   autor="dono")
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"]
    usar_previsto_restantes(producao_id=p, autor="dono")
    concluir_producao(producao_id=p, quantidade_boa=10, estado="resfriado", autor="dono")
    t = falado(chamar("ver_previsto_realizado", producao_id=p))
    assert "Sem custo previsto: falta o preço de Farinha de trigo; sem compra até a produção." in t


# --- relatório -----------------------------------------------------------------------------

def test_ver_relatorio(vendas_de_hoje):
    r = chamar("ver_relatorio", periodo="hoje")
    t = falado(r)
    assert r["rotulo"] == "estimado" and r["resultado"]["rotulo"] == "estimado"
    assert (r["resultado"]["receita"], r["resultado"]["perdas"], r["resultado"]["resultado"]) == (88, 1.2, 64.8)
    assert t.startswith("Hoje, tudo estimado. Vendas: 2 vendas, 88 reais, com margem estimada "
                        "de 75 por cento. Perdas com valor: 1 real e 20 centavos. Resultado estimado, antes das "
                        "despesas: 64 reais e 80 centavos, 73,6 por cento da receita. Dinheiro anotado: entrou "
                        "60 reais, saiu 10 reais.")
    assert "Hoje, em aberto: a receber 38 reais." in t
    assert "O resultado não desconta despesas, indiretos de fabricação rateados, tributos sobre a venda e ajuste " \
           "de óleo." in t


def test_ver_relatorio_sem_movimento_e_com_ressalva(salgado):
    t = falado(chamar("ver_relatorio", periodo="semana passada"))
    assert "Nenhuma venda concluída." in t and "Resultado estimado" not in t
    assert "O resultado não desconta despesas" in t and "não dá para dizer o resultado depois delas" in t
    pastel = Item.objects.create(nome="Pastel", tipo="produto", unidade_base="un")
    lote(pastel, 10, custo="0")
    vender(apresentacao(pastel, preco="4"), 5)
    r = chamar("ver_relatorio", periodo="mes")
    t = falado(r)
    assert r["ressalvas"] and "Ressalva: 1 linha(s) de venda com custo duvidoso" in t


# --- evolução de preço -------------------------------------------------------------------

def test_ver_evolucao_preco(atacadao):
    farinha = ingrediente("Farinha")
    assert falado(chamar("ver_evolucao_preco", item="farinha")) == \
        "Ainda não há compra de Farinha: não há preço para comparar."
    comprar(atacadao, farinha, "10", "kg", "40", quando=dia(-40))
    t = falado(chamar("ver_evolucao_preco", item="farinha"))
    assert "Só há uma compra de Farinha" in t and "do fornecedor Atacadão, 4 reais o quilo" in t
    comprar(atacadao, farinha, "10", "kg", "45", quando=dia(-20))
    comprar(atacadao, farinha, "10", "kg", "50", quando=dia(-5))
    r = chamar("ver_evolucao_preco", item="farinha")
    t = falado(r)
    assert [c["variacao_pct"] for c in r["compras"]] == [None, 12.5, 11.1]
    assert ("a última compra, " in t and "do fornecedor Atacadão, saiu a 5 reais o quilo; a anterior" in t
            and "a 4 reais e 50 centavos: subiu 11,1 por cento." in t)
    assert "Desde a primeira compra" in t and "a 4 reais, subiu 25 por cento em 3 compras." in t
    assert "Nenhum item com o nome 'chocolate'" in chamar("ver_evolucao_preco", item="chocolate")["erro"]


# --- nenhuma grava ---------------------------------------------------------------------------

def test_nenhuma_ferramenta_de_custos_grava(vendas_de_hoje, producao_com_desvio, atacadao):
    farinha = Item.objects.get(nome="Farinha de trigo")
    antes = (RegistroOperacao.objects.count(), Proposta.objects.count(), Movimento.objects.count())
    textos = [
        chamar("ver_custo", produto="bolinha"), chamar("ver_margem"), chamar("ver_margem", periodo="mes"),
        chamar("ver_margem_tabela"), chamar("ver_mais_vendidos"), chamar("ver_mais_vendidos", ordem="margem"),
        chamar("ver_previsto_realizado"), chamar("ver_previsto_realizado", producao_id=producao_com_desvio.id),
        chamar("ver_relatorio"), chamar("ver_evolucao_preco", item=farinha.nome)]
    assert (RegistroOperacao.objects.count(), Proposta.objects.count(), Movimento.objects.count()) == antes
    for r in textos:
        falado(r)
    # margem sempre "estimada"; resultado sempre "antes das despesas"
    assert all("estimad" in r["texto"] for r in textos[:4])
    assert "antes das despesas" in textos[8]["texto"]
