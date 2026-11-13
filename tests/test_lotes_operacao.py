"""Plano 9, fase 1: lotes na operação — separação, lote indicado, vencido com motivo, venda com data passada,
conferência do vencido (três respostas), ajuste por contagem, etiqueta e nome falável do lote."""

import datetime as dt
from decimal import Decimal as D

import pytest
from django.utils import timezone

from cadastros.models import Item
from cadastros.servicos import salvar_cliente
from custos.relatorios import relatorio_periodo
from decisoes.consultas import historico_operacoes, resumo_do_dia
from decisoes.geradores import rodar_rotina
from decisoes.models import Decisao
from estoque.etiquetas import dados_etiqueta
from estoque.lotes import nome_lote
from estoque.models import CriterioValidade, Lote, Movimento
from estoque.servicos import ajustar_contagem, entrada_manual, registrar_perda, saldo_lote, transferir_estado
from nucleo.models import RegistroOperacao
from nucleo.operacoes import RegraViolada
from producao.fritura import registrar_fritura
from producao.models import Producao
from producao.servicos import concluir_producao, iniciar_producao, registrar_peso, usar_previsto_restantes
from vendas.consultas import vendas
from vendas.lotes import separacao_encomenda, separacao_venda
from vendas.models import LinhaVenda, Reserva, Venda
from vendas.servicos import (cancelar_venda, criar_encomenda, entregar_encomenda, registrar_venda,
                             salvar_apresentacao)

pytestmark = pytest.mark.django_db

HOJE = timezone.localdate()


def dia(n):
    return HOJE + dt.timedelta(days=n)


@pytest.fixture
def coxinha():
    return Item.objects.create(nome="Coxinha 150 g", tipo="produto", unidade_base="un", oleo_ref_un=D("0.05"))


def feito_em(lote, d):
    Lote.objects.filter(id=lote.id).update(criado_em=timezone.make_aware(dt.datetime.combine(d, dt.time(10))))
    lote.refresh_from_db()
    return lote


def lote(produto, n, *, validade, feito=None, forma="cru", estado="congelado", custo="0.60", codigo=""):
    l = Lote.objects.create(item=produto, codigo=codigo, forma=forma, validade=validade, custo_unitario=D(custo))
    Movimento.objects.create(tipo="entrada_producao", item=produto, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado=estado, validade=validade)
    return feito_em(l, feito) if feito else l


def apresentacao(produto, nome="unidade", unidades=1, preco="5", forma="cru", estado="congelado"):
    return salvar_apresentacao(produto_id=produto.id, nome=nome, forma=forma, estado=estado, unidades=unidades,
                               preco_varejo=D(preco), autor="dono")["apresentacao_id"]


def vender(apr, n, lotes=None, **kw):
    item = {"apresentacao_id": apr, "quantidade": n}
    if lotes is not None:
        item["lotes"] = lotes
    return registrar_venda(itens=[item], autor="balcao", **kw)


def caixa(origem):
    return list(Decisao.objects.filter(origem=origem, vigente=True).order_by("id").values())


# ---------- nome falável e etiqueta ----------

def test_nome_falavel_do_lote_dia_mes_e_segundo_do_dia(coxinha):
    a = lote(coxinha, 5, validade=dia(30))
    b = lote(coxinha, 5, validade=dia(30))
    frito = lote(coxinha, 5, validade=dia(1), forma="frito", estado="fresco")
    antigo = lote(coxinha, 5, validade=dia(30), feito=dia(-40))
    assert nome_lote(a) == f"lote do dia {HOJE.day}"
    assert nome_lote(b) == f"segundo lote do dia {HOJE.day}"
    assert nome_lote(frito) == f"lote do dia {HOJE.day}"  # outra forma: conta à parte
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
             "novembro", "dezembro"]
    esperado = f"lote do dia {dia(-40).day} de {meses[dia(-40).month - 1]}"
    assert nome_lote(antigo).startswith(esperado)
    e = dados_etiqueta(antigo, "congelado")
    assert (e["dia_producao"], e["fabricacao"], e["nome_lote"]) == (dia(-40).day, dia(-40), nome_lote(antigo))


# ---------- instrução de separação ----------

