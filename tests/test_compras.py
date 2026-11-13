import datetime as dt
from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model

from cadastros.models import Conversao, Fornecedor, Item
from cadastros.servicos import salvar_fornecedor
from compras.consultas import compras_em_aberto, detalhe_compra, falta_receber, possiveis_duplicatas, ultimo_custo
from compras.models import Compra, LinhaCompra
from compras.servicos import (cancelar_compra, devolver_ao_fornecedor, encerrar_pendencia, estornar_recebimento,
                              receber_bonificacao, receber_compra, registrar_compra)
from estoque.models import Lote, Movimento
from estoque.servicos import saldo, saldo_lote
from financeiro.consultas import avisos_de_ajuste, devido_por_fornecedor, parcelas_em_aberto
from financeiro.models import Conta, Pagamento
from financeiro.servicos import estornar_pagamento
from nucleo.models import RegistroOperacao
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db

HOJE = dt.date(2026, 11, 12)


@pytest.fixture
def atacadao():
    return Fornecedor.objects.get(id=salvar_fornecedor(nome="Atacadão", autor="dono")["fornecedor_id"])


@pytest.fixture
def farinha():
    return Item.objects.create(nome="Farinha de trigo", tipo="ingrediente", unidade_base="g", controla_validade=False)


@pytest.fixture
def oleo():
    return Item.objects.create(nome="Óleo", tipo="insumo", unidade_base="mL", controla_validade=False)


def comprar(fornecedor, linhas, total, **kw):
    kw.setdefault("condicao", "a_prazo")
    if kw["condicao"] == "a_prazo":
        kw.setdefault("parcelas", [{"valor": total, "vencimento": HOJE + dt.timedelta(days=30)}])
    return registrar_compra(fornecedor_id=fornecedor.id, data_compra=HOJE, linhas=linhas, total=total,
                            autor="dono", **kw)


def linha(item, q, un, valor):
    return {"item_id": item.id, "quantidade": D(q), "unidade": un, "valor": D(valor)}


def farinha_10kg(atacadao, farinha, **kw):
    return comprar(atacadao, [linha(farinha, "10", "kg", "60")], D("60"), **kw)


# ---------- registrar compra ----------

def test_custo_unitario_com_rateio_de_frete_e_desconto(atacadao, farinha, oleo):
    # CA-12: farinha 10 kg R$ 60, óleo 5 L R$ 40, frete 10, desconto 5 → R$ 6,30/kg e R$ 8,40/L
    r = comprar(atacadao, [linha(farinha, "10", "kg", "60"), linha(oleo, "5", "L", "40")], D("105"),
                frete=D("10"), desconto=D("5"))
    l_far, l_oleo = LinhaCompra.objects.order_by("ordem")
    assert (l_far.quantidade_base, l_far.custo_unitario) == (D("10000"), D("0.0063"))
    assert (l_oleo.quantidade_base, l_oleo.custo_unitario) == (D("5000"), D("0.0084"))
    receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": l_far.id, "quantidade": D("8")}], autor="dono")
    lote = Lote.objects.get(item=farinha)
    assert lote.custo_unitario * saldo_lote(lote) == D("50.4")  # RN-21: o parcial não muda o custo unitário


def test_conversao_pela_unidade_de_compra(atacadao, farinha):
    with pytest.raises(RegraViolada, match="Cadastre o fator de 'saco'"):  # CA-06
        comprar(atacadao, [linha(farinha, "2", "saco", "50")], D("50"))
    Conversao.objects.create(item=farinha, unidade="saco", fator=D("5000"))
    r = comprar(atacadao, [linha(farinha, "2", "saco", "50")], D("50"))
    l = LinhaCompra.objects.get(id=r["linhas"][0]["linha_id"])
    assert (l.quantidade, l.unidade, l.fator, l.quantidade_base) == (D("2"), "saco", D("5000"), D("10000"))
    receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": l.id, "quantidade": D("1")}], autor="dono")
    m = Movimento.objects.get(tipo="entrada_compra")
    assert (m.quantidade_informada, m.unidade_informada, m.fator, m.quantidade) == (D("1"), "saco", D("5000"), D("5000"))


