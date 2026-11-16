"""Plano 10 na voz: as três categorias (congelado, frito, assado) na entrada e na fala, a finalização que frita ou
assa conforme o salgado e o erro que diz o acabamento quando pedem o outro."""

from decimal import Decimal as D

import pytest

from agente.compras import quando
from cadastros.models import Item
from cadastros.servicos import salvar_cliente
from estoque.models import CriterioValidade, Lote
from estoque.servicos import entrada_manual, saldo_lote
from producao.models import Fritura, Producao
from producao.servicos import usar_previsto_restantes
from tests.test_acabamento import HOJE, apresentacao, dia, esfirra, lote  # noqa: F401
from tests.test_mcp_agente_vendas import chamar, confirmar, falavel, ferramentas, pasta_backup  # noqa: F401
from vendas.models import Encomenda, Venda

pytestmark = pytest.mark.django_db


@pytest.fixture
def balcao(esfirra, bolinha):
    """Esfirra (assado) e Bolinha (frito), cada uma com a unidade congelada e a unidade pronta na tabela, e 50
    unidades cruas congeladas de cada no estoque."""
    CriterioValidade.objects.create(produto=esfirra, forma="assado", estado="fresco", dias=1)
    CriterioValidade.objects.create(produto=bolinha, forma="frito", estado="fresco", dias=1)
    apresentacao(esfirra, "unidade", "3")
    apresentacao(esfirra, "unidade assada", "5", forma="assado", estado="fresco")
    apresentacao(bolinha, "unidade", "2")
    apresentacao(bolinha, "unidade frita", "4", forma="frito", estado="fresco")
    return {"esfirra": lote(esfirra, 50, validade=dia(30), codigo="E1"),
            "bolinha": lote(bolinha, 50, validade=dia(30), codigo="B1")}


def assar(n=40, boas=38):
    return confirmar(chamar("registrar_fritura", produto="esfirra", quantidade=n, boas=boas,
                            motivo_perdas="queimaram"))


def test_total_de_ferramentas_nao_muda_e_a_descricao_fala_em_fritar_ou_assar():
    t = ferramentas()
    assert len(t) == 95 and "registrar_fritura" in t and "registrar_assado" not in t
    d = t["registrar_fritura"].description
    assert "fritar ou assar" in d and "assei 40 esfirras" in d and "não gasta óleo" in d
    assert "cru, frito ou assado" not in t["ver_precos"].description
    assert "congelado, frito ou assado" in t["ver_precos"].description
    assert "frito ou assado" in t["iniciar_producao"].description


def test_assei_quarenta_esfirras_vira_lote_assado_sem_oleo(balcao, esfirra):
    assert chamar("registrar_fritura", produto="esfirra", quantidade=40, boas=38) == {
        "erro": "Informe o motivo das perdas."}
    r = chamar("registrar_fritura", produto="esfirra", quantidade=40, boas=38, motivo_perdas="queimaram")
    # 40 × 60 centavos ÷ 38 boas = 63 centavos: o forno não soma óleo
    assert falavel(r["confirmar"]) == (
        f"Assar 40 unidades de Esfirra 100 g do lote do dia {HOJE.day}, congelado, que vence "
        f"{quando(dia(30))}: 38 boas e 2 perdidas (queimaram). Custo de 63 centavos por unidade assada; o "
        "assado fica fresco e vale até amanhã. Confirma?")
    assert Fritura.objects.count() == 0
    feito = confirmar(r)
    assert feito["dito"].startswith("Feito: Assar 40 unidades de Esfirra 100 g")
    assert (feito["resultado"]["forma"], feito["resultado"]["custo_total"]) == ("assado", "24.00")
    pronto = Lote.objects.get(forma="assado")
    assert (saldo_lote(balcao["esfirra"], "congelado"), saldo_lote(pronto, "fresco")) == (10, 38)
    # a mesma ferramenta continua fritando o que é frito, com óleo: 10 × (60 + 5 centavos) ÷ 10
    f = chamar("registrar_fritura", produto="bolinha", quantidade=10)
    assert f["confirmar"] == (
        f"Fritar 10 unidades de Bolinha 100 g do lote do dia {HOJE.day}, congelado, que vence "
        f"{quando(dia(30))}: 10 boas. Custo de 65 centavos por unidade frita; o frito fica fresco e vale até "
        "amanhã. Confirma?")
    confirmar(f)
    assert chamar("ver_sobras")["texto"] == ("Sobras fritas e assadas: 48 unidades. 10 unidades de Bolinha 100 g "
                                             "fritas hoje; 38 unidades de Esfirra 100 g assadas hoje.")
    assert chamar("ver_estoque_para_venda")["texto"] == (
        "Bolinha 100 g, congelado: 40 unidades para vender; Bolinha 100 g, frito: 10 unidades para vender; "
        "Esfirra 100 g, assado: 38 unidades para vender; Esfirra 100 g, congelado: 10 unidades para vender.")
    assert "Sobra de frito e assado no estoque: 48 unidades de Bolinha 100 g e Esfirra 100 g." in chamar(
        "ver_resumo_do_dia")["texto"]


