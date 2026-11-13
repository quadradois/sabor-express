"""Plano 9, fase 2b: lotes na operação pelo agente de voz — separação, lote indicado, venda com data passada,
vencido com motivo, conferência do vencido, contagem e destino da perda."""

import datetime as dt
import json
import re
from decimal import Decimal as D

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone
from mcp.shared.memory import create_connected_server_and_client_session

from agente.compras import quando
from agente.ferramentas import REGISTRO, criar_servidor
from cadastros.models import Cliente, Item
from cadastros.servicos import salvar_cliente
from decisoes.geradores import rodar_rotina
from decisoes.models import Decisao
from estoque.lotes import nome_lote
from estoque.models import Lote, Movimento
from estoque.servicos import saldo_lote
from nucleo.operacoes import RegraViolada
from vendas.lotes import separacao_venda
from vendas.models import LinhaVenda, Venda
from vendas.servicos import criar_encomenda, registrar_venda, salvar_apresentacao

pytestmark = pytest.mark.django_db
HOJE = timezone.localdate()


def dia(n):
    return HOJE + dt.timedelta(days=n)


@pytest.fixture(autouse=True)
def pasta_backup(settings, tmp_path):
    from datetime import datetime

    from backup.nucleo import FORMATO, PREFIXO
    settings.BACKUP_DIR = tmp_path
    (tmp_path / f"{PREFIXO}{(datetime.now() - dt.timedelta(hours=1)).strftime(FORMATO)}.tar.gz").write_bytes(b"x")


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


def falavel(t, *lotes):
    """Nada de "R$", "15/11" nem código de lote no que a voz lê."""
    assert "R$" not in t and not re.search(r"\d/\d", t), t
    for l in lotes:
        assert not l.codigo or l.codigo not in t, t
    return t


@pytest.fixture
def coxinha():
    return Item.objects.create(nome="Coxinha 150 g", tipo="produto", unidade_base="un", oleo_ref_un=D("0.05"))


def lote(produto, n, *, validade, feito, forma="cru", estado="congelado", custo="0.60", codigo=""):
    l = Lote.objects.create(item=produto, codigo=codigo, forma=forma, validade=validade, custo_unitario=D(custo))
    Movimento.objects.create(tipo="entrada_producao", item=produto, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado=estado, validade=validade)
    Lote.objects.filter(id=l.id).update(criado_em=timezone.make_aware(dt.datetime.combine(feito, dt.time(10))))
    l.refresh_from_db()
    return l


def apresentacao(produto, nome="unidade", unidades=1, preco="2", forma="cru", estado="congelado"):
    return salvar_apresentacao(produto_id=produto.id, nome=nome, forma=forma, estado=estado, unidades=unidades,
                               preco_varejo=D(preco), autor="dono")["apresentacao_id"]


@pytest.fixture
def unidade(coxinha):
    return apresentacao(coxinha)


@pytest.fixture
def dois_lotes(coxinha):
    """Lote do dia de 5 dias atrás (18 un, vence amanhã) e do de 3 dias atrás (40 un, vence em 20 dias)."""
    velho = lote(coxinha, 18, validade=dia(1), feito=dia(-5), codigo="V-123")
    novo = lote(coxinha, 40, validade=dia(20), feito=dia(-3), codigo="N-456")
    return velho, novo


ITEM = {"produto": "coxinha", "quantidade": 30}


# --- alçada ------------------------------------------------------------------------

def test_alcada_das_ferramentas_de_lotes():
    nivel = {f.nome: f.nivel for f in REGISTRO}
    assert (nivel["ver_separacao"], nivel["ver_separacao_encomenda"]) == (0, 0)
    # contagem altera saldo e a conferência sai do estoque: esperam o "sim"; venda, entrega, fritura,
    # transferência, devolução, conclusão e conciliação seguem nível 2 (o motivo do vencido vai na confirmação)
    assert {n: nivel[n] for n in ("contar_lote", "conferir_vencido", "registrar_venda", "entregar_encomenda",
                                  "registrar_fritura", "mudar_conservacao", "cancelar_venda", "concluir_producao",
                                  "conciliar_consumo", "registrar_perda")} == dict.fromkeys(
        ("contar_lote", "conferir_vencido", "registrar_venda", "entregar_encomenda", "registrar_fritura",
         "mudar_conservacao", "cancelar_venda", "concluir_producao", "conciliar_consumo", "registrar_perda"), 2)