def test_divergencia_de_total_exige_justificativa(atacadao, farinha):
    # CA-09: itens somam R$ 98 e o documento diz R$ 100
    with pytest.raises(RegraViolada, match=r"somam R\$ 98,00 .* R\$ 100,00 \(diferença de R\$ 2,00\)"):
        comprar(atacadao, [linha(farinha, "10", "kg", "98")], D("100"))
    r = comprar(atacadao, [linha(farinha, "10", "kg", "98")], D("100"), justificativa="taxa da sacola")
    assert Compra.objects.get().justificativa == "taxa da sacola"
    assert Conta.objects.get(id=r["conta_id"]).total == D("100")  # obrigação pelo valor do documento


def test_parcelas_precisam_somar_o_total(atacadao, farinha):
    venc = HOJE + dt.timedelta(days=30)
    with pytest.raises(RegraViolada, match=r"parcelas somam R\$ 50,00 e o total é R\$ 60,00"):
        farinha_10kg(atacadao, farinha, parcelas=[{"valor": D("50"), "vencimento": venc}])
    assert not Compra.objects.exists()  # atômico: nada da compra fica


def test_a_vista_nasce_paga(atacadao, farinha):
    r = farinha_10kg(atacadao, farinha, condicao="a_vista", forma_pagamento="pix")
    pg = Pagamento.objects.get()
    assert (pg.valor, pg.data, pg.forma) == (D("60"), HOJE, "pix")
    assert parcelas_em_aberto() == [] and Conta.objects.get(id=r["conta_id"]).compra_id == r["compra_id"]


@pytest.mark.parametrize("mudar, msg", [
    (lambda f, i: setattr(f, "ativo", False) or f.save(), "fornecedor 'Atacadão' está inativo"),
    (lambda f, i: setattr(i, "ativo", False) or i.save(), "Linha 1: o item 'Farinha de trigo' está inativo"),
    (lambda f, i: Item.objects.filter(id=i.id).update(tipo="produto"), "é produzido aqui, não comprado"),
])
def test_recusas_de_cadastro(atacadao, farinha, mudar, msg):
    mudar(atacadao, farinha)
    with pytest.raises(RegraViolada, match=msg):
        farinha_10kg(atacadao, farinha)


def test_quantidade_e_condicao(atacadao, farinha):
    with pytest.raises(RegraViolada, match="maior que zero"):
        comprar(atacadao, [linha(farinha, "0", "kg", "60")], D("60"))
    with pytest.raises(RegraViolada, match="condição de pagamento"):
        farinha_10kg(atacadao, farinha, condicao="fiado")
    with pytest.raises(RegraViolada, match="Informe ao menos um item"):
        comprar(atacadao, [], D("60"))


def test_documento_repetido_bloqueia_e_mesmo_total_so_alerta(atacadao, farinha):
    r1 = farinha_10kg(atacadao, farinha, documento="NF 123")
    assert r1["alertas"] == []
    with pytest.raises(RegraViolada, match=f"já foi lançado na compra {r1['compra_id']}"):
        farinha_10kg(atacadao, farinha, documento="nf 123")
    r2 = farinha_10kg(atacadao, farinha)  # RN-05 (d): mesmo fornecedor, data e total
    assert r2["alertas"] == [f"Possível duplicata: a compra {r1['compra_id']} é do mesmo fornecedor, "
                             "na mesma data e com o mesmo total."]
    dups = possiveis_duplicatas(fornecedor_id=atacadao.id, data_compra=HOJE, total=D("60"), documento="NF 123")
    assert [(d["compra_id"], d["bloqueia"]) for d in dups] == [(r1["compra_id"], True), (r2["compra_id"], False)]


def test_idempotencia_por_chave(atacadao, farinha):
    # CA-11: aprovar duas vezes → uma compra, uma conta, nenhum movimento duplicado
    r1 = farinha_10kg(atacadao, farinha, chave="aprova-1")
    r2 = farinha_10kg(atacadao, farinha, chave="aprova-1")
    assert r1 == r2 and Compra.objects.count() == 1 and Conta.objects.count() == 1
    lid = r1["linhas"][0]["linha_id"]
    for _ in range(2):
        receber_compra(compra_id=r1["compra_id"], linhas=[{"linha_id": lid, "quantidade": D("4")}],
                       autor="dono", chave="receb-1")
    assert Movimento.objects.count() == 1 and saldo(farinha) == D("4000")


# ---------- recebimento ----------