def test_so_assado_no_estoque_fala_sobras_assadas(balcao):
    assar()
    assert chamar("ver_sobras")["texto"] == ("Sobras assadas: 38 unidades. 38 unidades de Esfirra 100 g assadas "
                                             "hoje.")
    assert "Sobra de assado no estoque: 38 unidades de Esfirra 100 g." in chamar("ver_resumo_do_dia")["texto"]


def test_precos_falam_so_as_tres_categorias(balcao):
    t = falavel(chamar("ver_precos")["texto"])
    assert t == ("Preços: unidade de Bolinha 100 g, congelado, 2 reais, dá para vender 50 agora; unidade frita de "
                 "Bolinha 100 g, frito, 4 reais, dá para vender 0 agora; unidade de Esfirra 100 g, congelado, 3 reais, "
                 "dá para vender 50 agora; unidade assada de Esfirra 100 g, assado, 5 reais, dá para vender 0 agora.")
    assert "cru" not in t and "fresco" not in t


def test_entrada_por_voz_congelado_cru_frito_e_assado(balcao):
    assar()
    confirmar(chamar("registrar_fritura", produto="bolinha", quantidade=10))

    def vender(**item):
        return chamar("registrar_venda", itens=[{"quantidade": 2, **item}])

    assada = ("Vender 2 unidades assadas de Esfirra 100 g, assado, a 5 reais cada. Total 10 reais, à vista. Sai do "
              f"lote do dia {HOJE.day}, que vence amanhã. Confirma?")
    congelada = ("Vender 2 unidades de Esfirra 100 g, congelado, a 3 reais cada. Total 6 reais, à vista. Sai do lote "
                 f"do dia {HOJE.day}. Confirma?")
    # "assado" sozinho é o assado fresco; "congelado" (ou "cru") sozinho é o cru congelado
    assert vender(produto="esfirra", forma="assada")["confirmar"] == assada
    assert vender(produto="esfirra assada")["confirmar"] == assada
    assert vender(produto="esfirra congelada")["confirmar"] == congelada
    assert vender(produto="esfirra", forma="congelado")["confirmar"] == congelada
    assert vender(produto="esfirra", conservacao="congelado")["confirmar"] == congelada
    assert vender(produto="esfirra", forma="cru")["confirmar"] == congelada
    assert vender(produto="bolinha", forma="frito")["confirmar"] == (
        "Vender 2 unidades fritas de Bolinha 100 g, frito, a 4 reais cada. Total 8 reais, à vista. Sai do lote do dia "
        f"{HOJE.day}, que vence amanhã. Confirma?")
    assert vender(produto="bolinha congelada")["confirmar"].startswith(
        "Vender 2 unidades de Bolinha 100 g, congelado, a 2 reais cada.")
    # sem dizer a categoria, pergunta: as opções são as categorias, não forma mais conservação
    assert vender(produto="esfirra") == {
        "erro": "Mais de um jeito de vender 'esfirra'; pergunte qual.",
        "opcoes": ["unidade de Esfirra 100 g, congelado", "unidade assada de Esfirra 100 g, assado"]}
    assert Venda.objects.count() == 0
    v = confirmar(vender(produto="esfirra", forma="assada"))
    assert v["dito"].startswith("Feito: Vender 2 unidades assadas de Esfirra 100 g, assado")
    assert Venda.objects.count() == 1 and saldo_lote(Lote.objects.get(forma="assado"), "fresco") == 36


def test_pedir_frito_de_salgado_assado_diz_o_acabamento_com_opcoes(balcao):
    r = chamar("registrar_venda", itens=[{"produto": "esfirra", "quantidade": 2, "forma": "frita"}])
    assert r == {"erro": "Esfirra é assado, não frito. O que há para vender está nas opções; pergunte qual.",
                 "opcoes": ["unidade de Esfirra 100 g, congelado", "unidade assada de Esfirra 100 g, assado"]}
    salvar_cliente(nome="João", autor="dono")
    r = chamar("criar_encomenda", cliente="joao", dia="amanhã", itens=[{"produto": "bolinha assada", "quantidade": 2}])
    assert r == {"erro": "Bolinha é frito, não assado. O que há para vender está nas opções; pergunte qual.",
                 "opcoes": ["unidade de Bolinha 100 g, congelado", "unidade frita de Bolinha 100 g, frito"]}
    assert chamar("ver_separacao", itens=[{"produto": "esfirra frita", "quantidade": 2}])["erro"].startswith(
        "Esfirra é assado, não frito.")
    assert Venda.objects.count() == 0 and Encomenda.objects.count() == 0


