import json
from decimal import Decimal as D

import pytest
from asgiref.sync import async_to_sync
from mcp.shared.memory import create_connected_server_and_client_session

from agente.ferramentas import criar_servidor
from cadastros.servicos import criar_tamanho
from estoque.servicos import entrada_manual
from producao.servicos import iniciar_producao

pytestmark = pytest.mark.django_db


# async_to_sync roda o cliente num loop à parte e devolve as chamadas
# sync_to_async(thread_sensitive) para esta thread, dentro da transação do teste.
@async_to_sync
async def _sessao(acao):
    async with create_connected_server_and_client_session(criar_servidor()) as s:
        return await acao(s)


def chamar(nome, **args):
    async def acao(s):
        return await s.call_tool(nome, args)
    r = _sessao(acao)
    assert not r.isError, r.content
    return json.loads(r.content[0].text)


@pytest.fixture
def farinha(bolinha):
    return bolinha.ficha.proporcoes.get().preparacao.itens.get().item


def test_lista_as_ferramentas_de_consulta():
    async def acao(s):
        return (await s.list_tools()).tools
    ferramentas = {t.name: t for t in _sessao(acao) if t.annotations.readOnlyHint}
    assert set(ferramentas) >= {"consultar_estoque", "ver_validades", "buscar_produtos",
                                "calcular_receita", "ver_producoes", "ver_producao"}  # compras: test_mcp_agente_compras
    assert ferramentas["calcular_receita"].inputSchema["required"] == ["produto", "unidades"]


def test_estoque_busca_sem_acento(farinha):
    entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra", autor="dono")
    itens = chamar("consultar_estoque", busca="FARÍNHA de trigo")["itens"]
    assert [(i["nome"], i["saldo"]["texto"]) for i in itens] == [("Farinha de trigo", "2 kg")]


def test_receita_pelo_nome_aponta_falta(bolinha, farinha):
    entrada_manual(item_id=farinha.id, quantidade=D("500"), unidade="g", custo_total=D("3"), motivo="compra", autor="dono")
    r = chamar("calcular_receita", produto="bolinha", unidades=10)
    assert r["produto"] == "Bolinha 100 g"
    assert r["da_para_produzir"] is False
    assert r["ingredientes"][0]["falta"]["texto"] == "500 g"


def test_receita_produto_ambiguo_devolve_opcoes(bolinha):
    criar_tamanho(ficha_id=bolinha.ficha.id, peso_g=D("25"), oleo_ref_un=D("0.01"), autor="teste")
    r = chamar("calcular_receita", produto="bolinha", unidades=10)
    assert "erro" in r
    assert sorted(r["opcoes"]) == ["Bolinha 100 g", "Bolinha 25 g"]
    # o nome completo desfaz a ambiguidade
    assert chamar("calcular_receita", produto="bolinha 25 g", unidades=4)["produto"] == "Bolinha 25 g"
    # o jeito dito junto do nome ("frito fresco") não atrapalha
    assert chamar("calcular_receita", produto="Bolinha 25 g frito fresco", unidades=4)["produto"] == "Bolinha 25 g"
    assert "erro" in chamar("calcular_receita", produto="pastel frito", unidades=4)


def test_receita_produto_inexistente(bolinha):
    r = chamar("calcular_receita", produto="pastel", unidades=10)
    assert r == {"erro": "Nenhum produto com o nome 'pastel'."}


def test_producao_em_andamento(bolinha, farinha):
    entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra", autor="dono")
    pid = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"]
    assert [p["id"] for p in chamar("ver_producoes")["producoes"]] == [pid]
    p = chamar("ver_producao", producao_id=pid)
    assert p["etapa_atual"].startswith("mise en place")
    assert p["falta_pesar"][0]["previsto"]["texto"] == "1 kg"


def test_erros_de_entrada_voltam_como_dict(db):
    assert chamar("ver_producao", producao_id=999) == {"erro": "Produção não encontrada."}
    assert "erro" in chamar("ver_producoes", status="pronta")