def test_caminho_feliz_parcial_restante_e_pagamento(atacadao, farinha):
    # CA-10: 10 kg a prazo, recebe 8 kg; depois os 2 kg; depois paga
    r = farinha_10kg(atacadao, farinha)
    cid, lid = r["compra_id"], r["linhas"][0]["linha_id"]
    rr = receber_compra(compra_id=cid, linhas=[{"linha_id": lid, "quantidade": D("8"), "lote_codigo": "F-1"}],
                        autor="dono")
    assert rr["status"] == "parcial" and saldo(farinha) == D("8000")
    [p] = falta_receber()
    assert (p["documentado"], p["recebido"], p["pendente"]) == (D("10000"), D("8000"), D("2000"))
    assert Conta.objects.get().total == D("60")
    assert [c["compra_id"] for c in compras_em_aberto()] == [cid]
    receber_compra(compra_id=cid, linhas=[{"linha_id": lid, "quantidade": D("2000"), "unidade": "g"}], autor="dono")
    assert Compra.objects.get().status == "recebida" and saldo(farinha) == D("10000")
    assert Lote.objects.filter(item=farinha).count() == 2 and falta_receber() == []
    nomes = list(RegistroOperacao.objects.filter(status="sucesso").values_list("nome", flat=True))
    assert nomes == ["salvar_fornecedor", "registrar_compra", "receber_compra", "receber_compra"]  # RN-04
    [parc] = parcelas_em_aberto()
    from financeiro.servicos import registrar_pagamento
    registrar_pagamento(parcela_id=parc["parcela_id"], forma="boleto", autor="dono")
    assert parcelas_em_aberto() == [] and devido_por_fornecedor() == []
    d = detalhe_compra(cid)
    assert d["status"] == "recebida" and d["conta"]["parcelas"][0]["situacao"] == "paga"
    assert [x["quantidade"] for x in d["linhas"][0]["recebimentos"]] == [D("8000"), D("2000")]


def test_excesso_recusado_e_bonificacao_a_custo_zero(atacadao, farinha):
    # CA-42: documentado 10 kg, tenta receber 11 kg
    r = farinha_10kg(atacadao, farinha)
    lid = r["linhas"][0]["linha_id"]
    with pytest.raises(RegraViolada, match="só faltam receber 10 kg.*bonificação"):
        receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": lid, "quantidade": D("11")}], autor="dono")
    with pytest.raises(RegraViolada, match="só faltam receber"):  # a mesma linha duas vezes conta junto
        receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": lid, "quantidade": D("6")},
                                                        {"linha_id": lid, "quantidade": D("6")}], autor="dono")
    assert not Movimento.objects.exists()
    receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": lid, "quantidade": D("10")}], autor="dono")
    b = receber_bonificacao(item_id=farinha.id, quantidade=D("1"), unidade="kg", motivo="veio a mais",
                            compra_id=r["compra_id"], autor="dono")
    lote = Lote.objects.get(id=b["lote_id"])
    assert lote.custo_unitario == 0 and saldo_lote(lote) == D("1000") and saldo(farinha) == D("11000")
    assert Movimento.objects.get(lote=lote).tipo == "bonificacao"


def test_validade_obrigatoria_quando_item_controla(atacadao):
    queijo = Item.objects.create(nome="Queijo", tipo="ingrediente", unidade_base="g")
    r = comprar(atacadao, [linha(queijo, "2", "kg", "80")], D("80"))
    lid = r["linhas"][0]["linha_id"]
    with pytest.raises(RegraViolada, match="Informe a validade de 'Queijo'"):
        receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": lid, "quantidade": D("2")}], autor="dono")
    receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": lid, "quantidade": "2", "lote_codigo": "Q1",
                                                      "validade": "2026-12-01"}], autor="dono")
    lote = Lote.objects.get(item=queijo)
    assert (lote.codigo, lote.sem_lote, lote.validade) == ("Q1", False, dt.date(2026, 12, 1))


def test_linha_de_outra_compra_recusada(atacadao, farinha):
    r1, r2 = farinha_10kg(atacadao, farinha), comprar(atacadao, [linha(farinha, "1", "kg", "6")], D("6"))
    with pytest.raises(RegraViolada, match="não é uma linha desta compra"):
        receber_compra(compra_id=r1["compra_id"], linhas=[{"linha_id": r2["linhas"][0]["linha_id"],
                                                           "quantidade": D("1")}], autor="dono")