# --- separação ----------------------------------------------------------------------

def test_separacao_diz_de_qual_lote_pegar_sem_codigo_e_sem_conta_do_agente(coxinha, unidade, dois_lotes):
    velho, novo = dois_lotes
    r = chamar("ver_separacao", itens=[ITEM])
    nv, nn = nome_lote(velho), nome_lote(novo)
    assert falavel(r["texto"], velho, novo) == (
        f"30 unidades de Coxinha 150 g cru congelado: 18 do {nv}, que vence amanhã, e 12 do {nn}; o {nv} zera e no "
        f"{nn} sobram 28.")
    # os números são os do núcleo (a mesma separação que a venda vai baixar)
    nucleo = separacao_venda(itens=[{"apresentacao_id": unidade, "quantidade": 30}])
    [linha] = r["linhas"]
    assert [(x["lote_id"], x["unidades"], x["sobra"]) for x in linha["lotes"]] == [
        (x["lote_id"], float(x["unidades"]), float(x["sobra"])) for x in nucleo["linhas"][0]["lotes"]]
    assert [x["lote"] for x in linha["lotes"]] == [nv, nn] and r["completo"] and not r["precisa_motivo"]
    assert Venda.objects.count() == 0 and saldo_lote(velho, "congelado") == 18  # só leitura


def test_separacao_com_lote_indicado_avisa_o_deixado(coxinha, unidade, dois_lotes):
    velho, novo = dois_lotes
    nn = nome_lote(novo)
    r = chamar("ver_separacao", itens=[{**ITEM, "lotes": [{"lote": f"lote do dia {novo.criado_em.day}",
                                                           "unidades": 30}]}])
    assert falavel(r["texto"], velho, novo).startswith(f"30 unidades de Coxinha 150 g cru congelado: 30 do {nn}")
    assert f"Ficaram 18 unidades do {nome_lote(velho)}, que vencem amanhã: venda esse primeiro." in r["texto"]
    assert r["linhas"][0]["deixados"][0]["lote_id"] == velho.id
    # também pelo lote_id da separação e pelo "dia 8" curto
    por_id = chamar("ver_separacao", itens=[{**ITEM, "lotes": [{"lote_id": novo.id, "unidades": 30}]}])
    curto = chamar("ver_separacao", itens=[{**ITEM, "lotes": [{"lote": str(novo.criado_em.day), "unidades": 30}]}])
    assert por_id["texto"] == curto["texto"] == r["texto"]


def test_lote_falado_desconhecido_ou_ambiguo_e_recusado_com_clareza(coxinha, unidade, dois_lotes):
    velho, novo = dois_lotes
    r = chamar("ver_separacao", itens=[{**ITEM, "lotes": [{"lote": "lote do dia 31 de fevereiro", "unidades": 5}]}])
    assert r["erro"].startswith("Não há lote do dia 31 de fevereiro de Coxinha 150 g cru congelado com saldo")
    assert set(r["opcoes"]) == {nome_lote(velho), nome_lote(novo)}
    segundo = lote(coxinha, 5, validade=dia(20), feito=dia(-3))
    amb = chamar("ver_separacao", itens=[{**ITEM, "lotes": [{"lote": f"dia {novo.criado_em.day}", "unidades": 5}]}])
    assert amb["erro"] == f"Há mais de um lote do dia {novo.criado_em.day} de Coxinha 150 g cru congelado; pergunte qual."
    assert amb["opcoes"] == [nome_lote(novo), nome_lote(segundo)]
    ok = chamar("ver_separacao", itens=[{**ITEM, "lotes": [{"lote": nome_lote(segundo), "unidades": 5}]}])
    assert ok["linhas"][0]["lotes"][0]["lote_id"] == segundo.id
    # o código ainda vale, se pedirem
    cod = chamar("ver_separacao", itens=[{**ITEM, "lotes": [{"lote": "v-123", "unidades": 5}]}])
    assert cod["linhas"][0]["lotes"][0]["lote_id"] == velho.id