def test_separacao_diz_de_qual_lote_pegar_e_quanto_sobra_sem_gravar(coxinha):
    velho = lote(coxinha, 18, validade=dia(1), feito=dia(-5))
    novo = lote(coxinha, 40, validade=dia(10), feito=dia(-3))
    apr = apresentacao(coxinha)
    ops, movs = RegistroOperacao.objects.count(), Movimento.objects.count()
    s = separacao_venda(itens=[{"apresentacao_id": apr, "quantidade": 30}])
    [l] = s["linhas"]
    assert [(x["lote_id"], x["unidades"], x["sobra"]) for x in l["lotes"]] == [(velho.id, 18, 0), (novo.id, 12, 28)]
    nv, nn = nome_lote(velho), nome_lote(novo)
    assert l["texto"] == (f"30 un de Coxinha 150 g cru congelado: 18 do {nv}, que vence amanhã, e 12 do {nn}; "
                          f"o {nv} zera e no {nn} sobram 28.")
    assert [a["tipo"] for a in l["avisos"]] == ["vence_amanha"] and s["completo"] and l["deixados"] == []
    assert (RegistroOperacao.objects.count(), Movimento.objects.count()) == (ops, movs)
    # a venda baixa exatamente o que a separação disse
    r = vender(apr, 30)
    assert [(x["lote_id"], D(x["unidades"])) for x in r["linhas"][0]["lotes"]] == [(velho.id, 18), (novo.id, 12)]
    assert r["linhas"][0]["lotes"][0]["nome"] == nv and r["avisos"] == [f"O {nv} vence amanhã ({dia(1):%d/%m})."]


def test_separacao_avisa_falta_e_que_so_ha_vencido(coxinha):
    lote(coxinha, 10, validade=dia(-1), feito=dia(-9))
    lote(coxinha, 5, validade=dia(8))
    apr = apresentacao(coxinha)
    s = separacao_venda(itens=[{"apresentacao_id": apr, "quantidade": 8}])
    [l] = s["linhas"]
    assert l["falta"] == 3 and not s["completo"]
    tipos = {a["tipo"]: a for a in l["avisos"]}
    assert "só há 5 un livres" in tipos["falta"]["texto"]
    assert tipos["so_vencido"]["precisa_motivo"] and "só sai indicando o lote e um motivo" in tipos["so_vencido"]["texto"]
    with pytest.raises(RegraViolada, match="Só há 5 un"):  # FEFO automático não pega o vencido
        vender(apr, 8)


# ---------- lote indicado ----------

def test_lote_indicado_deixa_o_mais_velho_para_tras_avisa_e_lembra_sem_duplicar(coxinha):
    velho = lote(coxinha, 18, validade=dia(8), feito=dia(-5))
    novo = lote(coxinha, 40, validade=dia(20), feito=dia(-2))
    apr = apresentacao(coxinha)
    prev = separacao_venda(itens=[{"apresentacao_id": apr, "quantidade": 10, "lotes": [{"lote_id": novo.id,
                                                                                         "unidades": 10}]}])
    assert [d["lote_id"] for d in prev["linhas"][0]["deixados"]] == [velho.id]
    r = vender(apr, 10, lotes=[{"lote_id": novo.id, "unidades": "10"}])
    assert (saldo_lote(velho, "congelado"), saldo_lote(novo, "congelado")) == (18, 30)  # o que a pessoa pegou
    assert r["avisos"] == [f"Ficaram 18 un do {nome_lote(velho)}, que vencem em {dia(8):%d/%m}: venda esse primeiro."]
    linha = LinhaVenda.objects.get()
    assert linha.lotes_indicados and [d["lote_id"] for d in linha.deixados] == [velho.id]
    rodar_rotina()
    [d] = caixa("lotes_deixados")
    assert "ficaram 18 un do" in d["texto"] and d["texto"].endswith("Venda esse primeiro.")
    assert [x["lote_id"] for x in resumo_do_dia()["validade"]["deixados"]] == [velho.id]
    rodar_rotina()
    assert len(caixa("lotes_deixados")) == 1  # não duplica
    # quando entra na janela do "vence logo", o aviso de validade assume (sem aviso em dobro)
    Movimento.objects.filter(lote=velho).update(validade=dia(2))
    rodar_rotina()
    assert caixa("lotes_deixados") == [] and [x["detalhes"]["lote_id"] for x in caixa("lotes_vencendo")] == [velho.id]


