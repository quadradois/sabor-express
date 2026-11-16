"""Plano 10: acabamento por tipo de salgado (frito ou assado), forma "assado" e as três categorias de venda."""

import datetime as dt
import html as _html
import re
import uuid
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Fornecedor, Item
from cadastros.servicos import criar_tamanho, definir_acabamento, salvar_cliente
from compras.servicos import registrar_compra
from custos.fichas import custo_estimado
from estoque.categorias import acabamento, categoria, forma_estado
from estoque.etiquetas import dados_etiqueta
from estoque.models import ESTADOS, FORMAS, CriterioValidade, Lote, Movimento
from estoque.servicos import entrada_manual, saldo_lote
from fichas.models import ComponenteItem, Etapa, Ficha, Proporcao
from nucleo.models import RegistroOperacao
from nucleo.operacoes import RegraViolada
from producao.fritura import registrar_fritura
from producao.models import Fritura, Producao
from producao.servicos import concluir_producao, iniciar_producao, usar_previsto_restantes
from vendas.consultas import estoque_para_venda, frituras, necessidade_producao, sobras_fritas
from vendas.lotes import separacao_venda
from vendas.models import Apresentacao, Reserva
from vendas.servicos import criar_encomenda, entregar_encomenda, registrar_venda, salvar_apresentacao

pytestmark = pytest.mark.django_db
HOJE = timezone.localdate()


def dia(n):
    return HOJE + dt.timedelta(days=n)


def limpo(r):
    return " ".join(re.sub(r"<[^>]+>", " ", _html.unescape(r.content.decode())).split())


@pytest.fixture
def esfirra():
    """Esfirra 100 g: tipo de acabamento assado, sem referência de óleo; farinha comprada a R$ 5,00 o kg."""
    farinha = Item.objects.create(nome="Farinha especial", tipo="ingrediente", unidade_base="g", controla_validade=False)
    massa = Ficha.objects.create(nome="Massa de esfirra", tipo="preparacao", rendimento_g=D("1000"))
    ComponenteItem.objects.create(ficha=massa, item=farinha, quantidade=D("1000"), ordem=1)
    ficha = Ficha.objects.create(nome="Esfirra", tipo="produto", acabamento="assado")
    Proporcao.objects.create(ficha=ficha, preparacao=massa, percentual=D("100"), ordem=1)
    Etapa.objects.create(ficha=ficha, ordem=1, instrucao="Abra e recheie as esfirras")
    registrar_compra(fornecedor_id=Fornecedor.objects.create(nome="Atacadão").id, data_compra=HOJE, total=D("50"),
                     condicao="a_vista", autor="dono",
                     linhas=[{"item_id": farinha.id, "quantidade": D("10"), "unidade": "kg", "valor": D("50")}])
    r = criar_tamanho(ficha_id=ficha.id, peso_g=D("100"), indireto_ref_un=D("0.10"), autor="teste")
    return Item.objects.get(id=r["item_id"])


def lote(produto, n, *, validade, forma="cru", estado="congelado", custo="0.60", codigo=""):
    l = Lote.objects.create(item=produto, codigo=codigo, forma=forma, validade=validade, custo_unitario=D(custo))
    Movimento.objects.create(tipo="entrada_producao", item=produto, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado=estado, validade=validade)
    return l


def apresentacao(produto, nome="unidade", preco="3", forma="cru", estado="congelado"):
    return salvar_apresentacao(produto_id=produto.id, nome=nome, forma=forma, estado=estado, unidades=1,
                               preco_varejo=D(preco), autor="dono")["apresentacao_id"]


# ---------- a função única das categorias ----------

def test_categoria_em_todas_as_combinacoes():
    assert {(f, e): categoria(f, e) for f, _ in FORMAS for e, _ in ESTADOS} == {
        ("cru", "congelado"): "congelado", ("frito", "fresco"): "frito", ("assado", "fresco"): "assado",  # as três
        ("cru", "resfriado"): "resfriado", ("cru", "fresco"): "cru",  # bastidor
        ("frito", "resfriado"): "frito resfriado", ("frito", "congelado"): "frito congelado",
        ("assado", "resfriado"): "assado resfriado", ("assado", "congelado"): "assado congelado"}
    assert categoria("cru", "") == "cru" and categoria("", "congelado") == "congelado" and categoria("", "") == ""