def test_concordancia_falta_um(coxinha, unidade):
    lote(coxinha, 4, validade=dia(5), feito=dia(-1))
    r = separacao_venda(itens=[{"apresentacao_id": unidade, "quantidade": 5}])
    assert r["linhas"][0]["texto"].endswith("Falta 1 un.")
    assert any(a["texto"].startswith("Falta 1 un de Coxinha 150 g") for a in r["avisos"])
    r = separacao_venda(itens=[{"apresentacao_id": unidade, "quantidade": 6}])
    assert r["linhas"][0]["texto"].endswith("Faltam 2 un.")


# --- venda com lote indicado e data passada --------------------------------------------

def test_venda_repete_a_separacao_e_depois_avisa_o_deixado(coxinha, unidade, dois_lotes):
    velho, novo = dois_lotes
    nv, nn = nome_lote(velho), nome_lote(novo)
    r = chamar("registrar_venda", itens=[{**ITEM, "lotes": [{"lote": nn, "unidades": 30}]}], forma_pagamento="pix")
    assert falavel(r["confirmar"], velho, novo) == (
        "Vender 30 unidades de Coxinha 150 g, cru congelado, a 2 reais cada. Total 60 reais, à vista no pix. "
        f"De onde sai: 30 unidades de Coxinha 150 g cru congelado: 30 do {nn}; no {nn} sobram 10. Ficaram 18 "
        f"unidades do {nv}, que vencem amanhã: venda esse primeiro. Confirma?")
    assert Venda.objects.count() == 0
    f = confirmar(r)
    v = Venda.objects.get()
    assert falavel(f["dito"], velho, novo).endswith(
        f"É a venda {v.id}. Ficaram 18 unidades do {nv}, que vencem amanhã: venda esse primeiro.")
    linha = LinhaVenda.objects.get()
    assert linha.lotes_indicados and (saldo_lote(velho, "congelado"), saldo_lote(novo, "congelado")) == (18, 10)


def test_indicado_parcial_o_nucleo_completa(coxinha, unidade, dois_lotes):
    velho, novo = dois_lotes
    r = chamar("registrar_venda", itens=[{**ITEM, "lotes": [{"lote": nome_lote(novo), "unidades": 10}]}])
    confirmar(r)
    # o agente só passou os 10; os outros 20 o núcleo tirou pelo que vence primeiro
    assert (saldo_lote(velho, "congelado"), saldo_lote(novo, "congelado")) == (0, 28)


def test_venda_de_ontem_vale_pela_data_em_que_aconteceu(coxinha, unidade):
    # vence hoje - 1 = ontem: vendido ontem ainda estava na validade, sem motivo
    l = lote(coxinha, 20, validade=dia(-1), feito=dia(-4))
    hoje_vencido = chamar("registrar_venda", itens=[{"produto": "coxinha", "quantidade": 20}])
    assert hoje_vencido["erro"].startswith("Só há 0 un")  # hoje, o FEFO não pega vencido sozinho
    r = chamar("registrar_venda", itens=[{"produto": "coxinha", "quantidade": 20}], data="ontem")
    assert "venda de ontem" in r["confirmar"] and "Atenção" not in r["confirmar"]
    confirmar(r)
    assert Venda.objects.get().data == dia(-1) and saldo_lote(l, "congelado") == 0
    assert chamar("registrar_venda", itens=[{"produto": "coxinha", "quantidade": 1}], data="amanhã")["erro"].startswith(
        "A venda não pode ter data depois de hoje")


