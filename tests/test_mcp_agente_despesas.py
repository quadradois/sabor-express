"""Plano 8, fase 2b: ferramentas do agente de voz para despesas, resultado depois das despesas, margem com
indiretos e estudo de preço.

Leituras não gravam nada; anotar pagamento, lançar e cancelar despesa só gravam depois do "sim"
(`confirmar_proposta`, uma única vez); informar o valor da conta do mês é nível 1. O texto falado traz os números
prontos, dinheiro por extenso e datas faladas: sem "R$", sem "15/11" ou "11/2026", sem "lucro" e nunca "zero"
no lugar de um valor que falta."""

import json
import re
from datetime import timedelta
from decimal import Decimal as D

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone
from mcp.shared.memory import create_connected_server_and_client_session

from agente.compras import dia_falado, mes_falado
from agente.despesas import _competencia, _data
from agente.ferramentas import REGISTRO, criar_servidor
from agente.models import Proposta
from cadastros.models import Fornecedor, Item
from cadastros.servicos import salvar_referencias
from compras.servicos import registrar_compra
from custos.precos import indireto_real
from custos.relatorios import relatorio_periodo
from decisoes.geradores import rodar_rotina
from estoque.models import Lote, Movimento
from financeiro.despesas import lancar_despesa, pagar_despesa_do_mes, salvar_despesa_mensal
from financeiro.models import CategoriaDespesa, Conta, DespesaDoMes, Pagamento, Parcela
from nucleo.models import RegistroOperacao
from producao.models import Producao
from producao.servicos import iniciar_producao
from vendas.models import CanalVenda
from vendas.servicos import registrar_venda, salvar_apresentacao, salvar_canal_venda

pytestmark = pytest.mark.django_db
HOJE = timezone.localdate()
MES = mes_falado(HOJE)
LEITURA = {"ver_despesas", "ver_despesas_a_pagar", "ver_resultado", "ver_indireto_real", "ver_estudo_preco",
           "simular_preco", "ver_ponto_equilibrio"}
NIVEL_2 = {"pagar_despesa", "lancar_despesa", "cancelar_despesa"}


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


def _limpo(t):
    assert "R$" not in t and not re.search(r"\d/\d", t) and "lucro" not in t.lower(), t
    assert not re.search(r"\bzero\b", t), t  # valor que falta nunca vira zero
    return t


def falado(r):
    assert "erro" not in r, r
    return _limpo(r["texto"])


def pergunta(r):
    """Proposta de nível 2: nada gravado, frase terminando em "Confirma?"."""
    assert "erro" not in r, r
    assert r["confirmar"].endswith("Confirma?") and r["proposta_id"]
    return _limpo(r["confirmar"])


def contagem():
    return (RegistroOperacao.objects.filter(status="sucesso").count(), Conta.objects.count(),
            Pagamento.objects.count(), Parcela.objects.count())


# --- cenário --------------------------------------------------------------------------

def cat(nome):
    return CategoriaDespesa.objects.get(nome=nome).id


def mensal(nome, categoria, valor=None):
    r = salvar_despesa_mensal(nome=nome, categoria_id=cat(categoria), valor_previsto=valor, autor="dono")
    return DespesaDoMes.objects.get(despesa_id=r["despesa_id"], competencia=HOJE.replace(day=1))


def vence(dm, dias):
    """Muda o vencimento da despesa do mês (e da parcela, se houver) para hoje + `dias`."""
    d = HOJE + timedelta(days=dias)
    DespesaDoMes.objects.filter(id=dm.id).update(vencimento=d)
    if dm.conta_id:
        Parcela.objects.filter(conta_id=dm.conta_id).update(vencimento=d)
    return d


@pytest.fixture
def mes():
    """Funcionário R$ 2.200 (vence em 5 dias), Energia R$ 850 prevista (venceu há 3 dias), Internet sem valor
    (vence em 2 dias)."""
    m = {"mao": mensal("Funcionário (MEI)", "Mão de obra", "2200"), "luz": mensal("Energia", "Energia", "850"),
         "net": mensal("Internet", "Internet")}
    vence(m["mao"], 5)
    vence(m["luz"], -3)
    vence(m["net"], 2)
    return {k: DespesaDoMes.objects.get(id=v.id) for k, v in m.items()}