def test_complementar_e_encerrar_nao_entregue(atacadao, farinha):
    # CA-39: pendência de 2 kg, chega 1 kg, o resto é encerrado
    r = farinha_10kg(atacadao, farinha)
    cid, lid = r["compra_id"], r["linhas"][0]["linha_id"]
    receber_compra(compra_id=cid, linhas=[{"linha_id": lid, "quantidade": D("8")}], autor="dono")
    receber_compra(compra_id=cid, linhas=[{"linha_id": lid, "quantidade": D("1")}], autor="dono")
    assert falta_receber()[0]["pendente"] == D("1000") and Lote.objects.count() == 2
    with pytest.raises(RegraViolada, match="Informe o motivo"):
        encerrar_pendencia(compra_id=cid, motivo=" ", autor="dono")
    e = encerrar_pendencia(compra_id=cid, motivo="fornecedor sem estoque", autor="dono")
    assert e["status"] == "encerrada" and Compra.objects.get().get_status_display() == "Encerrada com pendência"
    assert Conta.objects.get().total == D("60")  # RN-09: o valor devido não muda
    [aviso] = avisos_de_ajuste()
    assert "1 kg de Farinha de trigo" in aviso["texto"] and "fornecedor sem estoque" in aviso["texto"]
    with pytest.raises(RegraViolada, match="não espera recebimento"):
        receber_compra(compra_id=cid, linhas=[{"linha_id": lid, "quantidade": D("1")}], autor="dono")
    from financeiro.servicos import resolver_aviso
    resolver_aviso(aviso_id=aviso["aviso_id"], observacao="abateu R$ 6 no boleto", autor="dono")
    assert avisos_de_ajuste() == []


def test_estorno_de_recebimento(atacadao, farinha):
    r = farinha_10kg(atacadao, farinha)
    cid, lid = r["compra_id"], r["linhas"][0]["linha_id"]
    rr = receber_compra(compra_id=cid, linhas=[{"linha_id": lid, "quantidade": D("10")}], autor="dono")
    rec_id = rr["recebimentos"][0]["recebimento_id"]
    estornar_recebimento(recebimento_id=rec_id, motivo="lancei na compra errada", autor="dono")
    assert saldo(farinha) == 0 and Compra.objects.get().status == "aprovada"
    assert falta_receber()[0]["pendente"] == D("10000")
    assert Movimento.objects.count() == 2  # o original continua, o estorno anula
    with pytest.raises(RegraViolada, match="já foi estornado"):
        estornar_recebimento(recebimento_id=rec_id, motivo="de novo", autor="dono")


def test_estorno_recusado_se_lote_ja_foi_usado(atacadao, farinha):
    r = farinha_10kg(atacadao, farinha)
    rr = receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": r["linhas"][0]["linha_id"],
                                                           "quantidade": D("10")}], autor="dono")
    lote = Lote.objects.get()
    devolver_ao_fornecedor(lote_id=lote.id, quantidade=D("1"), unidade="kg", motivo="úmida", autor="dono")
    with pytest.raises(RegraViolada, match="já foi usada"):
        estornar_recebimento(recebimento_id=rr["recebimentos"][0]["recebimento_id"], motivo="x", autor="dono")


def test_devolucao_ao_fornecedor(atacadao, farinha):
    # CA-41: 5 kg recebidos, 1 kg já consumido, devolve 4 kg
    r = comprar(atacadao, [linha(farinha, "5", "kg", "30")], D("30"))
    receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": r["linhas"][0]["linha_id"],
                                                      "quantidade": D("5")}], autor="dono")
    lote = Lote.objects.get()
    Movimento.objects.create(tipo="consumo_producao", item=farinha, lote=lote, quantidade=D("-1000"),
                             quantidade_informada=D("1000"), unidade_informada="g", fator=D("1"), motivo="teste")
    with pytest.raises(RegraViolada, match="só tem 4 kg"):
        devolver_ao_fornecedor(lote_id=lote.id, quantidade=D("5"), unidade="kg", motivo="estragada", autor="dono")
    d = devolver_ao_fornecedor(lote_id=lote.id, quantidade=D("4"), unidade="kg", motivo="estragada", autor="dono")
    assert D(d["saldo_lote"]) == 0 and Movimento.objects.filter(tipo="devolucao_fornecedor").count() == 1
    assert Conta.objects.get().total == D("30") and len(avisos_de_ajuste()) == 1


