import json
from datetime import timedelta
from decimal import Decimal as D

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone
from mcp.shared.memory import create_connected_server_and_client_session

from agente.ferramentas import criar_servidor
from agente.models import Proposta
from cadastros.models import Item
from cadastros.servicos import criar_tamanho
from conftest import item
from estoque.models import CriterioValidade, EtiquetaImpressa, Lote, Movimento
from estoque.servicos import entrada_manual, saldo, saldo_lote
from nucleo.models import RegistroOperacao
from producao.models import Producao
from producao.servicos import cancelar_producao, iniciar_producao

pytestmark = pytest.mark.django_db
hoje = timezone.localdate()


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


def envelhecer():
    """Passa da janela de repetição: a próxima chamada igual vale de novo."""
    RegistroOperacao.objects.update(criado_em=timezone.now() - timedelta(minutes=1))


def confirmar(r):
    assert "confirmar" in r, r
    return chamar("confirmar_proposta", proposta_id=r["proposta_id"])


@pytest.fixture
def farinha(bolinha):
    f = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    entrada_manual(item_id=f.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra", autor="dono")
    return f


@pytest.fixture
def em_andamento(bolinha, farinha):
    return Producao.objects.get(id=iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru",
                                                    autor="dono")["producao_id"])


def test_ferramentas_de_escrita_com_alcada():
    async def acao(s):
        return (await s.list_tools()).tools
    escrita = {t.name for t in _sessao(acao) if not t.annotations.readOnlyHint}
    assert escrita >= {  # compras e contas a pagar: test_mcp_agente_compras
        "registrar_peso", "usar_previsto", "proxima_etapa", "ir_para_etapa", "iniciar_cronometro",
        "parar_cronometro", "registrar_etiqueta",  # nível 1
        "iniciar_producao", "concluir_producao", "cancelar_producao", "mudar_conservacao", "entrada_estoque",
        "criar_tamanho", "confirmar_proposta", "recusar_proposta",  # nível 2
    }


def test_preparo_completo_por_ferramentas(bolinha):
    f = Item.objects.get(nome="Farinha de trigo")
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="congelado", dias=30)

    r = chamar("entrada_estoque", item="farinha", quantidade=2, unidade="kg", custo_total=10, motivo="compra")
    assert r["confirmar"] == "Entrada de 2 kg de Farinha de trigo por R$ 10,00 (motivo: compra). Confirma?"
    assert saldo(f) == 0
    confirmar(r)
    assert saldo(f) == D("2000")

    r = chamar("iniciar_producao", produto="bolinha", unidades=10)
    assert r["confirmar"] == "Iniciar a produção de 10 Bolinha 100 g, cru. Confirma?"
    assert not Producao.objects.exists()
    r = confirmar(r)
    p = Producao.objects.get()
    assert r["dito"] == (f"Feito: Iniciar a produção de 10 Bolinha 100 g, cru. É a produção {p.id}. "
                         "Mise en place: pese os ingredientes. Falta pesar: Farinha de trigo.")

    r = chamar("registrar_peso", item="farinha", quantidade=1.02, unidade="kg")
    assert r["dito"] == "Farinha de trigo: 1,02 kg registrado. Tudo pesado."
    assert p.linhas.get().usado == D("1020")

    assert chamar("proxima_etapa")["dito"] == "Etapa 1 de 2, Massa simples: Sove a massa (5 min)."
    assert chamar("iniciar_cronometro")["dito"] == "Cronômetro de 5 min ligado: Sove a massa."
    assert chamar("parar_cronometro")["dito"] == "Cronômetro desligado: Sove a massa."
    envelhecer()
    assert chamar("proxima_etapa")["dito"] == "Etapa 2 de 2, Montagem: Modele as bolinhas."
    envelhecer()
    assert chamar("proxima_etapa")["dito"].startswith("Fechamento:")

    r = chamar("concluir_producao", quantidade_boa=9, perdas=1, motivo_perdas="rasgou", conservacao="geladeira")
    validade = (hoje + timedelta(days=3)).strftime("%d/%m/%Y")
    assert r["confirmar"] == (f"Concluir a produção {p.id} de 10 Bolinha 100 g: 9 boas, 1 perdida (rasgou), "
                              f"resfriado, validade {validade}. Confirma?")
    assert not Lote.objects.filter(item=bolinha).exists()
    confirmar(r)
    p.refresh_from_db()
    assert (p.status, p.quantidade_boa, p.perdas) == ("concluida", 9, 1)

    r = chamar("registrar_etiqueta", produto="bolinha", conservacao="resfriado")
    assert r["dito"] == f"Impressão de 9 etiquetas registrada: Bolinha 100 g, lote do dia {hoje.day}, resfriado."

    r = chamar("mudar_conservacao", produto="bolinha", para="freezer")
    validade = (hoje + timedelta(days=30)).strftime("%d/%m/%Y")
    assert r["confirmar"] == (f"Passar 9 un de Bolinha 100 g, lote do dia {hoje.day}, de resfriado para congelado, "
                              f"validade {validade}. Confirma?")
    confirmar(r)
    assert (saldo_lote(p.lote, "resfriado"), saldo_lote(p.lote, "congelado")) == (0, 9)

    ops = RegistroOperacao.objects.filter(status="sucesso").exclude(autor="teste")  # o fixture cria o tamanho
    assert {(o.canal, o.autor) for o in ops} == {("agente", "agente-mcp")}
    assert Proposta.objects.filter(estado="confirmada").count() == 4