def test_categoria_dita_volta_para_forma_e_conservacao():
    assert forma_estado("congelado") == ("cru", "congelado")
    assert forma_estado("frito") == ("frito", "fresco") and forma_estado("assado") == ("assado", "fresco")
    assert forma_estado("resfriado") == ("cru", "resfriado") and forma_estado("grelhado") is None


def test_filtro_de_tela_e_nomes_dos_modelos(esfirra, bolinha):
    from web.templatetags.formato import categoria as filtro
    assert (filtro("cru", "congelado"), filtro("assado", "fresco"), filtro("frito", "fresco")) == (
        "congelado", "assado", "frito")
    a = Apresentacao.objects.get(id=apresentacao(esfirra, "unidade assada", forma="assado", estado="fresco"))
    c = Apresentacao.objects.get(id=apresentacao(bolinha))
    assert str(a) == "Esfirra 100 g — unidade assada (assado)" and str(c) == "Bolinha 100 g — unidade (congelado)"
    cv = CriterioValidade.objects.create(produto=esfirra, forma="assado", estado="fresco", dias=1)
    assert "assado" in str(cv) and "fresco" not in str(cv)
    l = lote(esfirra, 5, validade=dia(1), forma="assado", estado="fresco")
    assert dados_etiqueta(l, "fresco")["categoria"] == "Assado"
    assert dados_etiqueta(lote(esfirra, 5, validade=dia(9)), "congelado")["categoria"] == "Congelado"


# ---------- acabamento por tipo ----------

def test_acabamento_mora_na_ficha_e_vale_para_todos_os_tamanhos(esfirra, bolinha):
    assert Ficha._meta.get_field("acabamento").default == "frito"
    assert (acabamento(bolinha), acabamento(esfirra)) == ("frito", "assado")
    r = criar_tamanho(ficha_id=esfirra.ficha_id, peso_g=D("30"), autor="teste")
    assert r["acabamento"] == "assado" and acabamento(Item.objects.get(id=r["item_id"])) == "assado"
    sem_ficha = Item.objects.create(nome="Empada", tipo="produto", unidade_base="un")
    assert acabamento(sem_ficha) == "frito"  # produto sem ficha: o padrão


def test_definir_acabamento_registra_e_recusa_o_que_nao_existe(bolinha):
    r = definir_acabamento(ficha_id=bolinha.ficha_id, acabamento="assado", autor="dono")
    assert (r["antes"], r["acabamento"], r["ficha"]) == ("frito", "assado", "Bolinha")
    bolinha.refresh_from_db()
    assert acabamento(bolinha) == "assado"
    assert RegistroOperacao.objects.filter(nome="definir_acabamento", autor="dono").count() == 1
    with pytest.raises(RegraViolada, match="frito ou assado"):
        definir_acabamento(ficha_id=bolinha.ficha_id, acabamento="grelhado", autor="dono")
    massa = bolinha.ficha.proporcoes.get().preparacao
    with pytest.raises(RegraViolada, match="ficha de produto"):
        definir_acabamento(ficha_id=massa.id, acabamento="assado", autor="dono")


def test_acabamento_nao_muda_com_estoque_preco_ou_producao_do_antigo(esfirra):
    def mudar():
        return definir_acabamento(ficha_id=esfirra.ficha_id, acabamento="frito", autor="dono")

    pronto = lote(esfirra, 5, validade=dia(1), forma="assado", estado="fresco")
    with pytest.raises(RegraViolada, match="Ainda há 'Esfirra' assado no estoque"):
        mudar()
    Movimento.objects.create(tipo="perda", item=esfirra, lote=pronto, quantidade=-5, quantidade_informada=5,
                             unidade_informada="un", fator=1, motivo="sobra", estado="fresco")
    a = apresentacao(esfirra, "unidade assada", forma="assado", estado="fresco")
    with pytest.raises(RegraViolada, match="tem preço de assado na tabela"):
        mudar()
    Apresentacao.objects.filter(id=a).update(ativo=False)
    entrada_manual(item_id=Item.objects.get(nome="Farinha especial").id, quantidade=D("2"), unidade="kg",
                   custo_total=D("10"), motivo="compra", autor="dono")
    iniciar_producao(produto_id=esfirra.id, unidades=10, forma="assado", autor="dono")
    with pytest.raises(RegraViolada, match="produção de 'Esfirra' assado em andamento"):
        mudar()
    Producao.objects.update(status="cancelada")
    lote(esfirra, 5, validade=dia(9))  # cru congelado não trava: vale para os dois acabamentos
    assert mudar()["acabamento"] == "frito"
    # a mesma trava vale para quem edita a ficha pelo admin
    ficha = Ficha.objects.get(id=esfirra.ficha_id)
    lote(esfirra, 3, validade=dia(1), forma="frito", estado="fresco")
    ficha.acabamento = "assado"
    with pytest.raises(ValidationError, match="frito no estoque"):
        ficha.full_clean()