# --- vencido com motivo ---------------------------------------------------------------

def test_vencido_so_com_motivo_dito_e_repetido_na_confirmacao(coxinha, unidade):
    venc = lote(coxinha, 10, validade=dia(-2), feito=dia(-6), codigo="VX-9")
    nv = nome_lote(venc)
    pedido = [{"produto": "coxinha", "quantidade": 4, "lotes": [{"lote": nv, "unidades": 4}]}]
    sem = chamar("registrar_venda", itens=pedido)
    assert sem["precisa_motivo"] is True and falavel(sem["erro"], venc).startswith(
        f"O {nv} de 'Coxinha 150 g', congelado, venceu {quando(dia(-2))}. Para vender dele, informe o motivo.")
    assert "nunca invente" in sem["erro"] and Venda.objects.count() == 0
    sep = chamar("ver_separacao", itens=pedido)
    assert sep["precisa_motivo"] and "pergunte o motivo" in sep["texto"]
    r = chamar("registrar_venda", itens=pedido, motivo_vencido="cliente quis para ração do cachorro")
    assert falavel(r["confirmar"], venc).endswith(
        f"Atenção, lote vencido: o {nv} venceu {quando(dia(-2))}; vai com o motivo: cliente quis para ração do "
        "cachorro. Confirma?")
    confirmar(r)
    m = Movimento.objects.get(tipo="saida_venda")
    assert m.motivo_vencido == "cliente quis para ração do cachorro"


def test_motivo_sem_vencido_nao_vai_para_a_trilha(coxinha, unidade, dois_lotes):
    r = chamar("registrar_venda", itens=[ITEM], motivo_vencido="qualquer")
    assert "Atenção" not in r["confirmar"]
    confirmar(r)
    from nucleo.models import RegistroOperacao
    assert "motivo_vencido" not in RegistroOperacao.objects.get(nome="registrar_venda").parametros


def test_fritura_conservacao_e_devolucao_de_vencido_com_motivo(coxinha, unidade):
    from estoque.models import CriterioValidade

    CriterioValidade.objects.create(produto=coxinha, forma="frito", estado="fresco", dias=1)
    CriterioValidade.objects.create(produto=coxinha, forma="cru", estado="resfriado", dias=2)
    venc = lote(coxinha, 20, validade=dia(-1), feito=dia(-5), codigo="F-77")
    nv = nome_lote(venc)
    # fritura do lote dito, vencido: pergunta o motivo
    sem = chamar("registrar_fritura", produto="coxinha", quantidade=5, lote=nv)
    assert sem["precisa_motivo"] and "frito" in sem["erro"] and falavel(sem["erro"], venc)
    r = chamar("registrar_fritura", produto="coxinha", quantidade=5, lote=nv, motivo_vencido="teste de óleo")
    assert falavel(r["confirmar"], venc).startswith(f"Fritar 5 unidades de Coxinha 150 g do {nv}, congelado, que "
                                                     f"venceu ontem")
    assert r["confirmar"].endswith(f"Atenção, lote vencido: o {nv} de Coxinha 150 g venceu ontem; vai com o motivo: "
                                   "teste de óleo. Confirma?")
    confirmar(r)
    assert Movimento.objects.filter(motivo_vencido="teste de óleo").exists()
    # mudar a conservação do vencido
    sem = chamar("mudar_conservacao", produto="coxinha", para="resfriado", lote=nv, quantidade=5)
    assert sem["precisa_motivo"]
    r = chamar("mudar_conservacao", produto="coxinha", para="resfriado", lote=nv, quantidade=5,
               motivo_vencido="vai para a sopa da equipe")
    assert falavel(r["confirmar"].split("validade")[0], venc) and r["confirmar"].endswith(
        "vai com o motivo: vai para a sopa da equipe (continua vencido). Confirma?")
    confirmar(r)
    # venda de ontem do vencido (ainda válido ontem) e devolução ao estoque hoje: pede o motivo
    v = registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 3}], data_venda=dia(-1), autor="balcao")
    sem = chamar("cancelar_venda", venda_id=v["venda_id"], motivo="cliente devolveu", destino="estoque")
    assert sem["precisa_motivo"] and "a devolução vai para perda" in sem["erro"]
    r = chamar("cancelar_venda", venda_id=v["venda_id"], motivo="cliente devolveu", destino="estoque",
               motivo_vencido="vai para descarte depois da conferência")
    assert r["confirmar"].endswith("(volta ao estoque ainda vencido). Confirma?") and nv in r["confirmar"]
    confirmar(r)


