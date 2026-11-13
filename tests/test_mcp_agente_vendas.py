"""Plano 6, fase 2b: ferramentas do agente de voz para vendas, encomendas, fritura, perda e contas a receber."""

import json
import re
from datetime import timedelta
from decimal import Decimal as D

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone
from mcp.shared.memory import create_connected_server_and_client_session

from agente.compras import quando
from agente.ferramentas import REGISTRO, criar_servidor
from agente.models import Proposta
from agente.vendas import _dia, _hora, _para, _tokens
from cadastros.models import Cliente, Item
from cadastros.servicos import salvar_cliente
from decisoes.consultas import decisoes
from decisoes.geradores import rodar_rotina
from estoque.models import CriterioValidade, Lote, Movimento
from estoque.servicos import saldo, saldo_lote
from financeiro.models import Pagamento
from nucleo.models import RegistroOperacao
from producao.models import Fritura
from vendas.models import Encomenda, Reserva, Venda
from vendas.servicos import criar_encomenda, registrar_venda, salvar_apresentacao

pytestmark = pytest.mark.django_db
HOJE = timezone.localdate()


def dia(n):
    return HOJE + timedelta(days=n)


@pytest.fixture(autouse=True)
def pasta_backup(settings, tmp_path):
    """O resumo do dia olha o backup: nunca a pasta real, e um backup recente para não virar assunto."""
    from datetime import datetime

    from backup.nucleo import FORMATO, PREFIXO
    settings.BACKUP_DIR = tmp_path
    (tmp_path / f"{PREFIXO}{(datetime.now() - timedelta(hours=1)).strftime(FORMATO)}.tar.gz").write_bytes(b"x")


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


def confirmar(r):
    assert "confirmar" in r, r
    return chamar("confirmar_proposta", proposta_id=r["proposta_id"])


def ferramentas():
    async def acao(s):
        return (await s.list_tools()).tools
    return {t.name: t for t in _sessao(acao)}


def falavel(t):
    """Nada de "R$ 90,00" nem "15/11" no que a voz lê."""
    assert "R$" not in t and not re.search(r"\d/\d", t), t
    return t


@pytest.fixture
def coxinha():
    return Item.objects.create(nome="Coxinha 150 g", tipo="produto", unidade_base="un", oleo_ref_un=D("0.05"))


@pytest.fixture
def caixa_papelao():
    c = Item.objects.create(nome="Caixa de papelão", tipo="embalagem", unidade_base="un", controla_validade=False)
    l = Lote.objects.create(item=c, codigo="CX", custo_unitario=D("1.00"))
    Movimento.objects.create(tipo="entrada_manual", item=c, lote=l, quantidade=20, quantidade_informada=20,
                             unidade_informada="un", fator=1, motivo="compra")
    return c


def lote(produto, n, *, validade, forma="cru", estado="congelado", custo="0.60", codigo=""):
    l = Lote.objects.create(item=produto, codigo=codigo, forma=forma, validade=validade, custo_unitario=D(custo))
    Movimento.objects.create(tipo="entrada_producao", item=produto, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado=estado, validade=validade)
    return l


def apresentacao(produto, nome="unidade", unidades=1, preco="2", atacado=None, forma="cru", estado="congelado", **kw):
    return salvar_apresentacao(produto_id=produto.id, nome=nome, forma=forma, estado=estado, unidades=unidades,
                               preco_varejo=D(preco), preco_atacado=atacado, autor="dono", **kw)["apresentacao_id"]


@pytest.fixture
def tabela(coxinha, caixa_papelao):
    """Coxinha 150 g: unidade crua congelada (2 reais), caixa com 25 crua congelada (45, atacado 40) e unidade frita
    fresca (4 reais)."""
    return {"unidade": apresentacao(coxinha),
            "caixa": apresentacao(coxinha, "caixa com 25", 25, "45", atacado="40", embalagem_id=caixa_papelao.id,
                                  embalagens=1),
            "frita": apresentacao(coxinha, "unidade frita", 1, "4", forma="frito", estado="fresco")}


@pytest.fixture
def joao():
    return Cliente.objects.get(id=salvar_cliente(nome="João", autor="dono")["cliente_id"])