# ---------- trava frito × assado ----------

def test_trava_frito_x_assado_na_producao_no_preco_e_na_validade(esfirra, bolinha):
    entrada_manual(item_id=Item.objects.get(nome="Farinha especial").id, quantidade=D("2"), unidade="kg",
                   custo_total=D("10"), motivo="compra", autor="dono")
    msg = "'Esfirra 100 g' é assado, não frito: o acabamento desse salgado é assado. Use cru ou assado."
    with pytest.raises(RegraViolada, match=re.escape(msg)):
        iniciar_producao(produto_id=esfirra.id, unidades=10, forma="frito", autor="dono")
    with pytest.raises(RegraViolada, match=re.escape(msg)):
        apresentacao(esfirra, "unidade frita", forma="frito", estado="fresco")
    with pytest.raises(RegraViolada, match="'Bolinha 100 g' é frito, não assado"):
        apresentacao(bolinha, "unidade assada", forma="assado", estado="fresco")
    with pytest.raises(ValidationError, match="é assado, não frito"):
        CriterioValidade(produto=esfirra, forma="frito", estado="fresco", dias=1).full_clean()
    CriterioValidade(produto=esfirra, forma="assado", estado="fresco", dias=1).full_clean()
    CriterioValidade(produto=esfirra, forma="cru", estado="congelado", dias=90).full_clean()
    assert not Producao.objects.exists() and not Apresentacao.objects.exists()


# ---------- produção direta de assado ----------

def test_producao_de_assado_tem_forno_e_nao_soma_oleo(esfirra):
    entrada_manual(item_id=Item.objects.get(nome="Farinha especial").id, quantidade=D("2"), unidade="kg",
                   custo_total=D("10"), motivo="compra", autor="dono")
    CriterioValidade.objects.create(produto=esfirra, forma="assado", estado="fresco", dias=1)
    assert esfirra.oleo_ref_un is None  # assado não pede a referência de óleo (o frito pede)
    p = iniciar_producao(produto_id=esfirra.id, unidades=10, forma="assado", autor="dono")["producao_id"]
    ultima = Producao.objects.get(id=p).etapas[-1]
    assert (ultima["bloco"], ultima["instrucao"]) == ("Forno", "Asse as 10 unidades.")
    usar_previsto_restantes(producao_id=p, autor="dono")
    r = concluir_producao(producao_id=p, quantidade_boa=10, estado="fresco", autor="dono")
    l = Lote.objects.get(id=r["lote_id"])
    # 1 kg de farinha a R$ 5,00 o kg ÷ 10 unidades: só ingrediente, sem óleo
    assert (l.forma, l.custo_unitario, l.validade) == ("assado", D("0.5000"), dia(1))
    assert [(e["forma"], e["estado"], e["livre"]) for e in estoque_para_venda()] == [("assado", "fresco", 10)]


# ---------- finalização: assar ----------

def test_finalizacao_de_assado_gera_lote_assado_sem_oleo(esfirra):
    cru = lote(esfirra, 50, validade=dia(30), custo="0.60", codigo="K1")
    with pytest.raises(RegraViolada, match="Sem critério de validade"):
        registrar_fritura(lote_id=cru.id, estado="congelado", quantidade=40, boas=38, perda_motivo="queimou",
                          autor="dono")
    CriterioValidade.objects.create(produto=esfirra, forma="assado", estado="fresco", dias=1)
    with pytest.raises(RegraViolada, match="motivo das perdas"):
        registrar_fritura(lote_id=cru.id, estado="congelado", quantidade=40, boas=38, autor="dono")
    r = registrar_fritura(lote_id=cru.id, estado="congelado", quantidade=40, boas=38, perda_motivo="queimou",
                          autor="dono")
    pronto = Lote.objects.get(id=r["lote_id"])
    # 40 × 0,60 = 24,00, sem óleo; ÷ 38 boas = 0,6316 (a coxinha, com óleo de 0,05, daria 26,00 e 0,6842)
    assert (r["forma"], pronto.forma, D(r["custo_total"]), pronto.custo_unitario) == (
        "assado", "assado", D("24.00"), D("0.6316"))
    assert pronto.codigo == f"{HOJE:%y%m%d}-A{Fritura.objects.get().id}" and pronto.validade == dia(1)
    assert (saldo_lote(cru, "congelado"), saldo_lote(pronto, "fresco")) == (10, 38)
    f = Fritura.objects.get()
    assert (f.quantidade, f.boas, f.perdas, f.perda_motivo) == (40, 38, 2, "queimou")
    assert [x["forma"] for x in frituras()] == ["assado"]
    [s] = sobras_fritas()
    assert (s["forma"], s["saldo"]) == ("assado", 38)
    with pytest.raises(RegraViolada, match="salgado cru"):
        registrar_fritura(lote_id=pronto.id, estado="fresco", quantidade=1, boas=1, autor="dono")