@pytest.fixture
def bolinha_a_5(bolinha):
    """Bolinha 100 g: CMV R$ 0,50 (farinha), indiretos R$ 0,74, vendida a R$ 5,00; cartão de crédito 4%."""
    atacadao = Fornecedor.objects.create(nome="Atacadão")
    farinha = Item.objects.get(nome="Farinha de trigo")
    registrar_compra(fornecedor_id=atacadao.id, data_compra=HOJE, total=D("10"), condicao="a_vista",
                     linhas=[{"item_id": farinha.id, "quantidade": D("2"), "unidade": "kg", "valor": D("10")}],
                     autor="dono")
    salvar_referencias(produto_id=bolinha.id, oleo_ref_un="0.05", indireto_ref_un="0.74", autor="dono")
    credito = CanalVenda.objects.get(nome="Cartão de crédito")
    salvar_canal_venda(canal_id=credito.id, nome=credito.nome, taxa_pct="4", autor="dono")
    return salvar_apresentacao(produto_id=bolinha.id, nome="unidade", forma="cru", estado="congelado", unidades=1,
                               preco_varejo=D("5"), autor="dono")["apresentacao_id"]


def vender(bolinha, apr, n):
    l = Lote.objects.create(item=bolinha, forma="cru", validade=HOJE + timedelta(days=30), custo_unitario=D("0.50"))
    Movimento.objects.create(tipo="entrada_producao", item=bolinha, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado="congelado", validade=l.validade)
    return registrar_venda(itens=[{"apresentacao_id": apr, "quantidade": n}], data_venda=HOJE,
                           forma_pagamento="dinheiro", autor="dono")


# --- registro e alçada ---------------------------------------------------------------------

def test_registro_e_alcada_das_ferramentas_de_despesas():
    nivel = {f.nome: f.nivel for f in REGISTRO}
    assert {n: nivel[n] for n in LEITURA} == dict.fromkeys(LEITURA, 0)
    assert nivel["informar_valor_despesa"] == 1
    assert {n: nivel[n] for n in NIVEL_2} == dict.fromkeys(NIVEL_2, 2)
    t = ferramentas()
    assert len(t) == len(REGISTRO) == 95  # 77 até o Plano 7 + 11 do Plano 8 + 4 de lotes (Plano 9)
    assert all(t[n].annotations.readOnlyHint for n in LEITURA)
    # por voz não se cria despesa mensal, categoria, canal, taxa, referência nem preço
    proibidas = ("despesa_mensal", "categoria", "canal", "taxa", "referencia", "mudar_preco", "salvar_preco",
                 "gravar_preco", "indireto_ref")
    assert not {n for n in nivel if any(p in n for p in proibidas)}
    assert "simulação" in t["simular_preco"].description.lower() or "SIMULAÇÃO" in t["simular_preco"].description


def test_mes_e_datas_faladas():
    este = HOJE.replace(day=1)
    assert _competencia("") == _competencia("este mês") == _competencia("mes") == este
    assert _competencia("mês passado") == (este - timedelta(days=1)).replace(day=1)
    assert _competencia("2026-10") == HOJE.replace(year=2026, month=10, day=1)
    outubro = _competencia("outubro")
    assert outubro.month == 10 and outubro <= este
    assert _data("hoje", "x", passado=True) == HOJE
    assert _data("ontem", "x", passado=True) == HOJE - timedelta(days=1)
    assert _data(HOJE.isoformat(), "x", passado=False) == HOJE
    d = _data(f"dia {HOJE.day}", "vencimento", passado=False)
    assert d == HOJE
    assert "Não conheço o mês" in chamar("ver_despesas", mes="trimestre")["erro"]


# --- ver_despesas e ver_despesas_a_pagar ------------------------------------------------------