def test_proposta_nao_grava_nem_deixa_rastro(bolinha, farinha):
    antes = RegistroOperacao.objects.count()
    r = chamar("iniciar_producao", produto="bolinha", unidades=10, forma="frita")
    assert r["confirmar"].endswith("frito. Confirma?")
    assert RegistroOperacao.objects.count() == antes
    assert not Producao.objects.exists()
    proposta = Proposta.objects.get(id=r["proposta_id"])
    assert (proposta.estado, proposta.canal, proposta.operacao) == ("pendente", "agente", "iniciar_producao")


def test_confirmar_duas_vezes_nao_duplica(bolinha, farinha):
    r = chamar("iniciar_producao", produto="bolinha", unidades=10)
    a = confirmar(r)
    b = confirmar(r)
    assert a["resultado"] == b["resultado"]
    assert Producao.objects.count() == 1
    assert RegistroOperacao.objects.filter(nome="iniciar_producao").count() == 1


def test_proposta_recusada(bolinha, farinha):
    r = chamar("iniciar_producao", produto="bolinha", unidades=10)
    assert chamar("recusar_proposta", proposta_id=r["proposta_id"])["dito"] == (
        "Certo, não gravei nada: Iniciar a produção de 10 Bolinha 100 g, cru.")
    assert "recusada" in chamar("confirmar_proposta", proposta_id=r["proposta_id"])["erro"]
    assert not Producao.objects.exists()


def test_proposta_expirada(bolinha, farinha):
    r = chamar("iniciar_producao", produto="bolinha", unidades=10)
    Proposta.objects.update(expira_em=timezone.now() - timedelta(seconds=1))
    assert "expirou" in chamar("confirmar_proposta", proposta_id=r["proposta_id"])["erro"]
    assert Proposta.objects.get().estado == "expirada"
    assert not Producao.objects.exists()


def test_confirmada_nao_pode_ser_recusada(bolinha, farinha):
    r = chamar("iniciar_producao", produto="bolinha", unidades=10)
    confirmar(r)
    assert "já foi confirmada" in chamar("recusar_proposta", proposta_id=r["proposta_id"])["erro"]


def test_proposta_inexistente(db):
    assert chamar("confirmar_proposta", proposta_id=999) == {"erro": "Proposta não encontrada."}


def test_nucleo_recusa_na_confirmacao_e_proposta_continua_pendente(em_andamento):
    r = chamar("cancelar_producao", motivo="faltou gás")
    cancelar_producao(producao_id=em_andamento.id, motivo="pela tela", autor="dono")
    assert chamar("confirmar_proposta", proposta_id=r["proposta_id"]) == {"erro": "Esta produção já foi encerrada."}
    proposta = Proposta.objects.get()
    assert (proposta.estado, proposta.erro) == ("pendente", "Esta produção já foi encerrada.")
    # a recusa ficou na trilha de auditoria
    assert RegistroOperacao.objects.filter(nome="cancelar_producao", status="erro", canal="agente").exists()


def test_chamada_repetida_pelo_modelo_nao_duplica(em_andamento):
    a = chamar("proxima_etapa")
    b = chamar("proxima_etapa")
    assert "erro" in a and "erro" in b  # falta pesar: o núcleo recusa as duas
    chamar("usar_previsto")
    a, b = chamar("proxima_etapa"), chamar("proxima_etapa")
    assert a["dito"] == b["dito"] and b["repetida"] is True
    em_andamento.refresh_from_db()
    assert em_andamento.etapa_atual == 1
    assert RegistroOperacao.objects.filter(nome="ir_para_etapa", status="sucesso").count() == 1
    envelhecer()  # depois da janela, o mesmo pedido é um pedido novo
    chamar("proxima_etapa")
    em_andamento.refresh_from_db()
    assert em_andamento.etapa_atual == 2


def test_cronometro_repetido_liga_um_so(em_andamento):
    chamar("iniciar_cronometro", minutos=3, nome="forno")
    chamar("iniciar_cronometro", minutos=3, nome="forno")
    chamar("iniciar_cronometro", minutos=4, nome="forno")  # outro pedido: outro tempo
    assert sorted(c.nome for c in em_andamento.cronometros.all()) == ["forno", "forno"]
    r = chamar("parar_cronometro")
    assert "opcoes" in r


def test_etiqueta_repetida_conta_uma_vez(lote_produzido):
    chamar("registrar_etiqueta", produto="bolinha", copias=2)
    r = chamar("registrar_etiqueta", produto="bolinha", copias=2)
    assert r["repetida"] is True
    assert EtiquetaImpressa.objects.count() == 1