# --- entrega de encomenda -------------------------------------------------------------

def test_entrega_com_separacao_e_lote_indicado(coxinha, unidade, dois_lotes):
    velho, novo = dois_lotes
    joao = Cliente.objects.get(id=salvar_cliente(nome="João", autor="dono")["cliente_id"])
    e = criar_encomenda(cliente_id=joao.id, entrega_data=HOJE, itens=[{"apresentacao_id": unidade,
                                                                        "quantidade": 10}], autor="dono")
    s = chamar("ver_separacao_encomenda", cliente="joão")
    nv, nn = nome_lote(velho), nome_lote(novo)
    assert falavel(s["texto"], velho, novo) == (
        f"Encomenda {e['encomenda_id']} de João: 10 unidades de Coxinha 150 g cru congelado: 10 do {nv}, que vence "
        f"amanhã; no {nv} sobram 8.")
    r = chamar("entregar_encomenda", cliente="joão", lotes=[{"lote": nn, "unidades": 10}])
    assert f"De onde sai: 10 unidades de Coxinha 150 g cru congelado: 10 do {nn}" in falavel(r["confirmar"], velho)
    f = confirmar(r)
    assert f"Ficaram 18 unidades do {nv}" in f["dito"]
    assert (saldo_lote(velho, "congelado"), saldo_lote(novo, "congelado")) == (18, 30)


# --- contagem e perda com destino -------------------------------------------------------

def test_contar_lote_propoe_e_so_grava_com_o_sim(coxinha, unidade, dois_lotes):
    velho, novo = dois_lotes
    nv = nome_lote(velho)
    r = chamar("contar_lote", produto="coxinha", lote=nv, contado=15, motivo="contei o freezer")
    assert falavel(r["confirmar"], velho) == (
        f"Contagem do {nv} de Coxinha 150 g, cru, congelado: o sistema tinha 18 unidades e foi contado 15 "
        "unidades; ajusta 3 unidades a menos (1 real e 80 centavos em mercadoria). Confirma?")
    assert saldo_lote(velho, "congelado") == 18
    confirmar(r)
    assert saldo_lote(velho, "congelado") == 15
    assert Movimento.objects.get(tipo="ajuste_contagem").motivo == "Contagem: contei o freezer"
    assert chamar("contar_lote", produto="coxinha", lote=nv, contado=15, motivo="")["erro"].startswith(
        "Qual o motivo da contagem?")
    igual = chamar("contar_lote", produto="coxinha", lote=nv, contado=15, motivo="de novo")
    assert "Bate: nada muda no estoque" in igual["confirmar"]


def test_perda_com_destino(coxinha, unidade, dois_lotes):
    velho, _ = dois_lotes
    r = chamar("registrar_perda", produto="coxinha", lote=nome_lote(velho), quantidade=3, motivo="almoço",
               destino="consumo da equipe")
    assert r["confirmar"].startswith(f"Dar para consumo da equipe 3 unidades de Coxinha 150 g, {nome_lote(velho)}")
    confirmar(r)
    assert Movimento.objects.get(tipo="perda").destino == "consumo_equipe"
    assert chamar("registrar_perda", produto="coxinha", lote=nome_lote(velho), quantidade=1, motivo="x",
                  destino="vender na feira")["erro"].startswith("'destino' deve ser")


# --- conferência do vencido ------------------------------------------------------------