def test_ver_despesas_do_mes(mes):
    lancar_despesa(descricao="2 botijões", categoria_id=cat("Gás"), valor="230", paga=True, autor="dono")
    r = chamar("ver_despesas")
    t = falado(r)
    assert r["totais"] == {"valor": 3280.0, "pago": 230.0, "falta_pagar": 3050.0, "sem_valor": 1,
                           "completo": False, "vencidas": 1}
    assert t.startswith(f"Despesas de {MES}: 3.280 reais lançados, 230 reais já com pagamento anotado, falta "
                        "pagar 3.050 reais.")
    assert "Ainda sem valor, fora da conta: Internet; quando a conta chegar, é só dizer o valor." in t
    assert f"Vencidas: Energia, 850 reais, venceu {dia_falado(HOJE - timedelta(days=3))}." in t
    assert f"A pagar: Funcionário (MEI), 2.200 reais, vence {dia_falado(HOJE + timedelta(days=5))}." in t
    assert "Por categoria: Mão de obra, 2.200 reais; Energia, 850 reais; Gás, 230 reais." in t
    internet = [d for d in r["despesas"] if d["nome"] == "Internet"][0]
    assert internet["valor"] is None and internet["situacao"] == "sem_valor"  # nunca zero


def test_ver_despesas_sem_nada_e_de_outro_mes():
    t = falado(chamar("ver_despesas"))
    assert t == (f"Nenhuma despesa lançada em {MES}. Não há despesa mensal cadastrada; as contas que se repetem se "
                 "cadastram pela tela.")
    passado = mes_falado((HOJE.replace(day=1) - timedelta(days=1)))
    assert falado(chamar("ver_despesas", mes="mês passado")).startswith(f"Nenhuma despesa lançada em {passado}.")


def test_ver_despesas_a_pagar(mes):
    r = chamar("ver_despesas_a_pagar")
    t = falado(r)
    assert t.startswith("Falta pagar 3.050 reais de despesas, 850 reais já vencidos. Sem valor ainda, fora da "
                        f"soma: Internet de {MES}.")
    assert f"Energia de {MES}, 850 reais, venceu {dia_falado(HOJE - timedelta(days=3))}" in t
    assert [d["rotulo"] for d in r["despesas"]] == [f"Energia de {MES}", f"Internet de {MES}",
                                                    f"Funcionário (MEI) de {MES}"]
    t = falado(chamar("ver_despesas_a_pagar", situacao="vencidas"))
    assert t.startswith("1 despesa vencida, somando 850 reais.")
    vence(mes["luz"], 1)
    assert falado(chamar("ver_despesas_a_pagar", situacao="vencidas")) == "Nenhuma despesa vencida."
    assert "'situacao'" in chamar("ver_despesas_a_pagar", situacao="amanhã")["erro"]


# --- pagar_despesa ------------------------------------------------------------------------------

def test_paguei_850_de_luz_anota_na_despesa_do_mes_so_depois_do_sim(mes):
    antes = contagem()
    r = chamar("pagar_despesa", nome="luz", valor=850)
    assert pergunta(r) == f"Anotar o pagamento de Energia de {MES}: 850 reais, paga hoje. Fica quitada. Confirma?"
    assert contagem() == antes  # proposta não grava
    feito = chamar("confirmar_proposta", proposta_id=r["proposta_id"])
    assert feito["dito"].startswith(f"Feito: Anotar o pagamento de Energia de {MES}")
    assert Pagamento.objects.filter(parcela__conta_id=mes["luz"].conta_id).count() == 1
    chamar("confirmar_proposta", proposta_id=r["proposta_id"])  # confirmar de novo não duplica
    assert Pagamento.objects.filter(parcela__conta_id=mes["luz"].conta_id).count() == 1
    # já paga: não anota de novo nem vira despesa avulsa em dobro
    r = chamar("pagar_despesa", nome="conta de luz", valor=850)
    assert "Energia de " in r["erro"] and "já está com pagamento anotado (850 reais)" in r["erro"]


def test_pagar_com_valor_real_diferente_do_previsto_e_ontem_no_pix(mes):
    r = chamar("pagar_despesa", nome="energia", valor="812.40", data_pagamento="ontem", forma="pix")
    assert pergunta(r) == (f"Anotar o pagamento de Energia de {MES}: 812 reais e 40 centavos, paga ontem, no pix "
                           "(estava lançada com 850 reais; fica o valor real). Fica quitada. Confirma?")
    chamar("confirmar_proposta", proposta_id=r["proposta_id"])
    c = Conta.objects.get(id=mes["luz"].conta_id)
    pg = Pagamento.objects.get(parcela__conta=c)
    assert (c.total, pg.valor, pg.data, pg.forma) == (D("812.40"), D("812.40"), HOJE - timedelta(days=1), "pix")
    assert "ainda não chegou" in chamar("pagar_despesa", nome="internet", valor=99,
                                        data_pagamento=(HOJE + timedelta(days=1)).isoformat())["erro"]