# --- registro e alçada ----------------------------------------------------------

LEITURA = {"ver_precos", "ver_estoque_para_venda", "buscar_clientes", "ver_vendas", "ver_encomendas", "ver_encomenda",
           "ver_necessidade_producao", "ver_a_receber", "ver_sobras"}
NIVEL_2 = {"registrar_venda", "cancelar_venda", "criar_encomenda", "entregar_encomenda", "cancelar_encomenda",
           "registrar_fritura", "registrar_perda", "registrar_recebimento", "estornar_recebimento_cliente"}


def test_alcada_das_ferramentas_de_vendas():
    nivel = {f.nome: f.nivel for f in REGISTRO}
    assert {n: nivel[n] for n in LEITURA} == dict.fromkeys(LEITURA, 0)
    assert (nivel["cadastrar_cliente"], nivel["completar_reserva"]) == (1, 1)
    # dinheiro e estoque saindo esperam o "sim" (Q1, Q11); preço não muda por voz (Q10)
    assert {n: nivel[n] for n in NIVEL_2} == dict.fromkeys(NIVEL_2, 2)
    assert {n for n in nivel if "preco" in n} == {"ver_precos", "ultimo_preco"}  # nenhuma muda preço
    t = ferramentas()
    assert len(t) == 70
    assert {n for n in LEITURA if t[n].annotations.readOnlyHint} == LEITURA
    assert "$ref" not in json.dumps(t["registrar_venda"].inputSchema)
    assert t["registrar_venda"].inputSchema["properties"]["itens"]["items"]["required"] == ["produto", "quantidade"]
    assert "preco" not in t["registrar_venda"].inputSchema["properties"]["itens"]["items"]["properties"]


def test_entradas_faladas():
    assert _tokens("caixas de COXINHAS congeladas com 25") == ["caixa", "coxinha", "congelado", "25"]
    assert _tokens("pastéis fritos") == ["pastel", "frito"]
    assert _tokens("coxinha grande de 150 gramas crua") == ["coxinha", "grande", "150", "g", "cru"]
    assert (_dia("hoje", "dia"), _dia("amanhã", "dia"), _dia("depois de amanhã", "dia")) == (HOJE, dia(1), dia(2))
    sabado = _dia("sábado", "dia")
    assert sabado.weekday() == 5 and 0 <= (sabado - HOJE).days < 7
    assert (_hora("15h"), _hora("15h30"), _hora("9:05"), _hora("")) == ("15:00", "15:30", "09:05", None)
    assert chamar("criar_encomenda", cliente="x", dia="ontem de manhã", itens=[{"produto": "x", "quantidade": 1}]) \
        == {"erro": "Nenhum cliente com o nome 'x'."}


# --- leitura ----------------------------------------------------------------------

def test_precos_e_estoque_para_venda(coxinha, tabela, joao):
    lote(coxinha, 60, validade=dia(10))
    lote(coxinha, 5, validade=dia(-1), codigo="V")
    criar_encomenda(cliente_id=joao.id, entrega_data=dia(1), itens=[{"apresentacao_id": tabela["unidade"],
                                                                      "quantidade": 10}], autor="dono")
    r = chamar("ver_precos", produto="coxinha caixa")
    assert [p["apresentacao"] for p in r["precos"]] == ["caixa com 25"]
    assert falavel(r["texto"]) == ("Preços: caixa com 25 de Coxinha 150 g, cru congelado, 45 reais, no atacado "
                                   "40 reais, dá para vender 2 agora.")
    assert len(chamar("ver_precos")["precos"]) == 3
    assert chamar("ver_precos", produto="esfiha")["texto"] == "Não há preço cadastrado para 'esfiha'."
    e = chamar("ver_estoque_para_venda", produto="coxinha")
    assert e["texto"] == ("Coxinha 150 g, cru congelado: 50 unidades para vender, 10 unidades reservadas para "
                          "encomendas, 5 unidades vencidas.")


