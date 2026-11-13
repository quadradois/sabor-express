"""Plano 6, fase 1: clientes, preços, venda direta, encomenda com reserva, fritura, perda e contas a receber."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.utils import timezone

from cadastros.models import Item
from cadastros.servicos import salvar_cliente
from estoque.models import CriterioValidade, Lote, Movimento
from estoque.servicos import disponivel, registrar_perda, saldo, saldo_lote, transferir_estado
from financeiro.consultas import (devido_por_cliente, parcelas_em_aberto, receber_em_aberto, receber_vencidas,
                                  recebimentos)
from financeiro.models import Conta, Pagamento, Parcela
from financeiro.servicos import estornar_recebimento_cliente, registrar_pagamento, registrar_recebimento
from nucleo.models import RegistroOperacao
from nucleo.operacoes import RegraViolada
from producao.fritura import registrar_fritura
from producao.servicos import origem
from vendas.consultas import (apresentacoes, detalhe_encomenda, encomendas, encomendas_do_dia, estoque_para_venda,
                              lotes_para_fritar, necessidade_producao, sobras_fritas, vendas)
from vendas.models import Encomenda, Reserva, Venda
from vendas.servicos import (cancelar_encomenda, cancelar_venda, completar_reserva, criar_encomenda,
                             entregar_encomenda, registrar_venda, salvar_apresentacao)

pytestmark = pytest.mark.django_db

HOJE = timezone.localdate()


def dia(n):
    return HOJE + dt.timedelta(days=n)


@pytest.fixture
def coxinha():
    return Item.objects.create(nome="Coxinha 150 g", tipo="produto", unidade_base="un", oleo_ref_un=D("0.05"))


@pytest.fixture
def caixa_papelao():
    c = Item.objects.create(nome="Caixa de papelão", tipo="embalagem", unidade_base="un", controla_validade=False)
    l = Lote.objects.create(item=c, codigo="CX", custo_unitario=D("1.00"))
    Movimento.objects.create(tipo="entrada_manual", item=c, lote=l, quantidade=10, quantidade_informada=10,
                             unidade_informada="un", fator=1, motivo="compra")
    return c


def lote(produto, n, *, validade, forma="cru", estado="congelado", custo="0.60", codigo=""):
    """Lote de produto pronto no estoque (atalho de teste para não passar por uma produção inteira)."""
    l = Lote.objects.create(item=produto, codigo=codigo, forma=forma, validade=validade, custo_unitario=D(custo))
    Movimento.objects.create(tipo="entrada_producao", item=produto, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado=estado, validade=validade)
    return l


def apresentacao(produto, nome="unidade", unidades=1, preco="5", atacado=None, forma="cru", estado="congelado",
                 **kw):
    return salvar_apresentacao(produto_id=produto.id, nome=nome, forma=forma, estado=estado, unidades=unidades,
                               preco_varejo=D(preco), preco_atacado=atacado, autor="dono", **kw)["apresentacao_id"]


def cliente(nome="João"):
    return salvar_cliente(nome=nome, autor="dono")["cliente_id"]


# ---------- cadastros ----------

def test_cliente_repetido_ignora_acento_e_caixa():
    salvar_cliente(nome="José da Padaria", contato="9999-0000", autor="dono")
    with pytest.raises(RegraViolada, match="Já existe o cliente 'José da Padaria'"):
        salvar_cliente(nome="  JOSE DA PADARIA ", autor="dono")
    with pytest.raises(RegraViolada, match="nome do cliente"):
        salvar_cliente(nome=" ", autor="dono")


def test_apresentacao_regras_e_imutavel_depois_de_vendida(coxinha, caixa_papelao):
    with pytest.raises(RegraViolada, match="quantas embalagens"):
        apresentacao(coxinha, "caixa com 25", 25, "40", embalagem_id=caixa_papelao.id)
    a = apresentacao(coxinha, "caixa com 25", 25, "45", atacado="40", embalagem_id=caixa_papelao.id, embalagens=1)
    with pytest.raises(RegraViolada, match="já tem a apresentação"):
        apresentacao(coxinha, "Caixa com 25", 25, "45")
    lote(coxinha, 50, validade=dia(10))
    registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 1}], autor="dono")
    with pytest.raises(RegraViolada, match="já foi vendida"):
        salvar_apresentacao(apresentacao_id=a, produto_id=coxinha.id, nome="caixa com 25", forma="cru",
                            estado="congelado", unidades=20, preco_varejo=D("45"), autor="dono")
    # preço pode mudar
    salvar_apresentacao(apresentacao_id=a, produto_id=coxinha.id, nome="caixa com 25", forma="cru", estado="congelado",
                        unidades=25, preco_varejo=D("50"), preco_atacado=D("42"), embalagem_id=caixa_papelao.id,
                        embalagens=1, autor="dono")
    [p] = apresentacoes()
    assert (p["preco_varejo"], p["livre_unidades"], p["livre_apresentacoes"]) == (D("50"), D("25"), 1)


# ---------- venda direta ----------

def test_venda_baixa_pelo_que_vence_primeiro_na_forma_e_conservacao(coxinha):
    longe = lote(coxinha, 10, validade=dia(30), codigo="L")
    perto = lote(coxinha, 10, validade=dia(5), codigo="P")
    lote(coxinha, 10, validade=dia(-1), codigo="V")  # vencido: nunca é vendido (RN-19)
    lote(coxinha, 10, validade=dia(2), estado="resfriado")  # outra conservação
    lote(coxinha, 10, validade=dia(1), forma="frito", estado="fresco")  # outra forma
    a = apresentacao(coxinha)
    r = registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 12}], forma_pagamento="pix", autor="dono")
    assert (saldo_lote(perto, "congelado"), saldo_lote(longe, "congelado")) == (0, D("8"))
    v = Venda.objects.get(id=r["venda_id"])
    assert (v.total, v.custo, v.recebido_na_hora) == (D("60"), D("7.20"), D("60"))
    [l] = v.linhas.all()
    assert [(b["lote_id"], D(b["quantidade"])) for b in l.baixas] == [(perto.id, D("10")), (longe.id, D("2"))]
    assert not hasattr(v, "conta") or Conta.objects.count() == 0  # à vista não abre conta


def test_venda_sem_estoque_recusa_sem_gravar_nada(coxinha):
    lote(coxinha, 5, validade=dia(5))
    a = apresentacao(coxinha)
    with pytest.raises(RegraViolada, match=r"Só há 5 un de 'Coxinha 150 g' cru congelado"):
        registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 6}], autor="dono")
    assert Venda.objects.count() == 0 and saldo(coxinha) == 5
    assert RegistroOperacao.objects.filter(nome="registrar_venda", status="erro").count() == 1


def test_caixa_baixa_unidades_e_embalagem_e_preco_fica_gravado(coxinha, caixa_papelao):
    # CA-28: caixa com 25 consome 1 caixa de papelão; preço de atacado gravado
    lote(coxinha, 60, validade=dia(10))
    a = apresentacao(coxinha, "caixa com 25", 25, "45", atacado="40", embalagem_id=caixa_papelao.id, embalagens=1)
    r = registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 2}], tabela="atacado", autor="dono")
    assert saldo(coxinha) == 10 and saldo(caixa_papelao) == 8
    [l] = Venda.objects.get(id=r["venda_id"]).linhas.all()
    assert (l.preco, l.preco_tabela, l.unidades_por, l.custo) == (D("40"), D("40"), 25, D("32.00"))  # 50×0,60 + 2×1
    salvar_apresentacao(apresentacao_id=a, produto_id=coxinha.id, nome="caixa com 25", forma="cru", estado="congelado",
                        unidades=25, preco_varejo=D("50"), preco_atacado=D("44"), embalagem_id=caixa_papelao.id,
                        embalagens=1, autor="dono")
    l.refresh_from_db()
    assert l.preco == D("40")  # RN-30
    b = apresentacao(coxinha, "unidade", 1, "2")
    with pytest.raises(RegraViolada, match="não tem preço de atacado"):
        registrar_venda(itens=[{"apresentacao_id": b, "quantidade": 1}], tabela="atacado", autor="dono")


def test_desconto_manual_guarda_o_preco_original(coxinha):
    lote(coxinha, 10, validade=dia(10))
    a = apresentacao(coxinha, preco="5")
    r = registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 4, "preco": "4.50"}], autor="dono")
    [l] = Venda.objects.get(id=r["venda_id"]).linhas.all()
    assert (l.preco_tabela, l.preco, l.total, D(r["total"])) == (D("5"), D("4.50"), D("18"), D("18"))


def test_venda_idempotente(coxinha):
    lote(coxinha, 10, validade=dia(10))
    a = apresentacao(coxinha)
    r1 = registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 3}], autor="dono", chave="v-1")
    r2 = registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 3}], autor="dono", chave="v-1")
    assert r1 == r2 and Venda.objects.count() == 1 and saldo(coxinha) == 7


def test_venda_a_prazo_vira_conta_a_receber(coxinha):
    # CA-37: venda a prazo de R$ 400 em 2 parcelas; recebe R$ 200
    lote(coxinha, 100, validade=dia(30))
    a = apresentacao(coxinha, preco="5")
    with pytest.raises(RegraViolada, match="precisa do cliente"):
        registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 80}], condicao="a_prazo", autor="dono")
    j = cliente()
    parcelas = [{"valor": "200", "vencimento": dia(-1)}, {"valor": "200", "vencimento": dia(29)}]
    r = registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 80}], condicao="a_prazo", cliente_id=j,
                        parcelas=parcelas, autor="dono")
    assert D(r["recebido_na_hora"]) == 0 and len(r["parcelas"]) == 2
    conta = Conta.objects.get(id=r["conta_id"])
    assert (conta.tipo, conta.total, conta.cliente_id, conta.venda_id) == ("receber", D("400"), j, r["venda_id"])
    assert parcelas_em_aberto() == []  # contas a pagar não misturam recebíveis
    [v] = receber_vencidas()
    assert (v["cliente"], v["saldo"]) == ("João", D("200"))
    p1 = Parcela.objects.get(conta=conta, numero=1)
    with pytest.raises(RegraViolada, match="anote como recebimento"):
        registrar_pagamento(parcela_id=p1.id, autor="dono")
    rec = registrar_recebimento(parcela_id=p1.id, forma="pix", autor="dono")
    assert rec["situacao"] == "paga"
    assert [p["numero"] for p in receber_em_aberto()] == [2]
    [d] = devido_por_cliente()
    assert (d["cliente"], d["devido"], d["vencido"]) == ("João", D("200"), D("0"))
    estornar_recebimento_cliente(pagamento_id=rec["pagamento_id"], motivo="pix não caiu", autor="dono")
    assert [p["numero"] for p in receber_em_aberto()] == [1, 2] and recebimentos() == []


def test_cancelar_venda_perda_por_padrao_ou_volta_ao_estoque(coxinha):
    l = lote(coxinha, 10, validade=dia(10))
    a = apresentacao(coxinha)
    v1 = registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 3}], autor="dono")["venda_id"]
    with pytest.raises(RegraViolada, match="motivo"):
        cancelar_venda(venda_id=v1, motivo="", autor="dono")
    r = cancelar_venda(venda_id=v1, motivo="cliente desistiu", autor="dono")
    assert (r["destino"], D(r["valor_devolvido"]), saldo(coxinha)) == ("perda", D("15"), 7)  # RN-36
    with pytest.raises(RegraViolada, match="já foi cancelada"):
        cancelar_venda(venda_id=v1, motivo="de novo", autor="dono")
    v2 = registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 2}], autor="dono")["venda_id"]
    cancelar_venda(venda_id=v2, motivo="voltou fechado", destino="estoque", autor="dono")
    assert saldo_lote(l, "congelado") == 7
    assert vendas()["totais"]["vendas"] == 0 and vendas(incluir_canceladas=True)["totais"]["canceladas"] == 2


def test_devolucao_ao_estoque_recusa_lote_vencido_e_cancela_recebivel(coxinha):
    l = lote(coxinha, 10, validade=dia(10))
    a = apresentacao(coxinha)
    j = cliente()
    r = registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 4}], condicao="a_prazo", cliente_id=j,
                        parcelas=[{"valor": "20", "vencimento": dia(10)}], autor="dono")
    registrar_recebimento(parcela_id=r["parcelas"][0]["parcela_id"], valor="5", autor="dono")
    Lote.objects.filter(id=l.id).update(validade=dia(-1))
    Movimento.objects.filter(lote=l).update(validade=dia(-1))
    with pytest.raises(RegraViolada, match="venceu: a devolução vai para perda"):
        cancelar_venda(venda_id=r["venda_id"], motivo="devolveu", destino="estoque", autor="dono")
    c = cancelar_venda(venda_id=r["venda_id"], motivo="devolveu", autor="dono")
    assert D(c["valor_devolvido"]) == D("5") and Conta.objects.get().cancelada  # CA-30
    assert receber_em_aberto() == []


# ---------- reservas e encomendas ----------

def test_disponivel_desconta_reservado_e_vencido(coxinha):
    # CA-29: saldo 10, 3 reservados, 2 vencidos → disponível 5
    lote(coxinha, 8, validade=dia(10))
    lote(coxinha, 2, validade=dia(-1))
    a = apresentacao(coxinha)
    criar_encomenda(cliente_id=cliente(), entrega_data=dia(2), itens=[{"apresentacao_id": a, "quantidade": 3}],
                    autor="dono")
    assert (saldo(coxinha), disponivel(coxinha)) == (10, 5)
    [e] = estoque_para_venda()
    assert (e["saldo"], e["reservado"], e["vencido"], e["livre"]) == (10, 3, 2, 5)


def test_encomenda_reserva_o_que_ha_e_mostra_o_que_falta_produzir(coxinha):
    # CA-26: 60 congeladas, encomenda de 100 → 60 reservadas, falta 40, venda direta não enxerga nada
    lote(coxinha, 60, validade=dia(30))
    a = apresentacao(coxinha, preco="2")
    r = criar_encomenda(cliente_id=cliente(), entrega_data=dia(2), entrega_hora="15:30", sinal="50",
                        sinal_forma="pix", itens=[{"apresentacao_id": a, "quantidade": 100}], autor="dono")
    assert (r["situacao"], D(r["falta"]), D(r["total"]), D(r["saldo"])) == ("aberta", D("40"), D("200"), D("150"))
    assert disponivel(coxinha) == 0
    with pytest.raises(RegraViolada, match="Só há 0 un"):
        registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 1}], autor="dono")
    [n] = necessidade_producao()
    assert (n["falta"], n["livre"], n["a_produzir"], n["encomendas"]) == (40, 0, 40, [r["encomenda_id"]])
    with pytest.raises(RegraViolada, match="Falta reservar 40 un"):
        entregar_encomenda(encomenda_id=r["encomenda_id"], autor="dono")
    # entrou estoque: completa com confirmação (RF-VEN-07)
    lote(coxinha, 50, validade=dia(20))
    assert necessidade_producao()[0]["a_produzir"] == 0
    c = completar_reserva(encomenda_id=r["encomenda_id"], autor="dono")
    assert (c["situacao"], D(c["falta"])) == ("pronta", 0) and disponivel(coxinha) == 10
    assert necessidade_producao() == []
    [e] = encomendas_do_dia(hoje=dia(2))
    assert e["situacao"] == "pronta" and e["entrega_hora"] == dt.time(15, 30)


def test_entrega_vira_venda_uma_unica_vez(coxinha, caixa_papelao):
    lote(coxinha, 100, validade=dia(30))
    a = apresentacao(coxinha, "caixa com 25", 25, "40", embalagem_id=caixa_papelao.id, embalagens=1)
    j = cliente()
    e = criar_encomenda(cliente_id=j, entrega_data=HOJE, itens=[{"apresentacao_id": a, "quantidade": 2}], sinal="20",
                        autor="dono")["encomenda_id"]
    r = entregar_encomenda(encomenda_id=e, condicao="a_prazo",
                           parcelas=[{"valor": "60", "vencimento": dia(15)}], autor="dono", chave="ent-1")
    assert (D(r["total"]), D(r["sinal"]), D(r["saldo"]), D(r["recebido_na_hora"])) == (D("80"), D("20"), D("60"), 0)
    assert saldo(coxinha) == 50 and saldo(caixa_papelao) == 8
    assert Reserva.objects.filter(situacao="baixada").count() == 1 and disponivel(coxinha) == 50
    assert Conta.objects.get().total == D("60") and Encomenda.objects.get().situacao == "entregue"
    # mesma chave: o mesmo resultado, nada de novo
    assert entregar_encomenda(encomenda_id=e, condicao="a_prazo", parcelas=[{"valor": "60", "vencimento": dia(15)}],
                              autor="dono", chave="ent-1") == r
    with pytest.raises(RegraViolada, match=r"já foi entregue \(venda"):
        entregar_encomenda(encomenda_id=e, autor="dono")
    assert Venda.objects.count() == 1 and saldo(coxinha) == 50
    with pytest.raises(RegraViolada, match="já foi entregue"):
        cancelar_encomenda(encomenda_id=e, motivo="x", autor="dono")
    # cancelar a venda da encomenda devolve também o sinal
    c = cancelar_venda(venda_id=r["venda_id"], motivo="festa cancelada", autor="dono")
    assert D(c["valor_devolvido"]) == D("20")


def test_entrega_a_vista_quita_o_saldo(coxinha):
    lote(coxinha, 10, validade=dia(30))
    a = apresentacao(coxinha, preco="3")
    e = criar_encomenda(cliente_id=cliente(), entrega_data=dia(1), itens=[{"apresentacao_id": a, "quantidade": 10}],
                        sinal="10", autor="dono")["encomenda_id"]
    r = entregar_encomenda(encomenda_id=e, forma_pagamento="dinheiro", autor="dono")
    assert (r["condicao"], D(r["recebido_na_hora"]), r["conta_id"]) == ("a_vista", D("20"), None)
    t = vendas()["totais"]
    assert (t["total"], t["recebido_na_hora"], t["por_forma_pagamento"]) == (D("30"), D("20"), {"dinheiro": D("20")})


def test_cancelar_encomenda_libera_a_reserva(coxinha):
    lote(coxinha, 10, validade=dia(30))
    a = apresentacao(coxinha)
    e = criar_encomenda(cliente_id=cliente(), entrega_data=dia(3), itens=[{"apresentacao_id": a, "quantidade": 8}],
                        sinal="10", autor="dono")["encomenda_id"]
    assert disponivel(coxinha) == 2
    r = cancelar_encomenda(encomenda_id=e, motivo="mudou a data", devolver_sinal=False, autor="dono")
    assert (len(r["reservas_liberadas"]), D(r["sinal_devolvido"])) == (1, 0)
    assert disponivel(coxinha) == 10 and saldo(coxinha) == 10 and encomendas() == []
    assert encomendas(situacao="cancelada")[0]["motivo_cancelamento"] == "mudou a data"
    with pytest.raises(RegraViolada, match="foi cancelada"):
        entregar_encomenda(encomenda_id=e, autor="dono")


def test_reserva_so_em_lote_que_vale_ate_a_entrega_e_troca_o_que_venceria(coxinha):
    curto = lote(coxinha, 10, validade=dia(2), codigo="CURTO")
    a = apresentacao(coxinha)
    e = criar_encomenda(cliente_id=cliente(), entrega_data=dia(5), itens=[{"apresentacao_id": a, "quantidade": 5}],
                        autor="dono")
    assert D(e["falta"]) == 5 and not Reserva.objects.exists()  # o lote vence antes da entrega
    e2 = criar_encomenda(cliente_id=cliente("Maria"), entrega_data=dia(1),
                         itens=[{"apresentacao_id": a, "quantidade": 5}], autor="dono")
    assert e2["situacao"] == "pronta"
    # a entrega foi adiada na prática: o lote reservado vence antes; completar troca de lote (FL-07 A3)
    Encomenda.objects.filter(id=e2["encomenda_id"]).update(entrega_data=dia(5))
    longo = lote(coxinha, 10, validade=dia(20), codigo="LONGO")
    c = completar_reserva(encomenda_id=e2["encomenda_id"], autor="dono")
    assert len(c["reservas_liberadas"]) == 1 and c["situacao"] == "pronta"
    assert {r.lote_id for r in Reserva.objects.filter(situacao="ativa")} == {longo.id}
    assert curto.id in {r.lote_id for r in Reserva.objects.filter(situacao="liberada")}


def test_encomenda_regras(coxinha):
    a = apresentacao(coxinha)
    with pytest.raises(RegraViolada, match="precisa do cliente"):
        criar_encomenda(cliente_id=None, entrega_data=dia(1), itens=[{"apresentacao_id": a, "quantidade": 1}],
                        autor="dono")
    with pytest.raises(RegraViolada, match="já passou"):
        criar_encomenda(cliente_id=cliente(), entrega_data=dia(-1), itens=[{"apresentacao_id": a, "quantidade": 1}],
                        autor="dono")
    with pytest.raises(RegraViolada, match="sinal deve ficar entre"):
        criar_encomenda(cliente_id=cliente("Ana"), entrega_data=dia(1), sinal="6",
                        itens=[{"apresentacao_id": a, "quantidade": 1}], autor="dono")
    assert detalhe_encomenda(999) is None


# ---------- estoque: reservado não se move nem se perde ----------

def test_transferencia_e_perda_nao_tocam_no_reservado(coxinha):
    l = lote(coxinha, 10, validade=dia(30))
    a = apresentacao(coxinha)
    criar_encomenda(cliente_id=cliente(), entrega_data=dia(2), itens=[{"apresentacao_id": a, "quantidade": 8}],
                    autor="dono")
    with pytest.raises(RegraViolada, match="reservadas para encomendas"):
        transferir_estado(lote_id=l.id, quantidade=D("3"), de="congelado", para="resfriado", autor="dono")
    with pytest.raises(RegraViolada, match="Cancele a encomenda"):
        registrar_perda(lote_id=l.id, estado="congelado", quantidade="3", motivo="caiu", autor="dono")
    with pytest.raises(RegraViolada, match="motivo da perda"):
        registrar_perda(lote_id=l.id, estado="congelado", quantidade="1", motivo=" ", autor="dono")
    r = registrar_perda(lote_id=l.id, estado="congelado", quantidade="2", motivo="caiu no chão", autor="dono")
    assert (D(r["quantidade"]), D(r["valor"]), saldo(coxinha)) == (D("2"), D("1.20"), 8)
    assert Movimento.objects.filter(tipo="perda").count() == 1


def test_descarte_de_vencido_libera_a_reserva(coxinha):
    l = lote(coxinha, 10, validade=dia(3))
    a = apresentacao(coxinha)
    e = criar_encomenda(cliente_id=cliente(), entrega_data=dia(1), itens=[{"apresentacao_id": a, "quantidade": 4}],
                        autor="dono")["encomenda_id"]
    Movimento.objects.filter(lote=l).update(validade=dia(-1))  # venceu antes de entregar
    with pytest.raises(RegraViolada, match="Complete a reserva com outro lote"):
        entregar_encomenda(encomenda_id=e, autor="dono")
    r = registrar_perda(lote_id=l.id, estado="congelado", quantidade="10", motivo="vencido", autor="dono")
    assert r["vencido"] and len(r["reservas_liberadas"]) == 1 and saldo(coxinha) == 0
    assert detalhe_encomenda(e)["falta"] == 4


def test_perda_de_ingrediente_em_outra_unidade():
    farinha = Item.objects.create(nome="Farinha", tipo="ingrediente", unidade_base="g", controla_validade=False)
    l = Lote.objects.create(item=farinha, custo_unitario=D("0.005"))
    Movimento.objects.create(tipo="entrada_manual", item=farinha, lote=l, quantidade=5000, quantidade_informada=5,
                             unidade_informada="kg", fator=1000, motivo="compra")
    registrar_perda(lote_id=l.id, quantidade="1.5", unidade="kg", motivo="molhou", autor="dono")
    assert saldo(farinha) == D("3500")


# ---------- fritura ----------

def test_fritura_gera_lote_frito_com_custo_e_origem(coxinha):
    # CA-24: cru K1 a R$ 0,60, óleo R$ 0,05; frita 40 com 38 boas → R$ 26,00 (R$ 0,6842/un)
    lote(coxinha, 5, validade=dia(-1))  # vencido: não sugere
    k1 = lote(coxinha, 100, validade=dia(30), codigo="K1")
    assert [p["lote_id"] for p in lotes_para_fritar(produto_id=coxinha.id)] == [k1.id]
    with pytest.raises(RegraViolada, match="Sem critério de validade"):
        registrar_fritura(lote_id=k1.id, estado="congelado", quantidade=40, boas=38, perda_motivo="estourou",
                          autor="dono")
    CriterioValidade.objects.create(produto=coxinha, forma="frito", estado="fresco", dias=1)
    with pytest.raises(RegraViolada, match="motivo das perdas"):
        registrar_fritura(lote_id=k1.id, estado="congelado", quantidade=40, boas=38, autor="dono")
    r = registrar_fritura(lote_id=k1.id, estado="congelado", quantidade=40, boas=38, perda_motivo="estourou",
                          autor="dono")
    frito = Lote.objects.get(id=r["lote_id"])
    assert (D(r["custo_total"]), frito.custo_unitario, frito.forma) == (D("26.00"), D("0.6842"), "frito")
    assert (saldo_lote(k1, "congelado"), saldo_lote(frito, "fresco")) == (60, 38)
    assert origem(frito) == [(k1, D("40"))]
    assert frito.validade == dia(1)
    with pytest.raises(RegraViolada, match="salgado cru"):
        registrar_fritura(lote_id=frito.id, estado="fresco", quantidade=1, boas=1, autor="dono")


def test_fritura_nao_usa_vencido_nem_reservado(coxinha):
    CriterioValidade.objects.create(produto=coxinha, forma="frito", estado="fresco", dias=1)
    vencido = lote(coxinha, 10, validade=dia(-1))
    with pytest.raises(RegraViolada, match="vencido não pode ser frito"):
        registrar_fritura(lote_id=vencido.id, estado="congelado", quantidade=1, boas=1, autor="dono")
    bom = lote(coxinha, 10, validade=dia(30))
    a = apresentacao(coxinha)
    criar_encomenda(cliente_id=cliente(), entrega_data=dia(2), itens=[{"apresentacao_id": a, "quantidade": 9}],
                    autor="dono")
    with pytest.raises(RegraViolada, match="reservadas para encomendas"):
        registrar_fritura(lote_id=bom.id, estado="congelado", quantidade=2, boas=2, autor="dono")
    with pytest.raises(RegraViolada, match="confirme a perda total"):
        registrar_fritura(lote_id=bom.id, estado="congelado", quantidade=1, boas=0, perda_motivo="queimou",
                          autor="dono")
    r = registrar_fritura(lote_id=bom.id, estado="congelado", quantidade=1, boas=0, perda_motivo="queimou",
                          confirmar_perda_total=True, autor="dono")
    assert r["lote_id"] is None and saldo(coxinha) == 19


def test_frito_vendido_e_sobras(coxinha):
    CriterioValidade.objects.create(produto=coxinha, forma="frito", estado="fresco", dias=1)
    k = lote(coxinha, 20, validade=dia(30))
    registrar_fritura(lote_id=k.id, estado="congelado", quantidade=10, boas=10, autor="dono")
    a = apresentacao(coxinha, "unidade frita", forma="frito", estado="fresco", preco="7")
    registrar_venda(itens=[{"apresentacao_id": a, "quantidade": 6}], autor="dono")
    [s] = sobras_fritas()
    assert s["saldo"] == 4 and sobras_fritas(ate_ontem=True) == []  # frito hoje: a rotina só avisa amanhã
    assert sobras_fritas(hoje=dia(1), ate_ontem=True)[0]["saldo"] == 4