def test_finalizacao_de_frito_continua_pedindo_e_somando_o_oleo(bolinha):
    CriterioValidade.objects.create(produto=bolinha, forma="frito", estado="fresco", dias=1)
    cru = lote(bolinha, 50, validade=dia(30), custo="0.60")
    r = registrar_fritura(lote_id=cru.id, estado="congelado", quantidade=40, boas=38, perda_motivo="estourou",
                          autor="dono")
    pronto = Lote.objects.get(id=r["lote_id"])
    assert (pronto.forma, D(r["custo_total"]), pronto.custo_unitario) == ("frito", D("26.00"), D("0.6842"))
    assert pronto.codigo == f"{HOJE:%y%m%d}-F{Fritura.objects.get().id}"
    bolinha.oleo_ref_un = None
    bolinha.save()
    with pytest.raises(RegraViolada, match="óleo"):
        registrar_fritura(lote_id=cru.id, estado="congelado", quantidade=5, boas=5, autor="dono")


# ---------- custo ----------

def test_custo_do_assado_nao_soma_oleo(esfirra, bolinha):
    c = custo_estimado(produto_id=esfirra.id)
    # 100 g de massa a R$ 0,005 o grama = 0,50; indiretos 0,10; o forno não soma óleo
    assert (c["acabamento"], c["ingredientes"], c["indiretos"]) == ("assado", D("0.5000"), D("0.10"))
    assert (c["oleo"], c["custo_frito"]) == (None, None)
    assert c["custo_cru"] == c["custo_assado"] == D("0.6000")
    # mesmo com uma referência de óleo esquecida no tamanho, o assado não soma
    esfirra.oleo_ref_un = D("0.05")
    esfirra.save()
    c = custo_estimado(produto_id=esfirra.id)
    assert (c["oleo"], c["custo_frito"], c["custo_assado"]) == (None, None, D("0.6000"))
    f = custo_estimado(produto_id=bolinha.id)
    assert (f["acabamento"], f["oleo"], f["custo_assado"]) == ("frito", D("0.05"), None)


# ---------- venda, encomenda, reserva e separação de assado ----------

def test_venda_e_encomenda_de_assado(esfirra):
    CriterioValidade.objects.create(produto=esfirra, forma="assado", estado="fresco", dias=1)
    a = apresentacao(esfirra, "unidade assada", "5", forma="assado", estado="fresco")
    cong = apresentacao(esfirra, "unidade", "3")
    pronto = lote(esfirra, 10, validade=dia(1), forma="assado", estado="fresco", custo="0.63")
    cru = lote(esfirra, 20, validade=dia(30))
    assert {(e["forma"], e["estado"]): e["livre"] for e in estoque_para_venda()} == {
        ("assado", "fresco"): 10, ("cru", "congelado"): 20}
    sep = separacao_venda(itens=[{"apresentacao_id": a, "quantidade": 4}])
    assert sep["linhas"][0]["texto"].startswith("4 un de Esfirra 100 g assado: 4 do lote do dia")
    v = registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 4}], condicao="a_vista", autor="dono")
    assert D(v["total"]) == D("20") and (saldo_lote(pronto, "fresco"), saldo_lote(cru, "congelado")) == (6, 20)
    with pytest.raises(RegraViolada, match=r"Só há 6 un de 'Esfirra 100 g' assado para vender \(pedido: 7 un\)"):
        registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 7}], condicao="a_vista", autor="dono")
    joao = salvar_cliente(nome="João", autor="dono")["cliente_id"]
    e = criar_encomenda(cliente_id=joao, entrega_data=dia(1), autor="dono",
                        itens=[{"apresentacao_id": a, "quantidade": 8}, {"apresentacao_id": cong, "quantidade": 5}])
    # reserva o assado que há (6) e o congelado todo; faltam 2 assadas para produzir
    assert sorted((r.lote.forma, r.quantidade) for r in Reserva.objects.filter(situacao="ativa")) == [
        ("assado", 6), ("cru", 5)]
    [n] = necessidade_producao(dias=3)
    assert (n["forma"], n["estado"], n["falta"]) == ("assado", "fresco", 2)
    with pytest.raises(RegraViolada, match="Falta reservar 2 un de 'Esfirra 100 g' assado"):
        entregar_encomenda(encomenda_id=e["encomenda_id"], condicao="a_vista", autor="dono")