def test_producao_omitida_com_mais_de_uma_em_andamento(bolinha, farinha):
    a = iniciar_producao(produto_id=bolinha.id, unidades=5, forma="cru", autor="dono")["producao_id"]
    b = iniciar_producao(produto_id=bolinha.id, unidades=5, forma="cru", autor="dono")["producao_id"]
    r = chamar("registrar_peso", item="farinha", quantidade=500)
    assert r["opcoes"] == [f"Produção {a}: 5 Bolinha 100 g", f"Produção {b}: 5 Bolinha 100 g"]
    assert chamar("registrar_peso", item="farinha", quantidade=500, producao_id=b)["dito"].startswith(
        "Farinha de trigo: 500 g")


def test_ingrediente_em_dois_blocos_pede_qual(coxinha):
    for i in Item.objects.filter(tipo="ingrediente"):
        entrada_manual(item_id=i.id, quantidade=D("10"), unidade="kg" if i.unidade_base == "g" else "L",
                       custo_total=D("50"), motivo="compra", autor="dono")
    p = criar_tamanho(ficha_id=coxinha.id, peso_g=D("100"), autor="dono")
    iniciar_producao(produto_id=p["item_id"], unidades=10, forma="cru", autor="dono")
    r = chamar("registrar_peso", item="farinha de trigo", quantidade=100)
    assert sorted(r["opcoes"]) == ["Farinha de trigo (Empanamento)", "Farinha de trigo (Massa)"]
    assert chamar("registrar_peso", item="farinha empanamento", quantidade=21)["dito"].startswith(
        "Farinha de trigo: 21 g registrado.")


def test_produto_ambiguo_na_proposta(bolinha, farinha):
    criar_tamanho(ficha_id=bolinha.ficha.id, peso_g=D("25"), autor="dono")
    r = chamar("iniciar_producao", produto="bolinha", unidades=10)
    assert sorted(r["opcoes"]) == ["Bolinha 100 g", "Bolinha 25 g"]
    assert not Proposta.objects.exists()


def test_criar_tamanho_por_proposta(bolinha):
    r = chamar("criar_tamanho", salgado="bolinha", peso_g=25)
    assert r["confirmar"] == "Criar o tamanho Bolinha 25 g. Confirma?"
    assert not Item.objects.filter(nome="Bolinha 25 g").exists()
    confirmar(r)
    assert Item.objects.filter(nome="Bolinha 25 g", tipo="produto").exists()


# --- nível 3: o núcleo recusa ----------------------------------------------

def test_nunca_estoque_negativo(lote_produzido):
    r = chamar("mudar_conservacao", produto="bolinha", para="congelado", quantidade=50)
    assert r == {"erro": "Só há 9 un em resfriado."}
    assert not Proposta.objects.exists()


def test_nunca_iniciar_sem_estoque(bolinha):
    r = chamar("iniciar_producao", produto="bolinha", unidades=10)
    assert r["erro"].startswith("Falta 1 kg de 'Farinha de trigo'")
    assert not Proposta.objects.exists()


def test_nunca_alterar_producao_concluida(lote_produzido):
    p = Producao.objects.get()
    assert chamar("registrar_peso", item="farinha", quantidade=1, producao_id=p.id) == {
        "erro": "Esta produção já foi encerrada."}
    assert chamar("ir_para_etapa", etapa=1, producao_id=p.id) == {"erro": "Esta produção já foi encerrada."}
    assert chamar("cancelar_producao", motivo="x", producao_id=p.id) == {"erro": "Esta produção já foi encerrada."}
    assert chamar("concluir_producao", quantidade_boa=1, conservacao="fresco", producao_id=p.id) == {
        "erro": "Esta produção já foi encerrada."}
    # sem id, não há produção em andamento para alterar
    assert chamar("proxima_etapa") == {"erro": "Nenhuma produção em andamento."}


def test_entrada_com_custo_negativo_recusada(farinha):
    r = chamar("entrada_estoque", item="farinha", quantidade=1, unidade="kg", custo_total=-5, motivo="compra")
    assert r == {"erro": "O custo total não pode ser negativo."}


def test_nada_de_apagar_e_dinheiro_so_com_o_sim():
    from agente.ferramentas import REGISTRO
    nomes = {f.nome: f.nivel for f in REGISTRO}
    assert not {n for n in nomes if any(p in n for p in ("apagar", "excluir"))}
    # pagamento é só anotação, e como estorno, espera o "sim" (nível 2)
    assert {n: v for n, v in nomes.items() if "pagamento" in n or "estornar" in n or "recebimento" in n} == {
        "registrar_pagamento": 2, "estornar_pagamento": 2, "estornar_recebimento": 2,
        "registrar_recebimento": 2, "estornar_recebimento_cliente": 2}
    assert {n: v for n, v in nomes.items() if "despesa" in n and v} == {
        "pagar_despesa": 2, "lancar_despesa": 2, "cancelar_despesa": 2, "informar_valor_despesa": 1}
    # 50 até o Plano 4 + 20 de vendas (Plano 6) + 7 de custos (Plano 7) + 11 de despesas e estudo de preço (Plano 8)
    # + 4 de lotes (Plano 9: separação, separação da encomenda, contagem, conferência do vencido)
    assert len(nomes) == 92