def test_cadastrar_e_buscar_cliente():
    r = chamar("cadastrar_cliente", nome="Bar do Zé", contato="11 98888-0000")
    assert r["dito"] == "Cliente Bar do Zé cadastrado." and Cliente.objects.get().contato == "11 98888-0000"
    assert chamar("cadastrar_cliente", nome="Bar do Zé")["repetida"]  # o modelo repetiu a chamada
    RegistroOperacao.objects.update(criado_em=timezone.now() - timedelta(minutes=1))
    assert chamar("cadastrar_cliente", nome="bar do ze") == {"erro": "Já existe o cliente 'Bar do Zé'."}
    assert chamar("buscar_clientes", busca="ZE")["texto"] == "Clientes: Bar do Zé."
    assert chamar("buscar_clientes", busca="Maria")["texto"] == "Nenhum cliente com o nome 'Maria'."


# --- venda ------------------------------------------------------------------------

def test_venda_a_vista_so_grava_depois_do_sim(coxinha, tabela, caixa_papelao):
    lote(coxinha, 60, validade=dia(10))
    # "coxinha" sozinha tem três jeitos de vender: pergunta qual
    amb = chamar("registrar_venda", itens=[{"produto": "coxinha", "quantidade": 2}])
    assert amb["erro"].startswith("Mais de um jeito de vender 'coxinha'") and len(amb["opcoes"]) == 3
    r = chamar("registrar_venda", itens=[{"produto": "coxinha", "apresentacao": "caixas", "conservacao": "congelada",
                                          "quantidade": 2}], forma_pagamento="pix")
    assert falavel(r["confirmar"]) == ("Vender 2 caixas com 25 de Coxinha 150 g, cru congelado, a 45 reais cada. "
                                       "Total 90 reais, à vista no pix. Confirma?")
    assert Venda.objects.count() == 0 and saldo(coxinha) == 60 and saldo(caixa_papelao) == 20  # nada gravado
    f = confirmar(r)
    v = Venda.objects.get()
    assert f["dito"].startswith("Feito: Vender 2 caixas") and f["dito"].endswith(f"É a venda {v.id}.")
    assert (v.total, v.forma_pagamento, v.condicao, saldo(coxinha), saldo(caixa_papelao)) == (
        D("90"), "pix", "a_vista", 10, 18)
    assert RegistroOperacao.objects.get(nome="registrar_venda").canal == "agente"
    # confirmar de novo não vende duas vezes
    assert confirmar(r)["resultado"]["venda_id"] == v.id and Venda.objects.count() == 1


def test_venda_varias_linhas_e_tabela_de_atacado(coxinha, tabela):
    lote(coxinha, 60, validade=dia(10))
    lote(coxinha, 10, validade=dia(1), forma="frito", estado="fresco")
    r = chamar("registrar_venda", itens=[{"produto": "coxinha", "apresentacao": "unidade frita", "quantidade": 3},
                                         {"produto": "coxinha unidade", "conservacao": "congelado", "quantidade": 1}])
    assert r["confirmar"] == ("Vender 3 unidades fritas de Coxinha 150 g, frito fresco, a 4 reais cada e 1 unidade "
                              "de Coxinha 150 g, cru congelado, por 2 reais. Total 14 reais, à vista. Confirma?")
    sem_atacado = chamar("registrar_venda", itens=[{"produto": "coxinha unidade frita", "quantidade": 1}],
                         tabela="atacado")
    assert sem_atacado["erro"].endswith("não tem preço de atacado.")
    atacado = chamar("registrar_venda", itens=[{"produto": "coxinha caixa", "quantidade": 1}], tabela="atacado")
    assert "Total 40 reais, preço de atacado, à vista" in atacado["confirmar"]


def test_venda_sem_estoque_e_erro_de_regra_viram_texto(coxinha, tabela):
    lote(coxinha, 5, validade=dia(5))
    r = chamar("registrar_venda", itens=[{"produto": "coxinha", "apresentacao": "unidade", "conservacao": "congelado",
                                          "quantidade": 6}])
    assert r == {"erro": "Só há 5 un de 'Coxinha 150 g' cru congelado para vender (pedido: 6 un). O resto está "
                         "reservado, vencido ou não existe."}
    assert Venda.objects.count() == 0 and Proposta.objects.count() == 0
    assert chamar("registrar_venda", itens=[{"produto": "esfiha", "quantidade": 1}])["erro"].startswith(
        "Não achei preço para 'esfiha'")
    assert chamar("registrar_venda", itens=[])["erro"].startswith("Diga os itens")