def test_encomenda_separacao_e_perda_de_assado(balcao, esfirra):
    salvar_cliente(nome="João", autor="dono")
    assar()
    s = chamar("ver_separacao", itens=[{"produto": "esfirra assada", "quantidade": 3}])
    assert s["texto"] == (f"3 unidades de Esfirra 100 g assado: 3 do lote do dia {HOJE.day}, que vence amanhã; no "
                          f"lote do dia {HOJE.day} sobram 35.")
    e = chamar("criar_encomenda", cliente="joao", dia="amanhã",
               itens=[{"produto": "esfirra", "forma": "assada", "quantidade": 60}])
    assert falavel(e["confirmar"]) == (
        "Encomenda de João para amanhã, retirada: 60 unidades assadas de Esfirra 100 g, assado, a 5 reais cada. "
        "Total 300 reais. Reserva agora o que há no estoque; falta produzir 22 unidades de Esfirra 100 g assado. "
        "Confirma?")
    amb = chamar("registrar_perda", produto="esfirra", quantidade=3, motivo="caiu")
    assert amb == {
        "erro": "Há mais de um lote de Esfirra 100 g com saldo; pergunte qual (congelado, frito ou assado, ou o dia "
                "do lote).",
        "opcoes": [f"lote do dia {HOJE.day}, assado, 38 un, vence amanhã",
                   f"lote do dia {HOJE.day}, congelado, 10 un, vence {quando(dia(30))}"]}
    p = chamar("registrar_perda", produto="esfirra", forma="assada", quantidade=3, motivo="caiu")
    assert p["confirmar"].startswith(
        f"Dar perda de 3 unidades de Esfirra 100 g, lote do dia {HOJE.day}, assado, 38 un, vence amanhã (motivo: caiu).")
    c = chamar("registrar_perda", produto="esfirra", forma="congelado", quantidade=3, motivo="caiu")
    assert c["confirmar"].startswith(
        f"Dar perda de 3 unidades de Esfirra 100 g, lote do dia {HOJE.day}, congelado, 10 un,")
    confirmar(p)
    assert saldo_lote(Lote.objects.get(forma="assado"), "fresco") == 35


def test_custo_falado_do_assado_nao_tem_oleo(balcao):
    t = falavel(chamar("ver_custo", produto="esfirra")["texto"])
    assert t.startswith("Custo estimado de uma unidade de Esfirra 100 g, pela última compra de cada ingrediente: 50 "
                        "centavos de ingredientes, mais 10 centavos de indiretos, o que dá 60 centavos cru; assado "
                        "custa o mesmo, o forno não soma óleo.")
    assert "frito" not in t


def test_producao_por_voz_segue_o_acabamento(balcao, esfirra):
    entrada_manual(item_id=Item.objects.get(nome="Farinha especial").id, quantidade=D("5"), unidade="kg",
                   custo_total=D("25"), motivo="compra", autor="dono")
    assert chamar("iniciar_producao", produto="esfirra", unidades=10, forma="frito") == {
        "erro": "Esfirra 100 g é assado, não frito. Pergunte se a produção é para guardar cru ou já sai assado.",
        "opcoes": ["cru", "assado"]}
    assert chamar("iniciar_producao", produto="bolinha", unidades=10, forma="assada")["opcoes"] == ["cru", "frito"]
    # "congelado" na produção é o cru que vai para o freezer
    assert chamar("iniciar_producao", produto="esfirra", unidades=10, forma="congelado")["confirmar"] == (
        "Iniciar a produção de 10 Esfirra 100 g, cru. Confirma?")
    r = chamar("iniciar_producao", produto="esfirra", unidades=10, forma="assada")
    assert r["confirmar"] == "Iniciar a produção de 10 Esfirra 100 g, assado. Confirma?"
    confirmar(r)
    p = Producao.objects.get()
    assert p.forma == "assado" and p.etapas[-1]["instrucao"] == "Asse as 10 unidades."
    usar_previsto_restantes(producao_id=p.id, autor="dono")
    c = chamar("concluir_producao", quantidade_boa=10, conservacao="fresco")
    assert c["confirmar"] == (f"Concluir a produção {p.id} de 10 Esfirra 100 g: 10 boas, assado, validade "
                              f"{dia(1):%d/%m/%Y}. Confirma?")
    confirmar(c)
    pronto = Lote.objects.get(forma="assado")
    assert (pronto.custo_unitario, saldo_lote(pronto, "fresco")) == (D("0.5000"), 10)  # só a farinha: sem óleo


def test_criar_tamanho_diz_o_acabamento_do_tipo(balcao):
    r = chamar("criar_tamanho", salgado="esfirra", peso_g=30)
    assert r["confirmar"] == "Criar o tamanho Esfirra 30 g, assado. Confirma?"
    confirmar(r)
    assert Item.objects.get(nome="Esfirra 30 g").ficha.acabamento == "assado"