def test_devolucao_so_de_lote_de_compra(farinha):
    from estoque.servicos import entrada_manual
    lote_id = entrada_manual(item_id=farinha.id, quantidade=D("1"), unidade="kg", custo_total=D("5"),
                             motivo="inicial", autor="dono")["lote_id"]
    with pytest.raises(RegraViolada, match="não veio de uma compra"):
        devolver_ao_fornecedor(lote_id=lote_id, quantidade=D("1"), motivo="x", autor="dono")


# ---------- cancelamento ----------

def test_cancelar_compra_sem_recebimento_nem_pagamento(atacadao, farinha):
    r = farinha_10kg(atacadao, farinha)
    cancelar_compra(compra_id=r["compra_id"], motivo="lancei duas vezes", autor="dono")
    assert Compra.objects.get().status == "cancelada" and Conta.objects.get().cancelada
    assert parcelas_em_aberto() == [] and falta_receber() == [] and compras_em_aberto() == []
    with pytest.raises(RegraViolada, match="não espera recebimento"):
        receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": r["linhas"][0]["linha_id"],
                                                          "quantidade": D("1")}], autor="dono")
    assert farinha_10kg(atacadao, farinha)["alertas"] == []  # cancelada não conta como duplicata


def test_cancelar_recusado_com_recebimento_ou_pagamento(atacadao, farinha):
    r = farinha_10kg(atacadao, farinha)
    receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": r["linhas"][0]["linha_id"],
                                                      "quantidade": D("1")}], autor="dono")
    with pytest.raises(RegraViolada, match="já tem recebimento"):
        cancelar_compra(compra_id=r["compra_id"], motivo="x", autor="dono")
    av = comprar(atacadao, [linha(farinha, "1", "kg", "7")], D("7"), condicao="a_vista")
    with pytest.raises(RegraViolada, match="já tem pagamento"):
        cancelar_compra(compra_id=av["compra_id"], motivo="x", autor="dono")
    estornar_pagamento(pagamento_id=Pagamento.objects.get().id, motivo="não paguei", autor="dono")
    cancelar_compra(compra_id=av["compra_id"], motivo="x", autor="dono")


def test_ultimo_custo_e_da_ultima_compra(atacadao, farinha):
    assert ultimo_custo(farinha.id) is None
    farinha_10kg(atacadao, farinha)
    comprar(atacadao, [linha(farinha, "10", "kg", "70")], D("70"))
    assert ultimo_custo(farinha.id)["custo_unitario"] == D("0.0070")


# ---------- cadastro ----------

def test_fornecedor_nome_unico_e_admin_pelo_nucleo(client, atacadao):
    with pytest.raises(RegraViolada, match="Já existe o fornecedor 'Atacadão'"):
        salvar_fornecedor(nome="atacadão", autor="dono")
    salvar_fornecedor(fornecedor_id=atacadao.id, nome="Atacadão Centro", ativo=False, autor="dono")
    assert Fornecedor.objects.get().nome == "Atacadão Centro"
    salvar_fornecedor(fornecedor_id=atacadao.id, nome="Atacadão", autor="dono")  # o próprio nome não conta
    client.force_login(get_user_model().objects.create_superuser("adm", password="x"))
    client.post("/admin/cadastros/fornecedor/add/", {"nome": "Assaí", "ativo": "on"})
    assert RegistroOperacao.objects.filter(nome="salvar_fornecedor", autor="adm").exists()
    assert client.get("/admin/compras/compra/add/").status_code == 403  # compra só pelos serviços


def test_fornecedor_repetido_ignora_acento_e_caixa(atacadao):
    for nome in ("ATACADÃO", "Atacadao", " atacadão "):
        with pytest.raises(RegraViolada, match="Já existe o fornecedor 'Atacadão'"):
            salvar_fornecedor(nome=nome, autor="dono")
    assert Fornecedor.objects.count() == 1
    salvar_fornecedor(nome="Atacadão Centro", autor="dono")  # nome diferente continua aceito
    with pytest.raises(RegraViolada, match="Já existe o fornecedor 'Atacadão Centro'"):
        salvar_fornecedor(fornecedor_id=atacadao.id, nome="ATACADAO CENTRO", autor="dono")
    salvar_fornecedor(fornecedor_id=atacadao.id, nome="Atacadão Centro 2", ativo=False, autor="dono")