def test_proposta_de_venda_expira(coxinha, tabela):
    lote(coxinha, 10, validade=dia(5))
    r = chamar("registrar_venda", itens=[{"produto": "coxinha congelada unidade", "quantidade": 1}])
    Proposta.objects.update(expira_em=timezone.now() - timedelta(seconds=1))
    assert "expirou" in chamar("confirmar_proposta", proposta_id=r["proposta_id"])["erro"]
    assert Venda.objects.count() == 0


def test_fiado_vira_conta_a_receber_e_o_cliente_paga(coxinha, tabela, joao):
    lote(coxinha, 60, validade=dia(10))
    item = [{"produto": "coxinha", "apresentacao": "caixa", "quantidade": 2}]
    assert chamar("registrar_venda", itens=item, condicao="fiado") == {
        "erro": "Venda a prazo precisa do cliente: para quem foi?"}
    assert chamar("registrar_venda", itens=item, condicao="fiado", cliente="joao") == {
        "erro": "Quando o cliente vai pagar? Diga o prazo em dias ou a data."}
    r = chamar("registrar_venda", itens=item, condicao="a_prazo", cliente="joao", prazo_dias=30, parcelas=2)
    assert falavel(r["confirmar"]) == (
        f"Vender 2 caixas com 25 de Coxinha 150 g, cru congelado, a 45 reais cada, para João. Total 90 reais, a prazo "
        f"em 2 parcelas: 45 reais {quando(dia(30))} e 45 reais {quando(dia(60))}. Confirma?")
    confirmar(r)
    v = Venda.objects.get()
    d = chamar("ver_a_receber", cliente="JOÃO")
    assert falavel(d["texto"]) == (f"João deve 90 reais em 2 parcelas, nada vencido. A mais antiga: venda {v.id}, "
                                   f"parcela 1 de 2, 45 reais, vence {quando(dia(30))}.")
    assert chamar("ver_a_receber")["texto"] == "Os clientes devem 90 reais no total. João, 90 reais."
    assert chamar("ver_a_receber", situacao="vencidas")["texto"] == "Nenhum cliente com conta vencida."
    # o João pagou a primeira parcela
    p = chamar("registrar_recebimento", cliente="joão", forma="dinheiro")
    assert falavel(p["confirmar"]) == (f"Anotar que João pagou 45 reais hoje, venda {v.id}, parcela 1 de 2, 45 reais, "
                                       f"vence {quando(dia(30))} no dinheiro. A parcela fica quitada. Confirma?")
    assert Pagamento.objects.count() == 0
    confirmar(p)
    assert chamar("ver_a_receber", cliente="joao")["devido"]["valor"] == 45
    # anotado errado: desfaz
    e = chamar("estornar_recebimento_cliente", cliente="joao", motivo="era da outra venda")
    assert e["confirmar"].startswith("Desfazer o recebimento de 45 reais de João, hoje, venda")
    assert e["confirmar"].endswith("A parcela volta a ficar em aberto com 45 reais. Confirma?")
    confirmar(e)
    assert chamar("ver_a_receber", cliente="joao")["devido"]["valor"] == 90
    # quem não deve nada
    salvar_cliente(nome="Maria", autor="dono")
    assert chamar("ver_a_receber", cliente="maria")["texto"] == "Maria não deve nada."
    assert chamar("registrar_recebimento", cliente="maria") == {"erro": "Nenhuma conta a receber de Maria em aberto."}


def test_cliente_ambiguo_devolve_candidatos(coxinha, tabela):
    salvar_cliente(nome="João da Padaria", autor="dono")
    salvar_cliente(nome="João do Bar", autor="dono")
    r = chamar("registrar_venda", itens=[{"produto": "coxinha caixa", "quantidade": 1}], cliente="joão",
               condicao="a_prazo", prazo_dias=7)
    assert r["erro"] == "Mais de um cliente com o nome 'joão'; diga qual."
    assert r["opcoes"] == ["João da Padaria", "João do Bar"]