def test_pagar_despesa_sem_valor_pede_o_valor_e_nunca_usa_zero(mes):
    r = chamar("pagar_despesa", nome="internet")
    assert r["erro"] == f"Internet de {MES} ainda não tem valor: pergunte quanto foi pago."
    assert "maior que zero" in chamar("pagar_despesa", nome="internet", valor=-5)["erro"]
    r = chamar("pagar_despesa", nome="internet", valor="99.90")
    assert pergunta(r) == (f"Anotar o pagamento de Internet de {MES}: 99 reais e 90 centavos, paga hoje (ela ainda "
                           "não tinha valor; fica este). Fica quitada. Confirma?")
    assert DespesaDoMes.objects.get(id=mes["net"].id).conta is None  # a simulação não deixou rastro
    chamar("confirmar_proposta", proposta_id=r["proposta_id"])
    dm = DespesaDoMes.objects.get(id=mes["net"].id)
    assert dm.conta.total == D("99.90") and Pagamento.objects.filter(parcela__conta=dm.conta).count() == 1


def test_pagar_despesa_ambigua_pergunta_qual():
    mensal("Gás da cozinha", "Gás", "115")
    mensal("Gás do forno", "Gás", "115")
    r = chamar("pagar_despesa", nome="gás", valor=115)
    assert "Mais de uma despesa em aberto com 'gás'" in r["erro"]
    assert sorted(o.split(",")[0] for o in r["opcoes"]) == [f"Gás da cozinha de {MES}", f"Gás do forno de {MES}"]
    assert not Proposta.objects.exists()
    r = chamar("pagar_despesa", nome="gás do forno", valor=115)
    assert pergunta(r).startswith(f"Anotar o pagamento de Gás do forno de {MES}: 115 reais")


def test_pagar_sem_despesa_do_mes_vira_despesa_avulsa_paga():
    r = chamar("pagar_despesa", nome="diarista", valor=120)
    assert pergunta(r) == "Lançar a despesa Diarista, em Diária: 120 reais, paga hoje. Confirma?"
    antes = Conta.objects.count()
    chamar("confirmar_proposta", proposta_id=r["proposta_id"])
    c = Conta.objects.get(origem="despesa", descricao="Diarista")
    assert Conta.objects.count() == antes + 1 and c.categoria.nome == "Diária" and c.competencia == HOJE
    assert Pagamento.objects.get(parcela__conta=c).valor == D("120")
    # sem valor: pergunta quanto; sem categoria reconhecível: pergunta qual, com as opções
    assert chamar("pagar_despesa", nome="dedetização")["erro"] == "Quanto foi pago de dedetização? Diga o valor."
    r = chamar("pagar_despesa", nome="dedetização", valor=150)
    assert "De que categoria" in r["erro"] and "Outras" in r["opcoes"]
    r = chamar("pagar_despesa", nome="dedetização", valor=150, categoria="outras")
    assert pergunta(r) == "Lançar a despesa Dedetização, em Outras: 150 reais, paga hoje. Confirma?"


# --- lancar_despesa ------------------------------------------------------------------------------

def test_lancar_despesa_a_pagar_e_depois_anotar_o_pagamento(mes):
    venc = HOJE + timedelta(days=10)
    r = chamar("lancar_despesa", descricao="boleto do gás", valor=230, vencimento=venc.isoformat())
    assert pergunta(r) == f"Lançar a despesa Boleto do gás, em Gás: 230 reais, a pagar, vence {dia_falado(venc)}. Confirma?"
    assert "Quando vence?" in chamar("lancar_despesa", descricao="gás", valor=230)["erro"]
    assert "Diga o valor" in chamar("lancar_despesa", descricao="gás", valor=0, vencimento=venc.isoformat())["erro"]
    chamar("confirmar_proposta", proposta_id=r["proposta_id"])
    c = Conta.objects.get(descricao="Boleto do gás")
    assert (c.total, c.parcelas.get().vencimento, Pagamento.objects.filter(parcela__conta=c).count()) == (
        D("230"), venc, 0)
    # "paguei o gás" acha a avulsa a pagar e anota o pagamento nela (não lança outra)
    r = chamar("pagar_despesa", nome="gás")
    assert pergunta(r) == "Anotar o pagamento da despesa Boleto do gás: 230 reais, paga hoje. Fica quitada. Confirma?"
    assert "passa disso" in chamar("pagar_despesa", nome="gás", valor=300)["erro"]
    chamar("confirmar_proposta", proposta_id=r["proposta_id"])
    assert Pagamento.objects.get(parcela__conta=c).valor == D("230")