# ---------- telas ----------

def enviar(client, rota, **dados):
    return client.post(reverse(rota), {"chave": uuid.uuid4().hex, **dados}, follow=True)


def test_tela_do_acabamento_e_o_fallback(client, dono, esfirra, bolinha):
    t = limpo(client.get(reverse("referencias")))
    assert "Acabamento de cada salgado" in t and "Esfirra" in t and "Bolinha" in t
    t = limpo(enviar(client, "referencias", ficha=bolinha.ficha_id, acabamento="assado"))
    bolinha.refresh_from_db()
    assert acabamento(bolinha) == "assado" and "Bolinha" in t and "assado" in t
    lote(bolinha, 3, validade=dia(1), forma="assado", estado="fresco")
    t = limpo(enviar(client, "referencias", ficha=bolinha.ficha_id, acabamento="frito"))
    bolinha.refresh_from_db()
    assert "Ainda há 'Bolinha' assado no estoque" in t and acabamento(bolinha) == "assado"
    assert "frito ou assado" in limpo(enviar(client, "referencias", ficha=bolinha.ficha_id, acabamento="grelhado"))


def test_tela_de_finalizacao_serve_para_assar(client, dono, esfirra, bolinha):
    CriterioValidade.objects.create(produto=esfirra, forma="assado", estado="fresco", dias=1)
    cru = lote(esfirra, 20, validade=dia(30), codigo="K1")
    t = limpo(client.get(reverse("fritura")))
    assert "Finalização (fritar ou assar)" in t
    t = limpo(client.get(reverse("fritura"), {"produto": esfirra.id}))
    assert "Assar: registrar" in t and "Fritar: registrar" not in t
    assert "Esfirra 100 g é assado : vai ao forno, sem óleo no custo." in t and "Quantas foram assadas" in t
    lote(bolinha, 20, validade=dia(30))
    assert "Fritar: registrar" in limpo(client.get(reverse("fritura"), {"produto": bolinha.id}))
    d = {"chave": "a1", "produto": esfirra.id, "porcao": f"{cru.id}|congelado", "quantidade": "10", "boas": "9",
         "perda_motivo": "queimou", "estado_destino": "fresco"}
    t = limpo(client.post(reverse("fritura"), d, follow=True))
    assert "Assado registrado: 9 boas e 1 perdas" in t and "R$ 0,67 por unidade" in t  # 10 × 0,60 ÷ 9, sem óleo
    pronto = Lote.objects.get(forma="assado")
    assert (saldo_lote(cru, "congelado"), saldo_lote(pronto, "fresco")) == (10, 9)
    client.post(reverse("fritura"), d)  # mesma chave: nada em dobro
    assert Lote.objects.filter(forma="assado").count() == 1
    assert "assado em" in limpo(client.get(reverse("sobras"))) and "Sobras fritas e assadas" in limpo(
        client.get(reverse("inicio")))


def test_telas_mostram_a_categoria_e_nao_forma_mais_conservacao(client, dono, esfirra, bolinha):
    apresentacao(esfirra, "unidade assada", "5", forma="assado", estado="fresco")
    apresentacao(bolinha)
    lote(esfirra, 10, validade=dia(1), forma="assado", estado="fresco")
    t = limpo(client.get(reverse("precos")))
    assert "unidade assada (assado, 1 un)" in t and "unidade (congelado, 1 un)" in t
    assert "cru" not in t.lower() and "fresco" not in t.lower()
    c = limpo(client.get(reverse("custos")))
    assert "assado, sem óleo" in c and "Assado (sem óleo): R$ 0,6000" in c