def test_cancelar_venda_volta_ao_estoque(coxinha, tabela, joao):
    lote(coxinha, 60, validade=dia(10))
    confirmar(chamar("registrar_venda", itens=[{"produto": "coxinha caixa", "quantidade": 1}], cliente="joao",
                     condicao="a_prazo", vencimento=dia(7).isoformat()))
    v = Venda.objects.get()
    r = chamar("cancelar_venda", cliente="joao", motivo="cliente desistiu", destino="volta pro estoque")
    assert falavel(r["confirmar"]) == (
        f"Cancelar a venda {v.id}, de hoje, 1 caixa com 25 de Coxinha 150 g, cru congelado, para João, total 45 reais "
        "(motivo: cliente desistiu). 25 unidades voltam ao estoque; a embalagem não volta. A conta a receber é "
        "cancelada. Confirma?")
    assert saldo(coxinha) == 35
    confirmar(r)
    v.refresh_from_db()
    assert (v.situacao, v.destino, saldo(coxinha)) == ("cancelada", "estoque", 60)
    assert chamar("ver_a_receber")["texto"] == "Nenhum cliente está devendo."
    # sem cliente nem número: as vendas de hoje; já cancelada, o núcleo recusa
    assert chamar("cancelar_venda", venda_id=v.id, motivo="de novo") == {"erro": "Esta venda já foi cancelada."}


def test_ver_vendas_fala_os_totais(coxinha, tabela, joao):
    lote(coxinha, 60, validade=dia(10))
    registrar_venda(itens=[{"apresentacao_id": tabela["unidade"], "quantidade": 5}], forma_pagamento="pix",
                    autor="dono")
    registrar_venda(itens=[{"apresentacao_id": tabela["caixa"], "quantidade": 1}], cliente_id=joao.id,
                    condicao="a_prazo", parcelas=[{"valor": "45", "vencimento": dia(7)}], autor="dono")
    r = chamar("ver_vendas")
    assert falavel(r["texto"]) == ("Hoje, 2 vendas, somando 55 reais: 10 reais recebidos na hora (10 reais no pix) e 45 reais a "
                                   "prazo. "
                                   "Por produto: Coxinha 150 g, 30 unidades, 55 reais.")
    assert r["totais"]["total"] == {"valor": 55.0, "texto": "55 reais"} and "margem" not in json.dumps(r)
    assert chamar("ver_vendas", cliente="joao")["texto"].startswith("Hoje, 1 venda para João, somando 45 reais")
    assert chamar("ver_vendas", periodo="ontem")["texto"] == "Ontem, nenhuma venda."


# --- encomendas -------------------------------------------------------------------

