"""Plano 8, fase 1: despesas (avulsa e mensal), lembretes, resultado depois das despesas, margem com
indiretos, indireto real, estudo e simulação de preço e ponto de equilíbrio. Números conferíveis à mão.

O mês de referência é setembro de 2026 (30 dias): os serviços e consultas recebem `hoje`, então o teste não
depende do dia em que roda."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.utils import timezone

from cadastros.models import Fornecedor, Item
from cadastros.servicos import criar_tamanho, salvar_referencias
from compras.servicos import registrar_compra
from custos.consultas import margem_apresentacoes, margens
from custos.precos import estudo_preco, indireto_real, ponto_equilibrio, simular_preco
from custos.relatorios import relatorio_periodo
from decisoes.consultas import resumo_do_dia
from decisoes.geradores import rodar_rotina
from decisoes.models import Decisao
from estoque.models import Lote, Movimento
from financeiro.consultas import (contas_a_vencer, despesas_do_mes, despesas_em_aberto, despesas_mensais,
                                  despesas_periodo, devido_por_fornecedor, pagamentos)
from financeiro.despesas import (cancelar_despesa, gerar_despesas_do_mes, informar_valor_despesa, lancar_despesa,
                                 pagar_despesa_do_mes, salvar_despesa_mensal, vencimento_no_mes)
from financeiro.models import CategoriaDespesa, Conta, DespesaDoMes
from nucleo.operacoes import RegraViolada
from producao.models import Producao
from producao.servicos import iniciar_producao
from vendas.models import CanalVenda
from vendas.servicos import registrar_venda, salvar_apresentacao, salvar_canal_venda

pytestmark = pytest.mark.django_db

SET = dt.date(2026, 9, 1)


def set_(dia):
    return dt.date(2026, 9, dia)


def cat(nome):
    return CategoriaDespesa.objects.get(nome=nome).id


def mensal(nome, categoria, valor=None, dia=10, hoje=set_(1)):
    r = salvar_despesa_mensal(nome=nome, categoria_id=cat(categoria), dia_vencimento=dia, valor_previsto=valor,
                              hoje=hoje, autor="dono")
    return DespesaDoMes.objects.get(despesa_id=r["despesa_id"], competencia=SET)


@pytest.fixture
def setembro():
    """Mão de obra R$ 2.200 (dia 5), energia R$ 850 previstos (dia 10), internet sem valor (dia 10)."""
    return {"mao": mensal("Funcionário (MEI)", "Mão de obra", "2200", dia=5),
            "luz": mensal("Energia", "Energia", "850"), "net": mensal("Internet", "Internet")}


# ---------- cadastros iniciais ----------

def test_categorias_e_canais_iniciais():
    cats = {c.nome: c.indireta for c in CategoriaDespesa.objects.all()}
    assert cats == {"Mão de obra": True, "Energia": True, "Gás": True, "Diária": True, "Internet": False,
                    "Impostos/MEI": False, "Taxas": False, "Outras": False}
    assert [(c.nome, c.taxa_pct) for c in CanalVenda.objects.all()] == [
        ("Balcão — dinheiro", D("0")), ("Balcão — pix", D("0")), ("Cartão de débito", None),
        ("Cartão de crédito", None)]


# ---------- despesa mensal ----------

def test_despesa_mensal_gera_a_conta_do_mes_uma_unica_vez(setembro):
    assert setembro["net"].conta is None  # sem valor previsto: não vira conta (nem zero)
    luz = setembro["luz"]
    assert (luz.vencimento, luz.conta.total, luz.conta.origem, luz.conta.competencia) == (
        set_(10), D("850.00"), "despesa", SET)
    assert gerar_despesas_do_mes(hoje=set_(20))["criadas"] == []  # já gerada: idempotente
    assert gerar_despesas_do_mes(hoje=set_(20))["criadas"] == []
    r = rodar_rotina(hoje=dt.date(2026, 10, 2))  # virou o mês: a rotina gera outubro
    assert len(r["despesas_do_mes"]["criadas"]) == 3
    rodar_rotina(hoje=dt.date(2026, 10, 2))
    assert DespesaDoMes.objects.count() == 6
    assert Conta.objects.filter(origem="despesa").count() == 4  # energia e mão de obra, 2 meses
    assert vencimento_no_mes(dt.date(2027, 2, 1), 31) == dt.date(2027, 2, 28)
    assert [d["nome"] for d in despesas_mensais()] == ["Energia", "Funcionário (MEI)", "Internet"]
    with pytest.raises(RegraViolada, match="1 a 31"):
        salvar_despesa_mensal(nome="Aluguel", categoria_id=cat("Outras"), dia_vencimento=32, autor="dono")
    with pytest.raises(RegraViolada, match="Já existe"):
        salvar_despesa_mensal(nome="energia", categoria_id=cat("Energia"), autor="dono")


def test_despesa_sem_valor_lembra_sem_duplicar_e_pede_o_valor_ao_pagar(setembro):
    net = setembro["net"]
    rodar_rotina(hoje=set_(7))  # vence em 3 dias e não tem valor
    rodar_rotina(hoje=set_(7))
    [d] = Decisao.objects.filter(origem="despesas_sem_valor", situacao="pendente")
    assert "Internet de 09/2026 vence em 3 dias (10/09) e ainda não tem valor" in d.texto
    assert resumo_do_dia(hoje=set_(7))["totais"]["despesas_sem_valor"] == 1
    rodar_rotina(hoje=set_(12))  # venceu: o aviso muda (o anterior fica sem efeito)
    [d] = Decisao.objects.filter(origem="despesas_sem_valor", situacao="pendente")
    assert "venceu em 10/09 e ainda não tem valor nem pagamento" in d.texto
    with pytest.raises(RegraViolada, match="ainda não tem valor"):
        pagar_despesa_do_mes(despesa_do_mes_id=net.id, autor="dono")
    r = pagar_despesa_do_mes(despesa_do_mes_id=net.id, valor="99.90", data_pagamento=set_(12), forma="pix",
                             autor="dono")
    assert (r["valor"], r["situacao"]) == ("99.90", "paga")  # retorno de serviço vem em JSON
    rodar_rotina(hoje=set_(12))
    assert not Decisao.objects.filter(origem="despesas_sem_valor", situacao="pendente").exists()
    assert resumo_do_dia(hoje=set_(12))["totais"]["despesas_sem_valor"] == 0
    with pytest.raises(RegraViolada, match="já está paga"):
        pagar_despesa_do_mes(despesa_do_mes_id=net.id, autor="dono")


def test_previsto_corrigido_pelo_valor_real_e_lembrete_da_conta(setembro):
    luz = setembro["luz"]
    [p] = [p for p in contas_a_vencer(dias=3, hoje=set_(7)) if p["origem"] == "despesa"]
    assert (p["descricao"], p["categoria"], p["saldo"]) == ("Energia — 09/2026", "Energia", D("850.00"))
    rodar_rotina(hoje=set_(7))  # com valor, o lembrete é o das contas a pagar (um só por parcela)
    assert Decisao.objects.filter(origem="contas_a_vencer", situacao="pendente").count() == 1
    [d] = Decisao.objects.filter(origem="despesas_sem_valor")  # só a internet, que não tem valor
    assert "Internet" in d.texto
    assert devido_por_fornecedor(hoje=set_(7)) == []  # despesa não é fornecedor
    r = pagar_despesa_do_mes(despesa_do_mes_id=luz.id, valor="812.40", data_pagamento=set_(10), autor="dono")
    assert (r["valor"], r["situacao"]) == ("812.40", "paga")
    luz.refresh_from_db()
    assert luz.conta.total == D("812.40")
    with pytest.raises(RegraViolada, match="estorne o pagamento antes"):
        informar_valor_despesa(despesa_do_mes_id=luz.id, valor="800", autor="dono")
    m = despesas_do_mes(competencia=SET, hoje=set_(12))
    assert m["totais"] == {"valor": D("3012.40"), "pago": D("812.40"), "falta_pagar": D("2200.00"),
                           "sem_valor": 1, "completo": False, "vencidas": 2}  # mão de obra e internet


# ---------- despesa avulsa ----------

def test_despesa_avulsa_paga_a_pagar_e_cancelada_com_estorno(setembro):
    r = lancar_despesa(descricao="Diarista no dia de pico", categoria_id=cat("Diária"), valor="150", paga=True,
                       data_pagamento=set_(15), forma="dinheiro", hoje=set_(15), autor="dono")
    assert (r["paga"], r["competencia"], r["parecidas"]) == (True, "2026-09-15", [])
    assert [p["descricao"] for p in pagamentos(de=set_(15), ate=set_(15))] == ["Diarista no dia de pico"]
    with pytest.raises(RegraViolada, match="vencimento"):
        lancar_despesa(descricao="Gás", categoria_id=cat("Gás"), valor="230", hoje=set_(15), autor="dono")
    with pytest.raises(RegraViolada, match="valor da despesa"):
        lancar_despesa(descricao="Gás", categoria_id=cat("Gás"), valor="0", paga=True, autor="dono")
    gas = lancar_despesa(descricao="2 botijões P13", categoria_id=cat("Gás"), valor="230", vencimento=set_(20),
                         hoje=set_(15), autor="dono")
    assert any(p["conta_id"] == gas["conta_id"] for p in despesas_em_aberto(hoje=set_(15))["parcelas"])
    # "paguei a luz" lançado como avulsa: o retorno avisa que a energia do mês ainda está em aberto
    luz = lancar_despesa(descricao="Luz", categoria_id=cat("Energia"), valor="850", paga=True,
                         data_pagamento=set_(10), hoje=set_(10), autor="dono")
    assert [p["despesa"] for p in luz["parecidas"]] == ["Energia"]
    c = cancelar_despesa(conta_id=r["conta_id"], motivo="lançada em dobro", autor="dono")
    assert len(c["pagamentos_estornados"]) == 1
    assert pagamentos(de=set_(15), ate=set_(15)) == []  # o estorno anula, sem apagar
    assert pagamentos(de=set_(15), ate=set_(15), incluir_estornados=True)[0]["estornado"]
    with pytest.raises(RegraViolada, match="já foi cancelada"):
        cancelar_despesa(conta_id=r["conta_id"], motivo="de novo", autor="dono")
    avulsas = {a["descricao"]: a["situacao"] for a in despesas_do_mes(competencia=SET, hoje=set_(15))["avulsas"]}
    assert avulsas == {"Luz": "paga", "Diarista no dia de pico": "cancelada", "2 botijões P13": "aberta"}


# ---------- despesas do período e resultado depois das despesas ----------

def test_despesas_por_competencia_rateadas_no_periodo_parcial(setembro):
    lancar_despesa(descricao="Diarista", categoria_id=cat("Diária"), valor="150", paga=True,
                   data_pagamento=set_(15), hoje=set_(15), autor="dono")
    mes = despesas_periodo(de=SET, ate=set_(30), hoje=dt.date(2026, 10, 1))
    assert (mes["total"], mes["indiretas"], mes["completo"], mes["rateado"]) == (D("3200.00"), D("3200.00"),
                                                                                False, False)
    assert {g["categoria"]: g["valor"] for g in mes["por_categoria"]} == {
        "Mão de obra": D("2200.00"), "Energia": D("850.00"), "Diária": D("150.00")}
    assert mes["faltando"][0]["despesa"] == "Internet"
    assert "Internet sem valor informado em 09/2026" in mes["ressalvas"][0]
    # 1 a 15 de setembro: metade das mensais (15 ÷ 30 dias) + a diária inteira
    q1 = despesas_periodo(de=SET, ate=set_(15), hoje=dt.date(2026, 10, 1))
    assert (q1["total"], q1["rateado"]) == (D("1675.00"), True)  # 1.100 + 425 + 150
    assert any("rateadas pelos dias" in r for r in q1["ressalvas"])
    assert despesas_periodo(de=set_(16), ate=set_(30), hoje=dt.date(2026, 10, 1))["total"] == D("1525.00")


def produto_com_lote(nome, *, indireto=None, custo="0.60", n=100):
    p = Item.objects.create(nome=nome, tipo="produto", unidade_base="un", indireto_ref_un=indireto and D(indireto))
    l = Lote.objects.create(item=p, forma="cru", validade=timezone.localdate() + dt.timedelta(days=30),
                            custo_unitario=D(custo))
    Movimento.objects.create(tipo="entrada_producao", item=p, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado="congelado",
                             validade=l.validade)
    apr = salvar_apresentacao(produto_id=p.id, nome="unidade", forma="cru", estado="congelado", unidades=1,
                              preco_varejo=D("5"), autor="dono")["apresentacao_id"]
    return p, apr


def vender(apr, n, quando):
    return registrar_venda(itens=[{"apresentacao_id": apr, "quantidade": n}], data_venda=quando,
                           forma_pagamento="pix", autor="dono")


def test_resultado_depois_das_despesas_com_despesa_faltando(setembro):
    _, apr = produto_com_lote("Coxinha 150 g", indireto="0.74")
    vender(apr, 10, set_(10))  # receita 50, custo gravado 6,00
    r = relatorio_periodo(de=SET, ate=set_(30), hoje=dt.date(2026, 10, 1))
    assert r["resultado"]["resultado"] == D("44.00")  # o "antes das despesas" não mudou
    dd = r["depois_das_despesas"]
    assert (dd["resultado_antes"], dd["despesas"], dd["resultado"]) == (D("44.00"), D("3050.00"), D("-3006.00"))
    assert not dd["completo"] and dd["rotulo"] == "estimado, faltando despesa sem valor"
    assert [f["despesa"] for f in dd["faltando"]] == ["Internet"]
    assert r["despesas"]["por_categoria"][0]["categoria"] == "Mão de obra"
    assert r["ressalvas"] == []  # as frases das despesas ficam em depois_das_despesas
    informar_valor_despesa(despesa_do_mes_id=setembro["net"].id, valor="99.90", autor="dono")
    dd = relatorio_periodo(de=SET, ate=set_(30), hoje=dt.date(2026, 10, 1))["depois_das_despesas"]
    assert (dd["despesas"], dd["resultado"], dd["completo"]) == (D("3149.90"), D("-3105.90"), True)


# ---------- margem com indiretos ----------

def test_margem_com_indiretos_nas_vendas_sem_mudar_a_margem():
    _, com = produto_com_lote("Coxinha 150 g", indireto="0.74")
    _, sem = produto_com_lote("Kibe 150 g")
    vender(com, 10, set_(10))
    m = margens(de=set_(10), ate=set_(10), agrupar="produto")
    g = {x["nome"]: x for x in m["grupos"]}
    assert (g["Coxinha 150 g"]["margem"], g["Coxinha 150 g"]["margem_pct"]) == (D("44.00"), D("88.0"))
    assert (g["Coxinha 150 g"]["indiretos"], g["Coxinha 150 g"]["margem_com_indiretos"],
            g["Coxinha 150 g"]["margem_com_indiretos_pct"]) == (D("7.40"), D("36.60"), D("73.2"))
    vender(sem, 2, set_(10))
    t = margens(de=set_(10), ate=set_(10))["totais"]
    assert (t["margem"], t["linhas_sem_indireto"], t["margem_com_indiretos"]) == (D("52.80"), 1, None)


def test_margem_cheia_das_apresentacoes_e_referencias(bolinha):
    atacadao = Fornecedor.objects.create(nome="Atacadão")
    farinha = Item.objects.get(nome="Farinha de trigo")
    registrar_compra(fornecedor_id=atacadao.id, data_compra=timezone.localdate(), total=D("10"), condicao="a_vista",
                     linhas=[{"item_id": farinha.id, "quantidade": D("2"), "unidade": "kg", "valor": D("10")}],
                     autor="dono")  # R$ 0,005/g: bolinha 100 g = R$ 0,50
    apr = salvar_apresentacao(produto_id=bolinha.id, nome="unidade", forma="cru", estado="congelado", unidades=1,
                              preco_varejo=D("3"), autor="dono")["apresentacao_id"]
    [a] = margem_apresentacoes()
    assert (a["custo"], a["margem_varejo"], a["indiretos"], a["margem_varejo_com_indiretos"]) == (
        D("0.50"), D("2.50"), None, None)
    with pytest.raises(RegraViolada, match="negativa"):
        salvar_referencias(produto_id=bolinha.id, oleo_ref_un="0.05", indireto_ref_un="-1", autor="dono")
    r = salvar_referencias(produto_id=bolinha.id, oleo_ref_un="0.05", indireto_ref_un="0.74", autor="dono")
    assert r["antes"]["indireto_ref_un"] is None and r["depois"]["indireto_ref_un"] == "0.7400"
    [a] = margem_apresentacoes()
    assert (a["custo"], a["margem_varejo"], a["margem_varejo_pct"]) == (D("0.50"), D("2.50"), D("83.3"))
    assert (a["indiretos"], a["custo_com_indiretos"], a["margem_varejo_com_indiretos"],
            a["margem_varejo_com_indiretos_pct"]) == (D("0.74"), D("1.24"), D("1.76"), D("58.7"))
    # tamanho novo herda o indireto do tamanho mais recente que tem valor
    t = criar_tamanho(ficha_id=bolinha.ficha_id, peso_g=D("150"), autor="dono")
    assert (t["indireto_ref_un"], t["indireto_herdado_de"]["item_id"]) == ("0.7400", bolinha.id)
    t = criar_tamanho(ficha_id=bolinha.ficha_id, peso_g=D("200"), indireto_ref_un=D("0.80"), autor="dono")
    assert (t["indireto_ref_un"], t["indireto_herdado_de"]) == ("0.80", None)
    assert apr == a["apresentacao_id"]


# ---------- estudo de preço, simulação e ponto de equilíbrio ----------

@pytest.fixture
def bolinha_a_5(bolinha):
    """Bolinha 100 g: CMV R$ 0,50 (farinha), indiretos R$ 0,74, vendida a R$ 5,00; cartão de crédito 4%."""
    atacadao = Fornecedor.objects.create(nome="Atacadão")
    farinha = Item.objects.get(nome="Farinha de trigo")
    registrar_compra(fornecedor_id=atacadao.id, data_compra=timezone.localdate(), total=D("10"), condicao="a_vista",
                     linhas=[{"item_id": farinha.id, "quantidade": D("2"), "unidade": "kg", "valor": D("10")}],
                     autor="dono")
    salvar_referencias(produto_id=bolinha.id, oleo_ref_un="0.05", indireto_ref_un="0.74", autor="dono")
    credito = CanalVenda.objects.get(nome="Cartão de crédito")
    salvar_canal_venda(canal_id=credito.id, nome=credito.nome, taxa_pct="4", autor="dono")
    apr = salvar_apresentacao(produto_id=bolinha.id, nome="unidade", forma="cru", estado="congelado", unidades=1,
                              preco_varejo=D("5"), autor="dono")["apresentacao_id"]
    return {"apr": apr, "credito": credito.id, "debito": CanalVenda.objects.get(nome="Cartão de débito").id}


def test_estudo_de_preco_pelo_cmv_por_canal(bolinha_a_5):
    e = estudo_preco()
    [a] = e["apresentacoes"]
    assert (a["preco"], a["cmv"], a["cmv_pct"], a["indiretos"], a["completo"]) == (
        D("5"), D("0.50"), D("10.0"), D("0.74"), True)
    c = {x["canal"]: x for x in a["por_canal"]}
    assert (c["Balcão — dinheiro"]["taxa"], c["Balcão — dinheiro"]["contribuicao"], c["Balcão — dinheiro"]["sobra"],
            c["Balcão — dinheiro"]["sobra_pct"]) == (D("0.00"), D("4.50"), D("3.76"), D("75.2"))
    assert (c["Cartão de crédito"]["taxa"], c["Cartão de crédito"]["sobra"], c["Cartão de crédito"]["sobra_pct"]) == (
        D("0.20"), D("3.56"), D("71.2"))
    assert c["Cartão de débito"]["sobra"] is None and c["Cartão de débito"]["faltando"]  # taxa nunca vira zero
    with pytest.raises(RegraViolada, match="Tabela"):
        estudo_preco(tabela="feira")


def test_simulacao_de_preco_nos_dois_sentidos(bolinha_a_5):
    apr, credito = bolinha_a_5["apr"], bolinha_a_5["credito"]
    s = simular_preco(apresentacao_id=apr, preco="4", canal_id=credito)
    assert s["rotulo"] == "simulação"
    assert (s["taxa"], s["sobra"], s["sobra_pct"], s["preco_atual"]) == (D("0.16"), D("2.60"), D("65.0"), D("5"))
    # para sobrar 50% no crédito: 1,24 ÷ (1 − 0,04 − 0,50) = 2,6956... → R$ 2,70 (taxa 0,11, sobra 1,35)
    s = simular_preco(apresentacao_id=apr, sobra_pct="50", canal_id=credito)
    assert (s["preco"], s["taxa"], s["sobra"], s["sobra_pct"]) == (D("2.70"), D("0.11"), D("1.35"), D("50.0"))
    assert simular_preco(apresentacao_id=apr, sobra_pct="50")["preco"] == D("2.48")  # balcão: 1,24 ÷ 0,5
    with pytest.raises(RegraViolada, match="não foi informada"):
        simular_preco(apresentacao_id=apr, preco="4", canal_id=bolinha_a_5["debito"])
    with pytest.raises(RegraViolada, match="um dos dois"):
        simular_preco(apresentacao_id=apr)
    with pytest.raises(RegraViolada, match="Não existe preço"):
        simular_preco(apresentacao_id=apr, sobra_pct="96", canal_id=credito)


def test_ponto_de_equilibrio_do_mes(bolinha_a_5, setembro):
    p = ponto_equilibrio(apresentacao_id=bolinha_a_5["apr"], competencia=SET, hoje=set_(15))
    # despesas 2.200 + 850 = 3.050 (internet sem valor); contribuição 5 − 0,50 = 4,50 → 677,8 → 678
    assert (p["despesas"], p["contribuicao"], p["apresentacoes"], p["receita"]) == (
        D("3050.00"), D("4.50"), 678, D("3390"))
    assert not p["completo"] and p["faltando"] == ["Internet"]


# ---------- indireto real ----------

def test_indireto_real_do_mes_contra_a_referencia(bolinha_a_5, setembro):
    bolinha = Item.objects.get(nome__startswith="Bolinha")
    lancar_despesa(descricao="2 botijões P13", categoria_id=cat("Gás"), valor="230", paga=True,
                   data_pagamento=set_(8), hoje=set_(8), autor="dono")
    informar_valor_despesa(despesa_do_mes_id=setembro["net"].id, valor="99.90", autor="dono")
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", pendente_justificativa="teste",
                         autor="dono")["producao_id"]
    # a produção do mês inteiro, resumida numa só (4.000 boas encerradas em 10/09)
    Producao.objects.filter(id=p).update(status="concluida", quantidade_boa=4000,
                                         encerrada_em=timezone.make_aware(dt.datetime(2026, 9, 10, 12)))
    r = indireto_real(competencia=SET, hoje=dt.date(2026, 10, 5))
    # indiretas: mão de obra 2.200 + energia 850 + gás 230 = 3.280 ÷ 4.000 = 0,82; com internet 3.379,90
    assert (r["unidades_produzidas"], r["despesas_indiretas"], r["indireto_real_un"]) == (4000, D("3280.00"),
                                                                                         D("0.8200"))
    assert (r["referencia_un"], r["diferenca_un"], r["diferenca_pct"]) == (D("0.7400"), D("0.0800"), D("10.8"))
    assert (r["despesas_total"], r["despesa_total_un"], r["completo"]) == (D("3379.90"), D("0.8450"), True)
    meio = indireto_real(competencia=SET, hoje=set_(15))
    assert meio["ate"] == set_(15) and any("andamento" in x for x in meio["ressalvas"])