def test_lancar_despesa_que_ja_e_mensal_nao_lanca_em_dobro(mes):
    r = chamar("lancar_despesa", descricao="internet", valor="99.90", vencimento=HOJE.isoformat())
    assert f"Internet de {MES} já é uma despesa mensal, sem valor" in r["erro"]
    assert "informar_valor_despesa" in r["erro"]
    r = chamar("lancar_despesa", descricao="conta de luz", valor=850, paga=True)
    assert "Energia de " in r["erro"] and "pagar_despesa" in r["erro"]
    assert not Proposta.objects.exists()


# --- informar_valor_despesa (nível 1) -------------------------------------------------------------

def test_informar_valor_despesa(mes):
    r = chamar("informar_valor_despesa", nome="internet", valor="99.90")
    assert r["dito"] == (f"Anotado: Internet de {MES} veio 99 reais e 90 centavos. Vence "
                         f"{dia_falado(HOJE + timedelta(days=2))}, ainda sem pagamento anotado.")
    _limpo(r["dito"])
    dm = DespesaDoMes.objects.get(id=mes["net"].id)
    assert dm.conta.total == D("99.90") and not Pagamento.objects.filter(parcela__conta=dm.conta).exists()
    again = chamar("informar_valor_despesa", nome="internet", valor="99.90")  # repetição na janela não grava de novo
    assert again["repetida"] is True
    assert RegistroOperacao.objects.filter(nome="informar_valor_despesa", status="sucesso").count() == 1
    r = chamar("informar_valor_despesa", nome="luz", valor="812.40")
    assert r["dito"].startswith(f"Anotado: Energia de {MES} veio 812 reais e 40 centavos; estava lançada com "
                                "850 reais. Venceu ")
    assert Conta.objects.get(id=mes["luz"].conta_id).total == D("812.40")
    pagar_despesa_do_mes(despesa_do_mes_id=mes["luz"].id, autor="dono")
    assert "estorne o pagamento antes" in chamar("informar_valor_despesa", nome="energia", valor=800)["erro"]
    assert "Nenhuma despesa mensal em aberto com 'aluguel'" in \
        chamar("informar_valor_despesa", nome="aluguel", valor=1000)["erro"]
    assert "Diga o valor" in chamar("informar_valor_despesa", nome="internet", valor=0)["erro"]


# --- cancelar_despesa -----------------------------------------------------------------------------

def test_cancelar_despesa_com_motivo_estorna_o_pagamento(mes):
    pagar_despesa_do_mes(despesa_do_mes_id=mes["luz"].id, autor="dono")
    assert "motivo é obrigatório" in chamar("cancelar_despesa", nome="luz", motivo="")["erro"]
    r = chamar("cancelar_despesa", nome="luz", motivo="lancei errado")
    assert pergunta(r) == (f"Cancelar a despesa Energia de {MES}, 850 reais (motivo: lancei errado). O pagamento "
                           "anotado de 850 reais é estornado junto. Ela sai das contas a pagar e do resultado. "
                           "Confirma?")
    assert not Conta.objects.get(id=mes["luz"].conta_id).cancelada
    chamar("confirmar_proposta", proposta_id=r["proposta_id"])
    c = Conta.objects.get(id=mes["luz"].conta_id)
    assert c.cancelada and c.motivo_cancelamento == "lancei errado"
    assert Pagamento.objects.get(parcela__conta=c).estorno_operacao_id is not None
    assert "Nenhuma despesa com 'luz'" in chamar("cancelar_despesa", nome="luz", motivo="de novo")["erro"]
    # sem valor não tem conta para cancelar; nome inexistente; avulsa pelo número
    assert "ainda não tem valor" in chamar("cancelar_despesa", nome="internet", motivo="não teve")["erro"]
    a = lancar_despesa(descricao="Diarista", categoria_id=cat("Diária"), valor="100", paga=True, autor="dono")
    lancar_despesa(descricao="Diarista", categoria_id=cat("Diária"), valor="120", paga=True, autor="dono")
    r = chamar("cancelar_despesa", nome="diarista", motivo="lancei duas vezes")
    assert "Mais de uma despesa com 'diarista'" in r["erro"] and len(r["opcoes"]) == 2
    r = chamar("cancelar_despesa", conta_id=a["conta_id"], motivo="lancei duas vezes")
    assert pergunta(r).startswith("Cancelar a despesa Diarista, 100 reais (motivo: lancei duas vezes)")