def test_encomenda_reserva_o_que_ha_completa_e_entrega(coxinha, tabela, joao, caixa_papelao):
    lote(coxinha, 30, validade=dia(10))
    r = chamar("criar_encomenda", cliente="joao", dia="amanhã", hora="15h",
               itens=[{"produto": "coxinha", "apresentacao": "caixa com 25", "quantidade": 2}], sinal=20,
               sinal_forma="pix", observacao="sem pimenta")
    assert falavel(r["confirmar"]) == (
        "Encomenda de João para amanhã às 15h, retirada: 2 caixas com 25 de Coxinha 150 g, cru congelado, a 45 reais "
        "cada. Total 90 reais; sinal de 20 reais no pix, fica faltando 70 reais. Reserva agora o que há no estoque; "
        "falta produzir 20 unidades de Coxinha 150 g cru congelado. Observação: sem pimenta. Confirma?")
    assert Encomenda.objects.count() == 0 and Reserva.objects.count() == 0
    f = confirmar(r)
    e = Encomenda.objects.get()
    assert f["dito"].endswith(f"É a encomenda {e.id}.")
    lista = chamar("ver_encomendas", dia="amanhã")
    assert falavel(lista["texto"]) == (
        f"1 encomenda em aberto para amanhã. Encomenda {e.id} de João, para amanhã às 15h, retirada: 2 caixas com 25 "
        "de Coxinha 150 g, cru congelado; falta reservar 20 unidades de Coxinha 150 g cru congelado.")
    assert chamar("ver_encomendas", dia="hoje")["texto"] == "Nenhuma encomenda em aberto para hoje."
    n = chamar("ver_necessidade_producao")
    assert n["texto"] == ("Para as encomendas até daqui a 3 dias: Coxinha 150 g cru congelado: faltam 20 unidades, "
                          "produzir 20 unidades, a primeira entrega é amanhã.")
    # entregar faltando: o núcleo recusa e o erro vira fala
    assert chamar("entregar_encomenda", cliente="joao") == {
        "erro": "Falta reservar 20 un de 'Coxinha 150 g' cru congelado. Complete a reserva antes de entregar."}
    # entrou estoque: "reserva a encomenda do João" grava na hora (nível 1)
    lote(coxinha, 40, validade=dia(20))
    c = chamar("completar_reserva", cliente="joão")
    assert c["dito"] == f"Encomenda {e.id} de João: reserva completa, está pronta para amanhã."
    assert chamar("ver_encomenda", encomenda_id=e.id)["texto"] == (
        f"Encomenda {e.id} de João, para amanhã às 15h, retirada: 2 caixas com 25 de Coxinha 150 g, cru congelado; "
        "pronta, tudo reservado. Total 90 reais, sinal de 20 reais no pix, falta receber 70 reais na entrega. "
        "Observação: sem pimenta.")
    ent = chamar("entregar_encomenda", cliente="joao", forma_pagamento="dinheiro")
    assert falavel(ent["confirmar"]) == (
        f"Entregar a encomenda {e.id} de João: 2 caixas com 25 de Coxinha 150 g, cru congelado. Total 90 reais, com "
        "20 reais de sinal já pago. Recebe 70 reais agora no dinheiro. Confirma?")
    assert saldo(coxinha) == 70
    feito = confirmar(ent)
    v = Venda.objects.get()
    assert feito["dito"].endswith(f"Virou a venda {v.id}.")
    assert (v.recebido_na_hora, saldo(coxinha), saldo(caixa_papelao)) == (D("70"), 20, 18)
    assert chamar("ver_encomendas")["texto"] == "Nenhuma encomenda em aberto."


def test_encomenda_a_prazo_e_cancelamento_com_sinal(coxinha, tabela, joao):
    lote(coxinha, 100, validade=dia(10))
    a = criar_encomenda(cliente_id=joao.id, entrega_data=dia(1), itens=[{"apresentacao_id": tabela["caixa"],
                                                                         "quantidade": 1}], autor="dono")
    b = criar_encomenda(cliente_id=joao.id, entrega_data=dia(2), sinal="10", itens=[
        {"apresentacao_id": tabela["unidade"], "quantidade": 10}], autor="dono")
    amb = chamar("cancelar_encomenda", cliente="joao", motivo="festa adiada")
    assert amb["erro"] == "João tem mais de uma encomenda em aberto; diga qual (encomenda_id)."
    assert amb["opcoes"] == [f"Encomenda {a['encomenda_id']}, para amanhã, 45 reais",
                             f"Encomenda {b['encomenda_id']}, {_para(dia(2))}, 20 reais"]
    r = chamar("cancelar_encomenda", encomenda_id=b["encomenda_id"], motivo="festa adiada", devolver_sinal=False)
    assert r["confirmar"].endswith("As reservas são liberadas e nada sai do estoque. O sinal de 10 reais fica com "
                                   "você, não é devolvido. Confirma?")
    assert Reserva.objects.filter(situacao="ativa").count() == 2
    confirmar(r)
    e = Encomenda.objects.get(id=b["encomenda_id"])
    assert (e.situacao, e.sinal_devolvido) == ("cancelada", D("0"))
    # a outra: entrega a prazo
    ent = chamar("entregar_encomenda", cliente="joao", condicao="a prazo", prazo_dias=15)
    assert ent["confirmar"].endswith(f"Total 45 reais. Os 45 reais ficam a prazo, vence {quando(dia(15))}. Confirma?")
    confirmar(ent)
    assert chamar("ver_a_receber", cliente="joao")["devido"]["valor"] == 45


# --- fritura, sobras e perda ---------------------------------------------------------