def test_lote_deixado_some_quando_volta_a_sair_dele(coxinha):
    velho = lote(coxinha, 18, validade=dia(8), feito=dia(-5))
    novo = lote(coxinha, 40, validade=dia(20), feito=dia(-2))
    apr = apresentacao(coxinha)
    vender(apr, 10, lotes=[{"lote_id": novo.id, "unidades": 10}])
    assert len(resumo_do_dia()["validade"]["deixados"]) == 1
    vender(apr, 2)  # FEFO: sai do velho
    assert resumo_do_dia()["validade"]["deixados"] == [] and saldo_lote(velho, "congelado") == 16


def test_lote_indicado_parcial_completa_por_fefo(coxinha):
    velho = lote(coxinha, 5, validade=dia(8), feito=dia(-5))
    novo = lote(coxinha, 40, validade=dia(20), feito=dia(-2))
    apr = apresentacao(coxinha)
    r = vender(apr, 12, lotes=[{"lote_id": novo.id, "unidades": 10}])
    assert [(x["lote_id"], D(x["unidades"])) for x in r["linhas"][0]["lotes"]] == [(novo.id, 10), (velho.id, 2)]
    assert r["avisos"] == [f"Ficaram 3 un do {nome_lote(velho)}, que vencem em {dia(8):%d/%m}: venda esse primeiro."]


def test_lote_indicado_recusas(coxinha):
    outro = Item.objects.create(nome="Kibe", tipo="produto", unidade_base="un")
    bom = lote(coxinha, 10, validade=dia(20), feito=dia(-2))
    frito = lote(coxinha, 10, validade=dia(1), forma="frito", estado="fresco")
    kibe = lote(outro, 10, validade=dia(20))
    apr = apresentacao(coxinha)
    casos = [
        ([{"lote_id": kibe.id, "unidades": 1}], {}, "é de 'Kibe'"),
        ([{"lote_id": frito.id, "unidades": 1}], {}, "é frito; a apresentação é cru"),
        ([{"lote_id": bom.id, "unidades": 11}], {"n": 11}, "só tem 10 un em congelado"),
        ([{"lote_id": bom.id, "unidades": 3}], {"n": 2}, "somam 3 un, mas o item pede 2 un"),
        ([{"lote_id": 999, "unidades": 1}], {}, "lote não encontrado"),
        ([{"lote_id": bom.id, "unidades": 0}], {}, "maiores que zero"),
        ([{"lote_id": bom.id, "unidades": 1}], {"data_venda": dia(-3)}, "foi feito em .* depois do dia da venda"),
        ([{"lote_id": bom.id, "unidades": 1}], {"data_venda": dia(1)}, "não pode ter data depois de hoje"),
    ]
    for lotes, kw, msg in casos:
        n = kw.pop("n", 1)
        with pytest.raises(RegraViolada, match=msg):
            vender(apr, n, lotes=lotes, **kw)
    # reservado para encomenda não sai em outra venda, nem indicado
    j = salvar_cliente(nome="João", autor="dono")["cliente_id"]
    criar_encomenda(cliente_id=j, entrega_data=dia(2), itens=[{"apresentacao_id": apr, "quantidade": 8}], autor="dono")
    with pytest.raises(RegraViolada, match="só 2 un em congelado não estão reservadas"):
        vender(apr, 3, lotes=[{"lote_id": bom.id, "unidades": 3}])
    assert Venda.objects.count() == 0 and saldo_lote(bom, "congelado") == 10


# ---------- vencido: aviso com motivo ----------

def test_venda_de_vencido_so_indicado_e_com_motivo(coxinha):
    v = lote(coxinha, 10, validade=dia(-2), feito=dia(-9))
    apr = apresentacao(coxinha)
    with pytest.raises(RegraViolada) as e:
        vender(apr, 4, lotes=[{"lote_id": v.id, "unidades": 4}])
    msg = str(e.value)
    assert f"O {nome_lote(v)} de 'Coxinha 150 g', congelado, venceu em {dia(-2):%d/%m}" in msg
    assert "informe o motivo" in msg
    prev = separacao_venda(itens=[{"apresentacao_id": apr, "quantidade": 4, "lotes": [{"lote_id": v.id,
                                                                                        "unidades": 4}]}])
    assert prev["precisa_motivo"]
    r = vender(apr, 4, lotes=[{"lote_id": v.id, "unidades": 4}], motivo_vencido="cliente quis para fritar hoje",
               chave="venda-vencido")
    m = Movimento.objects.get(tipo="saida_venda")
    assert (m.motivo_vencido, saldo_lote(v, "congelado")) == ("cliente quis para fritar hoje", 6)
    assert r["linhas"][0]["lotes"][0]["motivo_vencido"] == "cliente quis para fritar hoje"
    [h] = historico_operacoes(nome="registrar_venda", status="sucesso")
    assert h["motivo_vencido"] == "cliente quis para fritar hoje"
    # idempotente pela chave
    assert vender(apr, 4, lotes=[{"lote_id": v.id, "unidades": 4}], motivo_vencido="cliente quis para fritar hoje",
                  chave="venda-vencido") == r
    assert Venda.objects.count() == 1