def _conferencia(coxinha):
    venc = lote(coxinha, 18, validade=dia(-1), feito=dia(-5), codigo="CF-1")
    rodar_rotina()
    return venc, Decisao.objects.get(origem="lotes_vencidos", vigente=True)


def test_conferencia_do_vencido_e_dita_como_pergunta(coxinha, unidade):
    venc, d = _conferencia(coxinha)
    caixa = chamar("ver_decisoes", origem="vencido")
    [item] = caixa["itens"]
    assert falavel(item["texto"], venc) == (
        f"Conferência do vencido: o {nome_lote(venc)} de Coxinha 150 g, cru, congelado, venceu ontem com 18 "
        "unidades no estoque. Ainda estão aí? Já foram vendidas, estão aqui ou não sabe?")
    assert f"Número {d.id}, aviso: Conferência do vencido" in caixa["texto"]
    assert falavel(chamar("ver_decisao", decisao_id=d.id)["texto"], venc)


def test_conferencia_ja_foram_vendidas_volta_o_lote_para_a_venda_com_data(coxinha, unidade):
    venc, d = _conferencia(coxinha)
    r = chamar("conferir_vencido", decisao_id=d.id, resposta="já foram vendidas")
    assert r["proximo"] == "registrar_venda" and r["lote_id"] == venc.id and r["lote"] == nome_lote(venc)
    v = chamar("registrar_venda", itens=[{"produto": "coxinha", "quantidade": 18,
                                          "lotes": [{"lote_id": r["lote_id"], "unidades": 18}]}], data="anteontem")
    assert "Atenção" not in v["confirmar"]  # anteontem ainda estava na validade: sem motivo
    confirmar(v)
    assert saldo_lote(venc, "congelado") == 0 and Venda.objects.get().data == dia(-2)


def test_conferencia_estao_aqui_pede_destino_e_motivo(coxinha, unidade):
    venc, d = _conferencia(coxinha)
    falta = chamar("conferir_vencido", decisao_id=d.id, resposta="estão aqui")
    assert falta["erro"].startswith("Estão aqui: pergunte o destino") and "o motivo" in falta["erro"]
    r = chamar("conferir_vencido", decisao_id=d.id, resposta="estão aqui", destino="descarte",
               motivo="passou da validade")
    assert falavel(r["confirmar"], venc).startswith(f"Descartar 18 unidades de Coxinha 150 g, {nome_lote(venc)}")
    confirmar(r)
    m = Movimento.objects.get(tipo="perda")
    assert (m.destino, m.motivo, saldo_lote(venc, "congelado")) == ("descarte", "passou da validade", 0)


def test_conferencia_nao_sei_conta_e_ajusta(coxinha, unidade):
    venc, d = _conferencia(coxinha)
    assert chamar("conferir_vencido", decisao_id=d.id, resposta="não sei")["erro"].startswith("Peça para contar")
    r = chamar("conferir_vencido", decisao_id=d.id, resposta="nao sei", contado=12)
    assert "o sistema tinha 18 unidades e foi contado 12 unidades; ajusta 6 unidades a menos" in r["confirmar"]
    confirmar(r)
    assert saldo_lote(venc, "congelado") == 12
    assert Movimento.objects.get(tipo="ajuste_contagem").motivo == f"Contagem: conferência do vencido (número {d.id})"
    # outra origem não é conferência (aqui, a de validade perto de vencer)
    lote(coxinha, 5, validade=dia(1), feito=dia(-1))
    rodar_rotina()
    outra = Decisao.objects.get(origem="lotes_vencendo", vigente=True)
    assert chamar("conferir_vencido", decisao_id=outra.id, resposta="não sei")["erro"].endswith(
        "não é conferência de vencido.")
    # e o texto dela fala o lote pelo nome, não pelo código
    assert "no lote do dia" in chamar("ver_decisao", decisao_id=outra.id)["texto"]