def test_fritura_pergunta_a_conservacao_e_vira_sobra(coxinha, tabela):
    CriterioValidade.objects.create(produto=coxinha, forma="frito", estado="fresco", dias=1)
    cong = lote(coxinha, 50, validade=dia(30), codigo="C1")
    lote(coxinha, 20, validade=dia(3), estado="resfriado", codigo="R1")
    amb = chamar("registrar_fritura", produto="coxinha", quantidade=40)
    assert amb["erro"] == "Há Coxinha 150 g cru em mais de uma conservação; pergunte de qual saiu."
    assert amb["opcoes"] == ["resfriado: 20 unidades livres", "congelado: 50 unidades livres"]
    assert chamar("registrar_fritura", produto="coxinha", quantidade=40, boas=38, conservacao="freezer") == {
        "erro": "Informe o motivo das perdas."}
    r = chamar("registrar_fritura", produto="coxinha", quantidade=40, boas=38, conservacao="freezer",
               motivo_perdas="estouraram")
    assert falavel(r["confirmar"]) == (
        f"Fritar 40 unidades de Coxinha 150 g do lote C1, congelado, que vence {quando(dia(30))}: 38 boas e 2 "
        "perdidas (estouraram). Custo de 68 centavos por unidade frita; o frito fica fresco e vale até amanhã. "
        "Confirma?")
    assert Fritura.objects.count() == 0 and saldo_lote(cong, "congelado") == 50
    confirmar(r)
    assert saldo_lote(cong, "congelado") == 10 and Fritura.objects.get().boas == 38
    s = chamar("ver_sobras")
    assert s["texto"] == "Sobras fritas: 38 unidades. 38 unidades de Coxinha 150 g fritas hoje, fresco."
    # sobrou: joga fora (nível 2, com o motivo)
    p = chamar("registrar_perda", produto="coxinha", forma="frita", quantidade=8, motivo="sobra do dia")
    frito = Fritura.objects.get().lote
    assert falavel(p["confirmar"]) == (
        f"Dar perda de 8 unidades de Coxinha 150 g, lote {frito.codigo}, frito, fresco, 38 un, vence amanhã "
        "(motivo: sobra do dia). Sai do estoque sem volta: 5 reais e 47 centavos em mercadoria. Ficam 30 unidades "
        "nesse lote. Confirma?")
    assert saldo_lote(frito, "fresco") == 38
    confirmar(p)
    assert saldo_lote(frito, "fresco") == 30


def test_perda_ambigua_e_descarte_de_vencido_libera_reserva(coxinha, tabela, joao):
    venc = lote(coxinha, 10, validade=dia(-1), codigo="V1")
    lote(coxinha, 10, validade=dia(9), codigo="B1")
    amb = chamar("registrar_perda", produto="coxinha", motivo="caiu")
    assert amb["erro"].startswith("Há mais de um lote de Coxinha 150 g com saldo") and len(amb["opcoes"]) == 2
    assert amb["opcoes"][0] == "lote V1, cru, congelado, 10 un, venceu ontem"
    assert chamar("registrar_perda", produto="coxinha", vencido=True, motivo="") == {
        "erro": "Informe o motivo da perda."}
    r = chamar("registrar_perda", produto="coxinha", vencido=True, motivo="vencido")
    assert r["confirmar"] == ("Descartar 10 unidades de Coxinha 150 g, lote V1, cru, congelado, 10 un, venceu ontem "
                              "(motivo: vencido). Sai do estoque sem volta: 6 reais em mercadoria. O lote fica zerado. "
                              "Confirma?")
    assert saldo_lote(venc, "congelado") == 10
    confirmar(r)
    assert saldo_lote(venc, "congelado") == 0


# --- caixa de decisões e resumo do dia -----------------------------------------------