def test_venda_com_data_passada_julga_a_validade_naquele_dia(coxinha):
    l = lote(coxinha, 10, validade=dia(-2), feito=dia(-6))
    apr = apresentacao(coxinha)
    r = vender(apr, 3, data_venda=dia(-3))  # FEFO no dia da venda: estava válido, sem motivo
    assert D(r["linhas"][0]["lotes"][0]["unidades"]) == 3 and r["data"] == dia(-3).isoformat()
    vender(apr, 2, lotes=[{"lote_id": l.id, "unidades": 2}], data_venda=dia(-2))  # último dia: ainda vale
    assert not Movimento.objects.filter(tipo="saida_venda").exclude(motivo_vencido="").exists()
    with pytest.raises(RegraViolada, match="venceu em"):
        vender(apr, 1, lotes=[{"lote_id": l.id, "unidades": 1}], data_venda=dia(-1))
    # a venda cai no dia em que aconteceu
    assert vendas(de=dia(-3), ate=dia(-3))["totais"]["total"] == D("15")
    assert relatorio_periodo(de=dia(-3), ate=dia(-2))["vendas"]["totais"]["receita"] == D("25")
    assert vendas(de=HOJE, ate=HOJE)["totais"]["vendas"] == 0


def test_entrega_com_lote_indicado_e_reserva_vencida_com_motivo(coxinha):
    velho = lote(coxinha, 10, validade=dia(5), feito=dia(-5))
    novo = lote(coxinha, 20, validade=dia(30), feito=dia(-1))
    apr = apresentacao(coxinha)
    j = salvar_cliente(nome="João", autor="dono")["cliente_id"]
    e = criar_encomenda(cliente_id=j, entrega_data=dia(1), itens=[{"apresentacao_id": apr, "quantidade": 6}],
                        autor="dono")
    ie = e["itens"][0]["item_encomenda_id"]
    s = separacao_encomenda(encomenda_id=e["encomenda_id"])
    assert [(x["lote_id"], x["unidades"], x["sobra"]) for x in s["linhas"][0]["lotes"]] == [(velho.id, 6, 4)]
    r = entregar_encomenda(encomenda_id=e["encomenda_id"],
                           lotes=[{"item_encomenda_id": ie, "lotes": [{"lote_id": novo.id, "unidades": 6}]}],
                           autor="balcao")
    assert (saldo_lote(velho, "congelado"), saldo_lote(novo, "congelado")) == (10, 14)
    assert Reserva.objects.get().situacao == "liberada"
    assert r["avisos"] and "Ficaram 10 un do" in r["avisos"][0]
    # reserva que venceu: sem motivo, recusa dizendo o que fazer; com motivo, entrega
    e2 = criar_encomenda(cliente_id=j, entrega_data=dia(2), itens=[{"apresentacao_id": apr, "quantidade": 2}],
                         autor="dono")
    Movimento.objects.filter(lote=velho).update(validade=dia(-1))
    avisos = separacao_encomenda(encomenda_id=e2["encomenda_id"])["avisos"]
    assert avisos[0]["tipo"] == "vencido_sem_motivo"
    with pytest.raises(RegraViolada, match="Complete a reserva com outro lote ou, para entregar dele mesmo assim"):
        entregar_encomenda(encomenda_id=e2["encomenda_id"], autor="balcao")
    entregar_encomenda(encomenda_id=e2["encomenda_id"], motivo_vencido="cliente avisado, vai fritar hoje",
                       autor="balcao")
    assert Movimento.objects.get(tipo="saida_venda", lote=velho).motivo_vencido == "cliente avisado, vai fritar hoje"