# --- propostas: expira e recusa ---------------------------------------------------------------------

def test_proposta_de_despesa_expira_ou_e_recusada_sem_gravar(mes):
    antes = contagem()
    r = chamar("pagar_despesa", nome="luz", valor=850)
    Proposta.objects.filter(id=r["proposta_id"]).update(expira_em=timezone.now() - timedelta(seconds=1))
    assert "expirou" in chamar("confirmar_proposta", proposta_id=r["proposta_id"])["erro"]
    r = chamar("lancar_despesa", descricao="conserto da fritadeira", valor=300, categoria="outras", paga=True)
    assert chamar("recusar_proposta", proposta_id=r["proposta_id"])["dito"].startswith("Certo, não gravei nada")
    assert "recusada" in chamar("confirmar_proposta", proposta_id=r["proposta_id"])["erro"]
    assert contagem() == antes


# --- resultado depois das despesas e relatório ---------------------------------------------------

def test_ver_resultado_e_relatorio_depois_das_despesas(mes, bolinha_a_5, bolinha):
    vender(bolinha, bolinha_a_5, 1000)  # 5.000 de receita
    de = HOJE.replace(day=1)
    rel = relatorio_periodo(de=de, ate=HOJE)
    dd = rel["depois_das_despesas"]
    r = chamar("ver_resultado", periodo="mes")
    t = falado(r)
    assert "tudo estimado" in t and "Resultado antes das despesas: " in t
    assert "Resultado estimado depois das despesas: " in t
    assert r["depois_das_despesas"]["resultado"] == float(dd["resultado"])
    assert f"Ainda incompleto: falta o valor de Internet de {MES}; o resultado de verdade é menor que este." in t
    assert "Ainda sem pagamento anotado, pelo valor lançado: Energia e Funcionário (MEI)." in t
    assert "Por categoria: Mão de obra" in t
    rel_t = falado(chamar("ver_relatorio", periodo="mes"))
    assert "Resultado estimado, antes das despesas:" in rel_t and "Resultado estimado depois das despesas" in rel_t
    assert f"falta o valor de Internet de {MES}" in rel_t


def test_resultado_sem_despesa_lancada_nao_inventa_numero():
    t = falado(chamar("ver_resultado", periodo="hoje"))
    assert "Nenhuma despesa lançada no período: sem as despesas, não dá para dizer o resultado depois delas." in t
    assert "Resultado estimado depois" not in t


# --- margem com indiretos -------------------------------------------------------------------------

def test_margem_com_indiretos_e_dita_como_outra_margem(bolinha_a_5, bolinha):
    vender(bolinha, bolinha_a_5, 10)  # receita 50, custo 5, indiretos 7,40
    r = chamar("ver_margem", periodo="hoje", comparar=False)
    t = falado(r)
    assert "Margem estimada hoje: 90 por cento, 45 reais sobre 50 reais de vendas com custo." in t
    assert ("Com os indiretos de referência por salgado (mão de obra, energia e gás), a margem estimada fica em "
            "75,2 por cento, 37 reais e 60 centavos.") in t
    assert r["totais"]["margem_com_indiretos"] == 37.6
    t = falado(chamar("ver_margem_tabela", produto="bolinha"))
    assert ("com os indiretos de referência, 74 centavos, a margem estimada no varejo fica em 75,2 por cento") in t
    assert "A margem com indiretos é outra" in t