def test_caixa_nova_fala_sem_barra_nem_cifrao_e_aprova_completar_reserva(coxinha, tabela, joao):
    CriterioValidade.objects.create(produto=coxinha, forma="frito", estado="fresco", dias=2)
    # encomenda sem estoque para amanhã; depois entra estoque livre que serve
    e = criar_encomenda(cliente_id=joao.id, entrega_data=dia(1), itens=[{"apresentacao_id": tabela["unidade"],
                                                                         "quantidade": 10}], autor="dono")
    cru = lote(coxinha, 40, validade=dia(30))
    # fiado vencido e frito de ontem
    registrar_venda(itens=[{"apresentacao_id": tabela["unidade"], "quantidade": 5}], cliente_id=joao.id,
                    condicao="a_prazo", parcelas=[{"valor": "10", "vencimento": dia(-3)}], autor="dono")
    confirmar(chamar("registrar_fritura", produto="coxinha", quantidade=6))
    Lote.objects.filter(forma="frito").update(criado_em=timezone.now() - timedelta(days=1))
    assert saldo_lote(cru, "congelado") == 29
    rodar_rotina()
    origens = {d["origem"] for d in decisoes()}
    assert {"encomenda_sem_estoque", "receber_vencidas", "sobras_fritas"} <= origens

    caixa = chamar("ver_decisoes")
    falavel(caixa["texto"])
    assert all(falavel(i["texto"]) for i in caixa["itens"])
    [dec] = [i for i in caixa["itens"] if i["origem"] == "encomenda_sem_estoque"]
    assert dec["tipo"] == "decisao" and caixa["texto"].startswith("Na caixa, 1 decisão para aprovar e 3 avisos.")
    assert dec["texto"] == (f"Encomenda {e['encomenda_id']} de João para amanhã: falta reservar 10 unidades de "
                            "Coxinha 150 g cru congelado. Há 10 unidades no estoque que servem: reservar agora?")
    devendo = chamar("ver_decisoes", origem="fiado")["itens"]
    assert [i["texto"] for i in devendo] == [
        f"João está devendo 10 reais (parcela 1 de 1), que venceu {quando(dia(-3))}."]
    sobras = chamar("ver_decisoes", origem="sobra")["itens"]
    assert sobras[0]["texto"].startswith("Sobraram 6 unidades de Coxinha 150 g fritos ontem")

    ap = chamar("aprovar_decisao", decisao_id=dec["decisao_id"])
    assert falavel(ap["confirmar"]).endswith(
        f"Vou reservar para a encomenda {e['encomenda_id']} o que houver no estoque; ela fica pronta, com tudo "
        "reservado. Confirma?")
    assert Reserva.objects.filter(situacao="ativa").count() == 0
    confirmar(ap)
    assert Reserva.objects.filter(situacao="ativa").count() == 1
    assert chamar("ver_encomenda", encomenda_id=e["encomenda_id"])["situacao"] == "pronta"

    dia_ = chamar("ver_resumo_do_dia")
    rotulos = [a["assunto"] for a in dia_["assuntos"]]
    assert {"receber_vencidas", "sobras_fritas", "encomendas_proximas", "vendas"} <= set(rotulos)
    assert all(falavel(a["texto"]) for a in dia_["assuntos"])
    [rv] = [a for a in dia_["assuntos"] if a["assunto"] == "receber_vencidas"]
    assert rv["texto"] == "1 conta a receber vencida de clientes, somando 10 reais."
    [vd] = [a for a in dia_["assuntos"] if a["assunto"] == "vendas"]
    assert vd["texto"] == "Hoje, 1 venda, somando 10 reais."


def test_resumo_fala_encomendas_de_hoje_e_o_que_falta_produzir(coxinha, tabela, joao):
    lote(coxinha, 5, validade=dia(10))
    criar_encomenda(cliente_id=joao.id, entrega_data=HOJE, itens=[{"apresentacao_id": tabela["unidade"],
                                                                    "quantidade": 5}], autor="dono")
    criar_encomenda(cliente_id=joao.id, entrega_data=HOJE, itens=[{"apresentacao_id": tabela["unidade"],
                                                                    "quantidade": 8}], autor="dono")
    r = chamar("ver_resumo_do_dia")
    assuntos = {a["assunto"]: a["texto"] for a in r["assuntos"]}
    assert assuntos["encomendas_hoje"] == "2 encomendas para hoje: 1 pronta e 1 faltando reservar."
    assert assuntos["falta_produzir"] == ("Para as encomendas dos próximos 3 dias, falta produzir 8 unidades de "
                                          "Coxinha 150 g cru congelado.")
    assert "2 encomendas para hoje" in r["texto"]  # entre os três mais urgentes