def test_fritura_transferencia_e_devolucao_de_vencido_com_motivo(coxinha):
    CriterioValidade.objects.create(produto=coxinha, forma="frito", estado="fresco", dias=1)
    CriterioValidade.objects.create(produto=coxinha, forma="cru", estado="congelado", dias=60)
    v = lote(coxinha, 20, validade=dia(-1), feito=dia(-8), estado="resfriado")
    with pytest.raises(RegraViolada, match=r"venceu em .* não pode ser frito sem um motivo"):
        registrar_fritura(lote_id=v.id, estado="resfriado", quantidade=2, boas=2, autor="dono")
    registrar_fritura(lote_id=v.id, estado="resfriado", quantidade=2, boas=2, motivo_vencido="lanche da equipe",
                      autor="dono")
    assert Movimento.objects.get(tipo="consumo_fritura").motivo_vencido == "lanche da equipe"
    with pytest.raises(RegraViolada, match="só aceita descarte"):
        transferir_estado(lote_id=v.id, quantidade=D("5"), de="resfriado", para="congelado", autor="dono")
    r = transferir_estado(lote_id=v.id, quantidade=D("5"), de="resfriado", para="congelado",
                          motivo_vencido="congelar até o dono decidir", autor="dono")
    assert r["validade"] == dia(-1).isoformat()  # continua vencido: a transferência não dá validade nova
    # devolução de venda a estoque com lote vencido
    bom = lote(coxinha, 5, validade=dia(3), forma="cru", estado="fresco")
    apr = apresentacao(coxinha, estado="fresco")
    venda = vender(apr, 2)
    Movimento.objects.filter(lote=bom).update(validade=dia(-1))
    with pytest.raises(RegraViolada, match="venceu: a devolução vai para perda"):
        cancelar_venda(venda_id=venda["venda_id"], motivo="devolveu", destino="estoque", autor="dono")
    cancelar_venda(venda_id=venda["venda_id"], motivo="devolveu", destino="estoque", motivo_vencido="vai para a conferência",
                   autor="dono")
    assert Movimento.objects.get(tipo="devolucao_cliente").motivo_vencido == "vai para a conferência"


