"""Plano 7, fase 1: custo estimado da ficha, previsto × realizado, margens, comparação de períodos,
margem das apresentações, ranking, evolução de preço e relatório do período. Números conferíveis à mão."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.utils import timezone

from cadastros.models import Fornecedor, Item
from cadastros.servicos import salvar_cliente
from compras.servicos import cancelar_compra, registrar_compra
from custos.consultas import (comparar_margens, evolucao_preco, intervalo, intervalo_anterior, margem_apresentacoes,
                              margem_das_linhas, margens, previsto_realizado, previsto_realizado_producao,
                              ranking_produtos)
from custos.fichas import custo_estimado, custo_preparacao, custos_estimados
from custos.relatorios import relatorio_periodo
from decisoes.consultas import resumo_do_dia
from decisoes.geradores import rodar_rotina
from estoque.models import CriterioValidade, Lote, Movimento
from estoque.servicos import entrada_manual, registrar_perda
from financeiro.consultas import receber_em_aberto
from financeiro.servicos import registrar_recebimento
from fichas.models import ComponenteItem, ComponentePreparacao, Ficha, Proporcao
from nucleo.operacoes import RegraViolada
from producao.models import Producao
from producao.servicos import (concluir_producao, conciliar_consumo, iniciar_producao, registrar_peso,
                               usar_previsto_restantes)
from vendas.servicos import cancelar_venda, registrar_venda, salvar_apresentacao

pytestmark = pytest.mark.django_db

HOJE = timezone.localdate()


def dia(n):
    return HOJE + dt.timedelta(days=n)


@pytest.fixture
def atacadao():
    return Fornecedor.objects.create(nome="Atacadão")


def ingrediente(nome, base="g"):
    return Item.objects.create(nome=nome, tipo="ingrediente", unidade_base=base, controla_validade=False)


def comprar(fornecedor, item, quantidade, unidade, valor, quando=HOJE):
    """Compra à vista de uma linha: o custo unitário (RN-20) vira a referência do item (RN-23)."""
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


# ---------- custo estimado da ficha ----------

def test_ca14_parcela_de_massa_por_coxinha(atacadao):
    farinha, leite = ingrediente("Farinha"), ingrediente("Leite", "mL")
    comprar(atacadao, farinha, "10", "kg", "45")  # R$ 0,0045/g
    comprar(atacadao, leite, "10", "L", "20")  # R$ 0,0020/mL
    # massa de 10 kg com R$ 30,00 de ingredientes (4 kg × 0,0045 + 6 L × 0,002)
    massa = preparacao("Massa", "10000", [(farinha, "4000"), (leite, "6000")])
    assert custo_preparacao(ficha_id=massa.id)["total"] == D("30.0000")
    bolinha = produto("Bolinha", [(massa, "100")], "50", oleo="0.05")  # 0,05 kg de massa por unidade
    c = custo_estimado(produto_id=bolinha.id)
    assert c["ingredientes"] == D("0.1500")
    assert (c["oleo"], c["custo_frito"]) == (D("0.05"), D("0.2000"))
    assert c["indiretos"] is None and c["custo_cru"] == D("0.1500")
    assert any("indiretos" in n for n in c["nao_inclui"])  # óleo e indiretos à parte (RF-CUS-05)


def test_custo_em_cascata_pelas_subpreparacoes(atacadao):
    farinha, leite, frango, alho = ingrediente("Farinha"), ingrediente("Leite", "mL"), ingrediente("Frango"), ingrediente("Alho")
    comprar(atacadao, farinha, "10", "kg", "45")
    comprar(atacadao, leite, "10", "L", "20")
    comprar(atacadao, frango, "5", "kg", "100")  # 0,02/g
    comprar(atacadao, alho, "1", "kg", "50")  # 0,05/g
    massa = preparacao("Massa", "10000", [(farinha, "4000"), (leite, "6000")])  # 0,003/g
    tempero = preparacao("Tempero", "100", [(alho, "100")])  # 0,05/g
    recheio = preparacao("Recheio", "1000", [(frango, "800")], [(tempero, "50")])  # 16 + 2,50 = 18,50 por kg
    assert custo_preparacao(ficha_id=recheio.id)["por_kg"] == D("18.5000")
    coxinha = produto("Coxinha", [(massa, "60"), (recheio, "40")], "50", oleo="0.05", indireto="0.10")
    c = custo_estimado(produto_id=coxinha.id)
    # massa 30 g × 0,003 = 0,09; recheio 20 g: frango 16 g × 0,02 = 0,32 + tempero 1 g × 0,05 = 0,05
    assert [(b["nome"], b["gramas"], b["custo"]) for b in c["blocos"]] == [
        ("Massa", D("30.000"), D("0.0900")), ("Tempero", D("1.000"), D("0.0500")), ("Recheio", D("20.000"), D("0.3200"))]
    assert (c["ingredientes"], c["custo_cru"], c["custo_frito"]) == (D("0.4600"), D("0.5600"), D("0.6100"))
    assert c["completo"] and c["faltando"] == []
    # preço sobe: o estimado muda (RF-FIC-05); a referência de um dia antes da compra nova não muda
    comprar(atacadao, frango, "5", "kg", "125", quando=dia(0))  # 0,025/g
    assert custo_estimado(produto_id=coxinha.id)["ingredientes"] == D("0.5400")
    comprar(atacadao, alho, "1", "kg", "80", quando=dia(-30))  # compra antiga não é a última
    assert custo_estimado(produto_id=coxinha.id)["ingredientes"] == D("0.5400")


def test_item_nunca_comprado_deixa_o_custo_incompleto(atacadao):
    farinha, queijo = ingrediente("Farinha"), ingrediente("Queijo")
    comprar(atacadao, farinha, "10", "kg", "45")
    entrada_manual(item_id=queijo.id, quantidade=D("1"), unidade="kg", custo_total=D("40"), motivo="doação",
                   autor="dono")  # entrada manual não é compra: não vira referência (RN-23)
    massa = preparacao("Massa de queijo", "1000", [(farinha, "500"), (queijo, "500")])
    p = produto("Bolinha de queijo", [(massa, "100")], "20")
    c = custo_estimado(produto_id=p.id)
    assert not c["completo"] and c["ingredientes"] is None and c["custo_cru"] is None
    assert c["ingredientes_conhecido"] == D("0.0450")  # só a farinha: 10 g × 0,0045
    assert c["faltando"] == [{"item_id": queijo.id, "item": "Queijo", "motivo": "nunca comprado"}]
    # compra cancelada não conta como referência
    r = registrar_compra(fornecedor_id=atacadao.id, data_compra=HOJE, total=D("40"), condicao="a_prazo",
                         parcelas=[{"valor": D("40"), "vencimento": dia(30)}], autor="dono",
                         linhas=[{"item_id": queijo.id, "quantidade": D("1"), "unidade": "kg", "valor": D("40")}])
    cancelar_compra(compra_id=r["compra_id"], motivo="lançada errada", autor="dono")
    assert not custo_estimado(produto_id=p.id)["completo"]


def test_ficha_invalida_nao_derruba_a_lista(atacadao):
    farinha = ingrediente("Farinha")
    comprar(atacadao, farinha, "1", "kg", "5")
    massa = preparacao("Massa", "1000", [(farinha, "1000")])
    boa = produto("Bolinha", [(massa, "100")], "10")
    ruim = produto("Torta", [(massa, "90")], "10")  # proporções não somam 100%
    lista = {c["produto_id"]: c for c in custos_estimados()}
    assert lista[boa.id]["ingredientes"] == D("0.0500")
    assert "somam 90%" in lista[ruim.id]["erro"]
    with pytest.raises(RegraViolada, match="Produto não encontrado"):
        custo_estimado(produto_id=farinha.id)


# ---------- previsto × realizado ----------

@pytest.fixture
def producao_com_desvio(bolinha, atacadao):
    """Bolinha 100 g (100% massa; massa = 100% farinha). Referência da farinha: compra a R$ 0,005/g.
    No estoque, farinha de R$ 0,006/g. Planejadas 10 (1.000 g previstos); usou 1.100 g; 9 boas, 1 rasgou."""
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


def test_previsto_realizado_por_producao(producao_com_desvio):
    d = previsto_realizado_producao(producao_com_desvio.id)
    assert (d["unidades"], d["boas"], d["perdas"], d["rendimento_pct"]) == (10, 9, 1, D("90.0"))
    assert (d["custo_previsto"], d["custo_real"]) == (D("5.00"), D("6.60"))  # 1000 × 0,005 × 1100 × 0,006
    assert (d["desvio_custo"], d["desvio_custo_pct"]) == (D("1.60"), D("32.0"))
    assert (d["custo_unitario_previsto"], d["custo_unitario_real"]) == (D("0.5000"), D("0.7333"))
    assert d["desvio_unitario_pct"] == D("46.7")
    [i] = d["itens"]
    assert (i["previsto"], i["usado"], i["desvio_pct"], i["custo_previsto"], i["custo_real"]) == (
        D("1000"), D("1100"), D("10.0"), D("5.00"), D("6.60"))
    assert previsto_realizado_producao(999) is None


def test_previsto_realizado_frito_conta_o_oleo(bolinha, atacadao):
    farinha = Item.objects.get(nome="Farinha de trigo")
    comprar(atacadao, farinha, "2", "kg", "10")
    entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="estoque",
                   autor="dono")
    CriterioValidade.objects.create(produto=bolinha, forma="frito", estado="fresco", dias=1)
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="frito", autor="dono")["producao_id"]
    usar_previsto_restantes(producao_id=p, autor="dono")
    concluir_producao(producao_id=p, quantidade_boa=8, perdas=2, perda_motivo="estourou", estado="fresco",
                      autor="dono")
    d = previsto_realizado_producao(p)
    # farinha 1000 g × 0,005 = 5,00 + óleo 0,05 × 10 fritas = 0,50
    assert (d["custo_previsto"], d["custo_real"], d["oleo_previsto"], d["oleo_real"]) == (
        D("5.50"), D("5.50"), D("0.50"), D("0.50"))
    assert (d["custo_unitario_previsto"], d["custo_unitario_real"]) == (D("0.5500"), D("0.6875"))


def test_custo_pendente_e_sem_referencia_ficam_fora_da_comparacao(producao_com_desvio, bolinha):
    # segunda produção sem farinha bastante: 900 g no estoque, 100 g ficam pendentes
    p2 = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", pendente_justificativa="chega amanhã",
                          autor="dono")["producao_id"]
    usar_previsto_restantes(producao_id=p2, autor="dono")
    concluir_producao(producao_id=p2, quantidade_boa=10, estado="resfriado", autor="dono")
    r = previsto_realizado(de=HOJE, ate=HOJE)
    assert r["fora"] == {"custo_pendente": [p2], "sem_previsto": []}
    [g] = r["por_produto"]
    assert (g["producoes"], g["unidades"], g["boas"], g["perdas"], g["rendimento_pct"]) == (2, 20, 19, 1, D("95.0"))
    # o custo só compara a produção fechada
    assert (g["comparadas"], g["custo_previsto"], g["custo_real"], g["desvio_custo"]) == (
        1, D("5.00"), D("6.60"), D("1.60"))
    assert g["custo_unitario_real"] == D("0.7333")
    assert previsto_realizado(de=dia(1))["producoes"] == []


def test_producao_sem_compra_do_ingrediente_nao_tem_previsto(bolinha):
    farinha = Item.objects.get(nome="Farinha de trigo")
    entrada_manual(item_id=farinha.id, quantidade=D("1"), unidade="kg", custo_total=D("6"), motivo="estoque",
                   autor="dono")
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"]
    usar_previsto_restantes(producao_id=p, autor="dono")
    concluir_producao(producao_id=p, quantidade_boa=10, estado="resfriado", autor="dono")
    d = previsto_realizado_producao(p)
    assert d["custo_previsto"] is None and d["custo_real"] == D("6.00")
    assert d["faltando"][0]["item"] == "Farinha de trigo"
    assert previsto_realizado()["fora"]["sem_previsto"] == [p]


# ---------- margens ----------

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


def lote(produto, n, *, custo="0.60", validade=None, forma="cru", estado="congelado"):
    l = Lote.objects.create(item=produto, forma=forma, validade=validade or dia(30), custo_unitario=D(custo))
    Movimento.objects.create(tipo="entrada_producao", item=produto, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado=estado, validade=l.validade)
    return l


def apresentacao(produto, nome="unidade", unidades=1, preco="5", atacado=None, forma="cru", estado="congelado", **kw):
    return salvar_apresentacao(produto_id=produto.id, nome=nome, forma=forma, estado=estado, unidades=unidades,
                               preco_varejo=D(preco), preco_atacado=atacado and D(atacado), autor="dono",
                               **kw)["apresentacao_id"]


def vender(apr, quantidade, *, preco=None, quando=HOJE, **kw):
    item = {"apresentacao_id": apr, "quantidade": quantidade}
    if preco is not None:
        item["preco"] = D(preco)
    return registrar_venda(itens=[item], data_venda=quando, autor="dono", **kw)["venda_id"]


@pytest.fixture
def vendas_do_mes(salgado, caixa):
    """Venda A: 10 un a R$ 5 (custo 6,00). Venda B: 1 caixa com 25 no atacado com desconto, R$ 38 em vez de
    R$ 40 (custo 25 × 0,60 + caixa 1,00 = 16,00), a prazo para o João. Venda C: cancelada (fora)."""
    lote(salgado, 100)
    un = apresentacao(salgado)
    cx = apresentacao(salgado, "caixa com 25", 25, "45", atacado="40", embalagem_id=caixa.id, embalagens=1)
    joao = salvar_cliente(nome="João", autor="dono")["cliente_id"]
    a = vender(un, 10, forma_pagamento="pix")
    b = vender(cx, 1, preco="38", tabela="atacado", cliente_id=joao, condicao="a_prazo",
               parcelas=[{"valor": D("38"), "vencimento": dia(30)}])
    c = vender(un, 2, forma_pagamento="dinheiro")
    cancelar_venda(venda_id=c, motivo="cliente desistiu", autor="dono")
    return {"a": a, "b": b, "c": c, "joao": joao, "un": un, "cx": cx}


def test_margem_por_produto_tabela_e_cliente_com_desconto(vendas_do_mes, salgado):
    m = margens(de=HOJE, ate=HOJE)
    t = m["totais"]
    assert (t["vendas"], t["receita"], t["receita_tabela"], t["desconto"]) == (2, D("88"), D("90"), D("2"))
    assert (t["custo"], t["margem"], t["margem_pct"]) == (D("22.00"), D("66.00"), D("75.0"))
    assert m["rotulo"] == "estimada" and m["nao_inclui"]  # RF-CUS-06
    [g] = m["grupos"]
    assert (g["nome"], g["unidades"], g["margem"]) == (salgado.nome, 35, D("66.00"))
    tabelas = {g["chave"]: (g["receita"], g["custo"], g["margem_pct"]) for g in margens(agrupar="tabela")["grupos"]}
    assert tabelas == {"varejo": (D("50"), D("6.00"), D("88.0")), "atacado": (D("38"), D("16.00"), D("57.9"))}
    clientes = {g["nome"]: g["margem"] for g in margens(agrupar="cliente")["grupos"]}
    assert clientes == {"Sem cliente (balcão)": D("44.00"), "João": D("22.00")}
    [linha] = margem_das_linhas(venda_id=vendas_do_mes["b"])
    assert (linha["custo_salgado"], linha["custo_embalagem"]) == (D("15.00"), D("1.00"))
    assert (linha["preco_tabela"], linha["preco"], linha["margem_pct"]) == (D("40"), D("38"), D("57.9"))
    assert margens(de=dia(1))["totais"]["margem"] is None  # sem vendas, sem margem
    with pytest.raises(RegraViolada, match="Agrupamento"):
        margens(agrupar="cor")


def test_comparacao_de_periodos_em_pontos(salgado):
    lote(salgado, 100)
    un = apresentacao(salgado)
    vender(un, 10, preco="10", quando=dia(-10))  # receita 100, custo 6: 94,0%
    vender(un, 10, quando=dia(0))  # receita 50, custo 6: 88,0%
    c = comparar_margens(de=dia(-6), ate=HOJE)
    assert (c["de_anterior"], c["ate_anterior"]) == (dia(-13), dia(-7))
    assert (c["atual"]["margem_pct"], c["anterior"]["margem_pct"]) == (D("88.0"), D("94.0"))
    assert c["variacao"]["pontos"] == D("-6.0")  # "sua margem caiu 6 pontos"
    assert (c["variacao"]["receita"], c["variacao"]["receita_pct"]) == (D("-50"), D("-50.0"))
    [g] = c["grupos"]
    assert (g["margem_pct"], g["margem_pct_anterior"], g["pontos"]) == (D("88.0"), D("94.0"), D("-6.0"))
    vazio = comparar_margens(de=dia(1), ate=dia(2))
    assert vazio["variacao"]["pontos"] is None


def test_venda_com_custo_zero_fica_fora_da_margem_e_dentro_da_receita(salgado):
    pastel = Item.objects.create(nome="Pastel", tipo="produto", unidade_base="un")
    lote(salgado, 10)
    lote(pastel, 10, custo="0")  # entrou sem custo
    vender(apresentacao(salgado), 10)
    vender(apresentacao(pastel, preco="4"), 5)
    t = margens()["totais"]
    assert (t["receita"], t["receita_com_custo"], t["custo"], t["margem"], t["margem_pct"]) == (
        D("70"), D("50"), D("6.00"), D("44.00"), D("88.0"))
    assert (t["fora"]["linhas"], t["fora"]["receita"], t["fora"]["motivos"]) == (1, D("20"), {"custo zero gravado": 1})
    grupos = {g["nome"]: g for g in margens()["grupos"]}
    assert grupos["Pastel"]["margem"] is None and grupos["Pastel"]["margem_pct"] is None


def test_venda_de_lote_com_custo_pendente_fica_fora_ate_a_conciliacao(bolinha, atacadao):
    farinha = Item.objects.get(nome="Farinha de trigo")
    entrada_manual(item_id=farinha.id, quantidade=D("500"), unidade="g", custo_total=D("3"), motivo="estoque",
                   autor="dono")
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", pendente_justificativa="chega amanhã",
                         autor="dono")["producao_id"]
    usar_previsto_restantes(producao_id=p, autor="dono")
    concluir_producao(producao_id=p, quantidade_boa=10, estado="resfriado", autor="dono")
    un = apresentacao(bolinha, estado="resfriado", preco="2")
    vender(un, 5)
    assert margens()["totais"]["fora"]["motivos"] == {"custo pendente na produção do lote": 1}
    r = entrada_manual(item_id=farinha.id, quantidade=D("1"), unidade="kg", custo_total=D("6"), motivo="chegou",
                       autor="dono")
    pendente = Producao.objects.get(id=p).consumos_pendentes.get()
    conciliar_consumo(pendente_id=pendente.id, lote_id=r["lote_id"], autor="dono")
    # a venda gravou o custo de antes (RN-30): continua fora, com o motivo
    assert margens()["totais"]["fora"]["motivos"] == {"custo gravado antes da conciliação do consumo pendente": 1}
    vender(un, 5)  # depois da conciliação, a venda nova entra
    t = margens()["totais"]
    assert (t["fora"]["linhas"], t["receita_com_custo"], t["custo"]) == (1, D("10"), D("3.00"))


# ---------- margem estimada das apresentações ----------

def test_margem_estimada_das_apresentacoes_pela_tabela_atual(bolinha, atacadao, caixa):
    farinha = Item.objects.get(nome="Farinha de trigo")
    comprar(atacadao, farinha, "2", "kg", "10")  # bolinha 100 g: R$ 0,50 de farinha por unidade
    cx = apresentacao(bolinha, "caixa com 25", 25, "45", atacado="40", embalagem_id=caixa.id, embalagens=1)
    frita = apresentacao(bolinha, "frita", 1, "3", forma="frito", estado="fresco")
    m = {a["apresentacao_id"]: a for a in margem_apresentacoes()}
    assert not m[cx]["completo"] and m[cx]["custo"] is None  # a caixa de papelão nunca foi comprada
    assert m[cx]["faltando"] == [{"item_id": caixa.id, "item": "Caixa de papelão", "motivo": "nunca comprado"}]
    comprar(atacadao, caixa, "10", "un", "10")
    m = {a["apresentacao_id"]: a for a in margem_apresentacoes()}
    assert (m[cx]["custo_salgado"], m[cx]["custo_embalagem"], m[cx]["custo"]) == (D("12.50"), D("1.00"), D("13.50"))
    assert (m[cx]["margem_varejo"], m[cx]["margem_varejo_pct"]) == (D("31.50"), D("70.0"))
    assert (m[cx]["margem_atacado"], m[cx]["margem_atacado_pct"]) == (D("26.50"), D("66.3"))
    assert (m[frita]["custo"], m[frita]["margem_varejo"], m[frita]["margem_varejo_pct"]) == (
        D("0.55"), D("2.45"), D("81.7"))  # 0,50 + óleo 0,05
    assert m[frita]["margem_atacado"] is None


# ---------- ranking e evolução de preço ----------

def test_ranking_por_receita_e_margem(salgado):
    pastel = Item.objects.create(nome="Pastel", tipo="produto", unidade_base="un")
    lote(salgado, 50)
    lote(pastel, 50, custo="2.00")
    vender(apresentacao(salgado), 10)  # receita 50, margem 44
    vender(apresentacao(pastel, preco="4"), 25)  # receita 100, margem 50
    r = ranking_produtos()
    assert [(p["nome"], p["participacao_pct"], p["acumulado_pct"]) for p in r["produtos"]] == [
        ("Pastel", D("66.7"), D("66.7")), ("Coxinha 150 g", D("33.3"), D("100.0"))]
    r = ranking_produtos(ordem="unidades", limite=1)
    assert [p["nome"] for p in r["produtos"]] == ["Pastel"]
    r = ranking_produtos(ordem="margem")
    assert [(p["nome"], p["margem"]) for p in r["produtos"]] == [("Pastel", D("50.00")), ("Coxinha 150 g", D("44.00"))]


def test_evolucao_de_preco_do_item(atacadao):
    farinha = ingrediente("Farinha")
    comprar(atacadao, farinha, "10", "kg", "45", quando=dia(-20))
    comprar(atacadao, farinha, "10", "kg", "50", quando=dia(-5))
    e = evolucao_preco(item_id=farinha.id)
    assert [(c["custo_unitario"], c["variacao_pct"]) for c in e["compras"]] == [(D("0.0045"), None),
                                                                                (D("0.0050"), D("11.1"))]
    assert e["variacao_pct"] == D("11.1")
    assert [c["variacao_pct"] for c in evolucao_preco(item_id=farinha.id, de=dia(-10))["compras"]] == [None]


# ---------- períodos ----------

def test_intervalos_e_periodo_anterior():
    sexta = dt.date(2026, 11, 13)
    assert intervalo("semana", hoje=sexta) == (dt.date(2026, 11, 9), sexta)
    assert intervalo_anterior("semana", hoje=sexta) == (dt.date(2026, 11, 2), dt.date(2026, 11, 6))
    assert intervalo("mes", hoje=sexta) == (dt.date(2026, 11, 1), sexta)
    assert intervalo_anterior("mes", hoje=sexta) == (dt.date(2026, 10, 1), dt.date(2026, 10, 13))
    assert intervalo_anterior("mes", hoje=dt.date(2026, 3, 31)) == (dt.date(2026, 2, 1), dt.date(2026, 2, 28))
    assert intervalo("mes_passado", hoje=sexta) == (dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    assert intervalo_anterior("mes_passado", hoje=sexta) == (dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert intervalo_anterior("hoje", hoje=sexta) == (dt.date(2026, 11, 12),) * 2
    assert intervalo_anterior("ultimos_7", hoje=sexta) == (dt.date(2026, 10, 31), dt.date(2026, 11, 6))
    with pytest.raises(RegraViolada, match="Período desconhecido"):
        intervalo("trimestre")


# ---------- relatório do período ----------

def test_relatorio_do_periodo(vendas_do_mes, salgado, atacadao):
    farinha = ingrediente("Farinha")
    comprar(atacadao, farinha, "10", "kg", "45")  # à vista: nasce paga (R$ 45 saem)
    l = Lote.objects.get(item=salgado)
    registrar_perda(lote_id=l.id, estado="congelado", quantidade=5, motivo="caiu no chão", autor="dono")  # 3,00
    [parcela] = receber_em_aberto()
    registrar_recebimento(parcela_id=parcela["parcela_id"], valor="20", forma="pix", autor="dono")
    r = relatorio_periodo(de=HOJE, ate=HOJE)
    v = r["vendas"]
    assert (v["totais"]["receita"], v["custo_gravado"], v["canceladas"]["vendas"]) == (D("88"), D("22.00"), 1)
    assert v["por_forma_pagamento"] == {"pix": D("50")}
    assert [g["chave"] for g in v["por_tabela"]] == ["varejo", "atacado"]
    p = r["perdas"]
    assert (p["valor_movimentos"], p["vendas_canceladas"]["valor"], p["valor_total"]) == (D("3.00"), D("1.20"), D("4.20"))
    assert p["por_motivo"][0]["motivo"] == "caiu no chão"
    assert (r["compras"]["compras"], r["compras"]["total"]) == (1, D("45"))
    d = r["dinheiro"]
    # entrou: venda A 50 + venda C 10 (depois devolvida) + recebimento 20; saiu: compra 45 + devolução 10
    assert (d["entrou"], d["saiu"], d["saldo"]) == (D("80"), D("55"), D("25"))
    assert (r["posicao"]["a_receber"], r["posicao"]["a_pagar"]) == (D("18"), D("0"))
    res = r["resultado"]
    assert (res["receita"], res["custo_vendido"], res["perdas"], res["resultado"]) == (
        D("88"), D("22.00"), D("4.20"), D("61.80"))
    assert res["rotulo"] == "estimado" and any("despesas" in n for n in res["nao_inclui"])
    assert r["ressalvas"] == []
    assert relatorio_periodo(de=dia(1), ate=dia(1))["resultado"]["resultado_pct"] is None
    with pytest.raises(RegraViolada, match="vem antes"):
        relatorio_periodo(de=HOJE, ate=dia(-1))


def test_relatorio_conta_a_producao_do_periodo(producao_com_desvio):
    pr = relatorio_periodo(de=HOJE, ate=HOJE)["producao"]
    assert (pr["producoes"], pr["unidades"], pr["boas"], pr["perdas"], pr["custo_real"]) == (1, 10, 9, 1, D("6.60"))
    assert pr["perdas_por_motivo"] == {"rasgou": 1}


# ---------- resumo do dia ----------

def test_operacoes_hoje_nao_conta_a_rotina(atacadao):
    farinha = ingrediente("Farinha")
    comprar(atacadao, farinha, "1", "kg", "5")
    rodar_rotina()
    t = resumo_do_dia()["totais"]
    assert t["operacoes_hoje"] == 1
    assert t["operacoes_rotina_hoje"] > 1