# --- estudo de preço, simulação, ponto de equilíbrio ------------------------------------------------

def test_ver_estudo_preco_por_canal(bolinha_a_5):
    r = chamar("ver_estudo_preco", produto="bolinha")
    t = falado(r)
    assert t.startswith("unidade de Bolinha 100 g, cru, a 5 reais: CMV de 50 centavos, 10 por cento do preço; "
                        "indiretos de referência, 74 centavos. No balcão, dinheiro e balcão, pix, sobram 3 reais e "
                        "76 centavos, 75,2 por cento do preço; no cartão de débito, taxa não informada, sem conta; "
                        "no cartão de crédito, sobram 3 reais e 56 centavos, 71,2 por cento do preço, já descontada a "
                        "taxa de 20 centavos.")
    assert t.endswith("o preço da tabela não muda.")
    t = falado(chamar("ver_estudo_preco", produto="bolinha", canal="crédito"))
    assert "No cartão de crédito, sobram" in t and "balcão" not in t
    assert "Nenhum preço de tabela para 'quibe'" in chamar("ver_estudo_preco", produto="quibe")["erro"]


def test_simular_preco_nos_dois_sentidos_sem_gravar(bolinha_a_5):
    antes = (contagem(), Proposta.objects.count())
    r = chamar("simular_preco", produto="bolinha", preco=8)
    t = falado(r)
    assert r["rotulo"] == "simulação" and r["sobra"] == 6.76
    assert t.startswith("Simulação, o preço da tabela não muda: unidade de Bolinha 100 g, cru a 8 reais no balcão, "
                        "dinheiro. CMV de 50 centavos, 6,3 por cento do preço; indiretos de referência, 74 centavos; "
                        "sobram 6 reais e 76 centavos, 84,5 por cento do preço.")
    assert "Hoje a tabela está em 5 reais: este preço fica 3 reais acima." in t
    assert t.endswith("É só uma simulação: o preço só muda pela tela, e quem decide é o dono.")
    # o dono diz a sobra; o sistema calcula o preço: 1,24 ÷ 0,70 = 1,7714 → 1,77
    r = chamar("simular_preco", produto="bolinha", sobra_pct=30)
    t = falado(r)
    assert r["preco"] == 1.77 and r["sobra_pct_pedida"] == 30
    assert ("para sobrar 30 por cento do preço no balcão, dinheiro, o sistema calcula unidade de Bolinha 100 g, cru "
            "a 1 real e 77 centavos.") in t
    assert "este preço fica 3 reais e 23 centavos abaixo." in t
    r = chamar("simular_preco", produto="bolinha", preco=4, canal="crédito")
    assert "taxa do canal, 16 centavos" in falado(r)
    assert "não foi informada" in chamar("simular_preco", produto="bolinha", preco=4, canal="débito")["erro"]
    assert "um dos dois" in chamar("simular_preco", produto="bolinha")["erro"]
    assert "Mais de um canal" in chamar("simular_preco", produto="bolinha", preco=4, canal="cartão")["erro"]
    assert (contagem(), Proposta.objects.count()) == antes


def test_ver_ponto_equilibrio(bolinha_a_5, mes):
    r = chamar("ver_ponto_equilibrio", produto="bolinha")
    t = falado(r)
    # despesas com valor 2.200 + 850 = 3.050 (internet sem valor); cada venda deixa 4,50 → 677,8 → 678
    assert (r["despesas"], r["contribuicao"], r["apresentacoes"], r["receita"]) == (3050, 4.5, 678, 3390)
    assert ("cada venda deixa 4 reais e 50 centavos depois do CMV e da taxa; as despesas de "
            f"{MES} somam 3.050 reais. Para pagar as despesas, seria preciso vender 678 unidades, 3.390 reais de "
            "vendas no mês.") in t
    assert t.endswith("Ficou fora, sem valor: Internet; com ela o número é maior.")