def test_ingrediente_vencido_na_producao_so_escolhido_e_com_motivo(bolinha):
    farinha = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    entrada_manual(item_id=farinha.id, quantidade=D("1000"), unidade="g", custo_total=D("5"), motivo="compra",
                   validade=dia(-1), autor="dono")
    entrada_manual(item_id=farinha.id, quantidade=D("1000"), unidade="g", custo_total=D("8"), motivo="compra",
                   validade=dia(10), autor="dono")
    vencida, boa = Lote.objects.filter(item=farinha).order_by("id")
    p = Producao.objects.get(id=iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"])
    linha = p.linhas.get()
    registrar_peso(linha_id=linha.id, usado=None, lote_id=vencida.id, autor="dono")
    usar_previsto_restantes(producao_id=p.id, autor="dono")
    with pytest.raises(RegraViolada, match="venceu em .*informe o motivo"):
        concluir_producao(producao_id=p.id, quantidade_boa=10, estado="resfriado", autor="dono")
    concluir_producao(producao_id=p.id, quantidade_boa=10, estado="resfriado", motivo_vencido="farinha conferida, boa",
                      autor="dono")
    m = Movimento.objects.get(tipo="consumo_producao")
    assert (m.lote_id, m.motivo_vencido, saldo_lote(boa)) == (vencida.id, "farinha conferida, boa", D("1000"))


# ---------- conferência do vencido ----------

def test_conferencia_do_vencido_pergunta_uma_vez_e_as_tres_respostas(coxinha):
    v = lote(coxinha, 18, validade=dia(-1), feito=dia(-10), codigo="V1")
    apr = apresentacao(coxinha)
    rodar_rotina()
    rodar_rotina()
    [d] = caixa("lotes_vencidos")  # uma pergunta por porção, não uma por dia
    assert d["texto"].startswith(f"Coxinha 150 g venceu em {dia(-1):%d/%m}: 18 un no lote V1, congelado")
    assert "Ainda estão aí? Se já foram vendidas" in d["texto"]
    conf = d["detalhes"]["conferencia"]
    assert (conf["ja_saiu"]["servico"], conf["estao_aqui"]["servico"], conf["nao_sei"]["servico"]) == (
        "registrar_venda", "registrar_perda", "ajustar_contagem")
    # (a) já foram vendidas: venda com a data real, do lote, sem motivo (estava válido)
    vender(apr, 5, lotes=[{"lote_id": v.id, "unidades": 5}], data_venda=dia(-2))
    # (b) estão aqui: destino com motivo — consumo da equipe é diferente de descarte
    r = registrar_perda(lote_id=v.id, estado="congelado", quantidade=3, motivo="lanche", destino="consumo_equipe",
                        autor="dono")
    assert r["destino"] == "consumo_equipe" and Movimento.objects.get(tipo="perda").destino == "consumo_equipe"
    with pytest.raises(RegraViolada, match="Destino inválido"):
        registrar_perda(lote_id=v.id, estado="congelado", quantidade=1, motivo="x", destino="lixo", autor="dono")
    perdas = relatorio_periodo(de=HOJE, ate=HOJE)["perdas"]["movimentos"]
    assert [(p["destino"], p["quantidade"]) for p in perdas] == [("consumo_equipe", D("3"))]
    # (c) não sei: contagem
    with pytest.raises(RegraViolada, match="não pode ser negativa"):
        ajustar_contagem(lote_id=v.id, estado="congelado", contado=-1, motivo="contei", autor="dono")
    with pytest.raises(RegraViolada, match="motivo do ajuste"):
        ajustar_contagem(lote_id=v.id, estado="congelado", contado=4, motivo=" ", autor="dono")
    a = ajustar_contagem(lote_id=v.id, estado="congelado", contado=4, motivo="conferência do vencido", autor="dono",
                         chave="conta-1")
    assert (D(a["antes"]), D(a["diferenca"]), saldo_lote(v, "congelado")) == (D("10"), D("-6"), 4)
    assert ajustar_contagem(lote_id=v.id, estado="congelado", contado=4, motivo="conferência do vencido",
                            autor="dono", chave="conta-1") == a
    assert Movimento.objects.filter(tipo="ajuste_contagem").count() == 1
    rodar_rotina()
    assert "4 un no lote V1" in caixa("lotes_vencidos")[0]["texto"]  # números em dia, mesma pergunta
    registrar_perda(lote_id=v.id, estado="congelado", quantidade=4, motivo="vencido", destino="descarte", autor="dono")
    rodar_rotina()
    assert caixa("lotes_vencidos") == [] and Decisao.objects.get(origem="lotes_vencidos").situacao == "sem_efeito"


def test_caixa_se_atualiza_na_hora_sem_esperar_a_rotina(coxinha, django_capture_on_commit_callbacks):
    v = lote(coxinha, 10, validade=dia(-1), codigo="V1")
    rodar_rotina()
    assert len(caixa("lotes_vencidos")) == 1
    with django_capture_on_commit_callbacks(execute=True):
        registrar_perda(lote_id=v.id, estado="congelado", quantidade=4, motivo="vencido", destino="descarte",
                        autor="dono")
    assert "6 un no lote V1" in caixa("lotes_vencidos")[0]["texto"]  # números em dia, sem rodar a rotina
    with django_capture_on_commit_callbacks(execute=True):
        registrar_perda(lote_id=v.id, estado="congelado", quantidade=6, motivo="vencido", destino="descarte",
                        autor="dono")
    assert caixa("lotes_vencidos") == [] and Decisao.objects.get(origem="lotes_vencidos").situacao == "sem_efeito"
    n = RegistroOperacao.objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        lote(coxinha, 5, validade=dia(30), codigo="N1")
        ajustar_contagem(lote_id=Lote.objects.get(codigo="N1").id, estado="congelado", contado=4, motivo="contei",
                         autor="dono")
    assert RegistroOperacao.objects.count() == n + 1  # nada mudou na caixa: só a operação entra no histórico


def test_contagem_acha_mais_ou_menos_que_o_reservado(coxinha):
    l = lote(coxinha, 10, validade=dia(10))
    apr = apresentacao(coxinha)
    j = salvar_cliente(nome="João", autor="dono")["cliente_id"]
    criar_encomenda(cliente_id=j, entrega_data=dia(2), itens=[{"apresentacao_id": apr, "quantidade": 6}], autor="dono")
    r = ajustar_contagem(lote_id=l.id, estado="congelado", contado=12, motivo="achei mais", autor="dono")
    m = Movimento.objects.get(tipo="ajuste_contagem")
    assert (D(r["diferenca"]), m.validade, r["reservas_liberadas"]) == (D("2"), dia(10), [])
    r = ajustar_contagem(lote_id=l.id, estado="congelado", contado=5, motivo="contagem", autor="dono")
    assert len(r["reservas_liberadas"]) == 1 and Reserva.objects.get().situacao == "liberada"
    assert ajustar_contagem(lote_id=l.id, estado="congelado", contado=5, motivo="bate", autor="dono")["diferenca"] == "0.000"
    assert Movimento.objects.filter(tipo="ajuste_contagem").count() == 2