def test_alerta_de_validade_so_fala_vencido_e_o_que_vence_hoje(coxinha, unidade):
    assert chamar("ver_alerta_validade") == {"tem_alerta": False, "total": 0, "itens": [], "texto": ""}
    lote(coxinha, 5, validade=dia(2), feito=dia(-1))  # vence depois de amanhã: não entra no alerta
    rodar_rotina()
    assert chamar("ver_alerta_validade")["tem_alerta"] is False
    hoje_ = lote(coxinha, 7, validade=dia(0), feito=dia(-3))
    venc = lote(coxinha, 18, validade=dia(-1), feito=dia(-5))
    rodar_rotina()
    r = chamar("ver_alerta_validade")
    assert (r["tem_alerta"], r["total"]) == (True, 2) and r["texto"].startswith("Atenção à validade. ")
    assert [i["origem"] for i in r["itens"]] == ["lotes_vencidos", "lotes_vencendo"]
    assert nome_lote(venc) in r["texto"] and "vence hoje" in r["texto"] and nome_lote(hoje_) in r["texto"]
    assert r["texto"].endswith(f"Coxinha 150 g vence hoje: 7 unidades no {nome_lote(hoje_)}, congelado. É o último dia: "
                               "o que vai fazer com isso? Ainda dá para vender hoje; a partir de amanhã só sai com "
                               "motivo.")


# --- resumo do dia ----------------------------------------------------------------------

def test_resumo_fala_os_lotes_deixados(coxinha, unidade):
    velho = lote(coxinha, 18, validade=dia(10), feito=dia(-5))
    novo = lote(coxinha, 40, validade=dia(20), feito=dia(-3))
    registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 5, "lotes": [{"lote_id": novo.id,
                                                                                    "unidades": 5}]}], autor="balcao")
    r = chamar("ver_resumo_do_dia")
    [a] = [x for x in r["assuntos"] if x["assunto"] == "lotes_deixados"]
    assert falavel(a["texto"], velho) == (f"Venda primeiro: 18 unidades de Coxinha 150 g do {nome_lote(velho)}, "
                                          f"congelado, que vence {quando(dia(10))}.")
    rodar_rotina()
    caixa = chamar("ver_decisoes", origem="deixado")
    assert caixa["itens"][0]["origem_texto"] == "lote deixado para trás"


# --- produção: ingrediente vencido fixado na pesagem --------------------------------------

def test_ingrediente_vencido_pesado_pelo_lote_so_conclui_com_motivo(bolinha):
    from estoque.models import CriterioValidade
    from estoque.servicos import entrada_manual
    from producao.servicos import iniciar_producao

    farinha = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    venc = entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra",
                          validade=dia(-1), lote_codigo="FAR-1", autor="dono")["lote_id"]
    entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra",
                   validade=dia(30), autor="dono")
    venc = Lote.objects.get(id=venc)
    Lote.objects.filter(id=venc.id).update(criado_em=timezone.make_aware(dt.datetime.combine(dia(-4), dt.time(9))))
    venc.refresh_from_db()
    nv = nome_lote(venc)
    iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")
    p = chamar("registrar_peso", item="farinha", quantidade=1, unidade="kg", lote=nv)
    assert falavel(p["dito"], venc).startswith(f"Farinha de trigo: 1 kg registrado, {nv}.")
    sem = chamar("concluir_producao", quantidade_boa=10, conservacao="resfriado")
    assert sem["precisa_motivo"] and nv in sem["erro"] and falavel(sem["erro"], venc)
    r = chamar("concluir_producao", quantidade_boa=10, conservacao="resfriado",
               motivo_vencido="farinha lacrada, o dono conferiu")
    assert r["confirmar"].endswith(f"Atenção, lote vencido: o {nv} de Farinha de trigo venceu ontem; vai com o "
                                   "motivo: farinha lacrada, o dono conferiu. Confirma?")
    confirmar(r)
    assert Movimento.objects.get(lote=venc, quantidade__lt=0).motivo_vencido == "farinha lacrada, o dono conferiu"