def test_ver_indireto_real_os_74_centavos(bolinha_a_5, bolinha, mes):
    t = falado(chamar("ver_indireto_real"))
    assert "nenhuma produção concluída" in t and t.endswith("É estimado.")
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", pendente_justificativa="teste",
                         autor="dono")["producao_id"]
    Producao.objects.filter(id=p).update(status="concluida", quantidade_boa=4000, encerrada_em=timezone.now())
    r = chamar("ver_indireto_real")
    t = falado(r)
    real = indireto_real()
    assert r["indireto_real_un"] == float(real["indireto_real_un"]) and r["referencia_un"] == 0.74
    assert "4000 unidades boas produzidas" in t and "a referência cadastrada é 74 centavos" in t
    assert f"Incompleto: falta o valor de Internet de {MES}; o real pode ser maior." in t


def test_ver_indireto_real_sem_despesa_nao_diz_zero(bolinha_a_5, bolinha):
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", pendente_justificativa="teste",
                         autor="dono")["producao_id"]
    Producao.objects.filter(id=p).update(status="concluida", quantidade_boa=4000, encerrada_em=timezone.now())
    t = falado(chamar("ver_indireto_real"))
    assert "nenhuma despesa da produção lançada" in t and "não dá para conferir" in t
    assert "a referência cadastrada é 74 centavos" in t and "zero" not in t and "abaixo" not in t


# --- resumo do dia, caixa de decisões e contas ------------------------------------------------------

def test_resumo_do_dia_e_caixa_falam_as_despesas_sem_duplicar(mes):
    vencida = mensal("Água", "Outras")
    vence(vencida, -2)
    r = chamar("ver_resumo_do_dia")
    textos = {a["assunto"]: a["texto"] for a in r["assuntos"]}
    _limpo(r["texto"])
    assert textos["despesas_sem_valor_vencidas"] == (
        f"1 despesa do mês venceu sem valor nem pagamento anotado: Água de {MES}, "
        f"{dia_falado(HOJE - timedelta(days=2))}. Se já pagou, diga quanto foi.")
    assert textos["despesas_sem_valor"] == (
        f"1 despesa do mês vence logo e ainda sem valor: Internet, {dia_falado(HOJE + timedelta(days=2))}. Quando a "
        "conta chegar, é só dizer o valor.")
    assert "Energia" not in textos["despesas_sem_valor"]  # com valor, a Energia está nas contas vencidas
    assert textos["contas_vencidas"].startswith("1 conta vencida, somando 850 reais")
    rodar_rotina()
    r = chamar("ver_decisoes", origem="despesa sem valor")
    t = falado(r)
    assert f"Água de {MES} venceu" in t and "ainda não tem valor nem pagamento" in t
    assert f"Internet de {MES} vence" in t
    t = falado(chamar("ver_decisoes", origem="conta vencida"))
    assert f"Conta vencida: Energia de {MES}, 850 reais, venceu" in t
    t = falado(chamar("ver_contas", situacao="vencidas"))
    assert f"despesa Energia de {MES}, parcela única, 850 reais, venceu" in t and "compra None" not in t


# --- nenhuma leitura grava ---------------------------------------------------------------------------

def test_nenhuma_leitura_de_despesas_grava(mes, bolinha_a_5, bolinha):
    vender(bolinha, bolinha_a_5, 10)
    antes = (contagem(), Proposta.objects.count(), Movimento.objects.count())
    respostas = [chamar("ver_despesas"), chamar("ver_despesas", mes="mês passado"), chamar("ver_despesas_a_pagar"),
                 chamar("ver_resultado"), chamar("ver_resultado", periodo="semana"), chamar("ver_indireto_real"),
                 chamar("ver_estudo_preco"), chamar("simular_preco", produto="bolinha", preco=6),
                 chamar("simular_preco", produto="bolinha", sobra_pct=40), chamar("ver_ponto_equilibrio",
                                                                                 produto="bolinha"),
                 chamar("ver_relatorio"), chamar("ver_margem"), chamar("ver_margem_tabela")]
    assert (contagem(), Proposta.objects.count(), Movimento.objects.count()) == antes
    for r in respostas:
        falado(r)
    assert "simulação" in respostas[7]["texto"].lower() and "simulação" in respostas[8]["texto"].lower()
    assert "depois das despesas" in respostas[3]["texto"] and "depois das despesas" in respostas[10]["texto"]
    assert "estimad" in respostas[11]["texto"] and "estimad" in respostas[5]["texto"]
