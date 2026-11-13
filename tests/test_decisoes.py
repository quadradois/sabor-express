from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.management import call_command
from django.utils import timezone

from cadastros.models import Item
from cadastros.servicos import salvar_fornecedor
from compras.servicos import encerrar_pendencia, registrar_compra
from decisoes.consultas import contar_pendentes, decisoes, detalhe_decisao, historico_operacoes, resumo_do_dia
from decisoes.geradores import rodar_rotina
from decisoes.models import Decisao
from decisoes.servicos import aprovar_decisao, criar_decisao, expirar_decisoes, recusar_decisao, sincronizar
from estoque.models import ConsumoPendente, CriterioValidade, Movimento
from estoque.servicos import disponivel, entrada_manual, itens_abaixo_do_minimo
from financeiro.models import Parcela
from financeiro.servicos import registrar_pagamento, resolver_aviso
from nucleo.models import RegistroOperacao
from nucleo.operacoes import RegraViolada
from producao.models import LinhaPreparo
from producao.servicos import concluir_producao, iniciar_producao, registrar_peso, usar_previsto_restantes

pytestmark = pytest.mark.django_db


def hoje():
    return timezone.localdate()


def caixa(origem):
    return decisoes(origem=origem)


@pytest.fixture
def farinha(bolinha):
    return bolinha.ficha.proporcoes.get().preparacao.itens.get().item


@pytest.fixture
def atacadao():
    return salvar_fornecedor(nome="Atacadão", autor="dono")["fornecedor_id"]


def produzir(bolinha, boas=10, usado=None, **iniciar):
    """10 bolinhas de 100 g = 1 kg de farinha prevista."""
    CriterioValidade.objects.get_or_create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono", **iniciar)["producao_id"]
    if usado is not None:
        registrar_peso(linha_id=LinhaPreparo.objects.get(producao_id=p).id, usado=D(usado), autor="dono")
    usar_previsto_restantes(producao_id=p, autor="dono")
    perdas = 10 - boas
    return p, concluir_producao(producao_id=p, quantidade_boa=boas, perdas=perdas,
                                perda_motivo="rasgou" if perdas else "", estado="resfriado", autor="dono",
                                validade_manual=hoje(), justificativa="teste")


def farinha_em_estoque(farinha, kg="10"):
    return entrada_manual(item_id=farinha.id, quantidade=D(kg), unidade="kg", custo_total=D("50"), motivo="compra",
                          autor="dono")["lote_id"]


# ---------- caixa: criar, aprovar, recusar ----------

def test_aviso_so_aceita_ciencia():
    r = criar_decisao(origem="agente", texto="O freezer 2 está fazendo barulho.", autor="agente", canal="agente")
    assert r["criada"] and r["situacao"] == "pendente"
    [d] = decisoes()
    assert (d["tipo"], d["texto"], d["criada_por"]) == ("aviso", "O freezer 2 está fazendo barulho.", "agente")
    with pytest.raises(RegraViolada, match="Aviso não se recusa"):
        recusar_decisao(decisao_id=d["decisao_id"], motivo="não", autor="dono")
    feito = aprovar_decisao(decisao_id=d["decisao_id"], autor="dono")
    assert (feito["situacao"], feito["resultado"]) == ("aprovada", None)
    assert decisoes() == [] and detalhe_decisao(d["decisao_id"])["decidida_por"] == "dono"


def test_criar_recusa_operacao_desconhecida_e_nao_duplica_assunto():
    with pytest.raises(RegraViolada, match="não pode ser decidida pela caixa"):
        criar_decisao(origem="agente", texto="apagar tudo", operacao="apagar_tudo", parametros={}, autor="agente")
    with pytest.raises(RegraViolada, match="Informe o texto"):
        criar_decisao(origem="agente", texto=" ", autor="agente")
    a = criar_decisao(origem="agente", assunto="freezer", texto="Freezer", autor="agente")
    b = criar_decisao(origem="agente", assunto="freezer", texto="Freezer de novo", autor="agente")
    assert (b["decisao_id"], b["criada"]) == (a["decisao_id"], False) and Decisao.objects.count() == 1


def test_aprovar_executa_a_operacao_uma_unica_vez(bolinha, farinha):
    produzir(bolinha, pendente_justificativa="nota não lançada")  # 1 kg de farinha pendente
    lote = farinha_em_estoque(farinha)
    rodar_rotina()
    [d] = caixa("consumo_pendente")
    assert d["tipo"] == "decisao" and d["parametros"] == {"pendente_id": ConsumoPendente.objects.get().id,
                                                          "lote_id": lote}
    assert "1 kg de Farinha de trigo" in d["texto"] and d["expira_em"] is not None
    feito = aprovar_decisao(decisao_id=d["decisao_id"], autor="dono", canal="agente")
    assert feito["situacao"] == "aprovada" and D(feito["resultado"]["custo"]) == D("5.00")
    assert aprovar_decisao(decisao_id=d["decisao_id"], autor="dono") == feito  # de novo: não executa
    assert RegistroOperacao.objects.filter(nome="conciliar_consumo", status="sucesso").count() == 1
    assert Movimento.objects.filter(motivo__startswith="Conciliação").count() == 1
    salvo = Decisao.objects.get(id=d["decisao_id"])
    assert (salvo.decidida_por, salvo.registro.autor, salvo.registro.canal) == ("dono", "dono", "agente")
    rodar_rotina()  # a pendência acabou: a decisão aprovada deixa de ser vigente, nada novo
    salvo.refresh_from_db()
    assert caixa("consumo_pendente") == [] and (salvo.situacao, salvo.vigente) == ("aprovada", False)


def test_aprovar_com_a_mesma_chave_nao_duplica(bolinha, farinha):
    produzir(bolinha, pendente_justificativa="nota não lançada")
    farinha_em_estoque(farinha)
    rodar_rotina()
    [d] = caixa("consumo_pendente")
    a = aprovar_decisao(decisao_id=d["decisao_id"], autor="dono", chave="k1")
    assert aprovar_decisao(decisao_id=d["decisao_id"], autor="dono", chave="k1") == a
    assert RegistroOperacao.objects.filter(nome="aprovar_decisao", status="sucesso").count() == 1


def test_recusa_do_nucleo_mantem_pendente_e_fica_na_trilha(bolinha, farinha):
    produzir(bolinha, pendente_justificativa="nota não lançada")
    lote = farinha_em_estoque(farinha, kg="1")
    rodar_rotina()
    [d] = caixa("consumo_pendente")
    produzir(bolinha)  # usa o lote antes da aprovação
    with pytest.raises(RegraViolada, match="só tem"):
        aprovar_decisao(decisao_id=d["decisao_id"], autor="dono")
    depois = detalhe_decisao(d["decisao_id"])
    assert depois["situacao"] == "pendente" and "só tem" in depois["ultimo_erro"]["erro"]
    assert not Movimento.objects.filter(motivo__startswith="Conciliação").exists()
    assert ConsumoPendente.objects.get().aberto and lote
    rodar_rotina()  # o lote já não cobre: a proposta fica sem efeito e vira aviso
    assert detalhe_decisao(d["decisao_id"])["situacao"] == "sem_efeito"
    [aviso] = caixa("consumo_pendente")
    assert aviso["tipo"] == "aviso" and "sem lote que cubra" in aviso["texto"]


def test_recusar_guarda_o_motivo_e_nao_volta_enquanto_a_situacao_existir(bolinha, farinha):
    produzir(bolinha, pendente_justificativa="nota não lançada")
    farinha_em_estoque(farinha)
    rodar_rotina()
    [d] = caixa("consumo_pendente")
    with pytest.raises(RegraViolada, match="motivo"):
        recusar_decisao(decisao_id=d["decisao_id"], motivo=" ", autor="dono")
    r = recusar_decisao(decisao_id=d["decisao_id"], motivo="vou usar o lote da semana que vem", autor="dono")
    assert r["situacao"] == "recusada"
    with pytest.raises(RegraViolada, match="já foi recusada por dono"):
        aprovar_decisao(decisao_id=d["decisao_id"], autor="dono")
    rodar_rotina()
    assert caixa("consumo_pendente") == [] and Decisao.objects.filter(origem="consumo_pendente").count() == 1
    assert Decisao.objects.get(id=d["decisao_id"]).motivo == "vou usar o lote da semana que vem"


def test_expirada_sai_da_caixa_e_a_rotina_gera_de_novo(bolinha, farinha):
    produzir(bolinha, pendente_justificativa="nota não lançada")
    farinha_em_estoque(farinha)
    rodar_rotina()
    [d] = caixa("consumo_pendente")
    Decisao.objects.filter(id=d["decisao_id"]).update(expira_em=timezone.now() - timedelta(minutes=1))
    assert caixa("consumo_pendente") == [] and detalhe_decisao(d["decisao_id"])["situacao"] == "expirada"
    with pytest.raises(RegraViolada, match="não vale mais"):
        aprovar_decisao(decisao_id=d["decisao_id"], autor="dono")
    assert expirar_decisoes()["expiradas"] == 1
    rodar_rotina()
    [nova] = caixa("consumo_pendente")
    assert nova["decisao_id"] != d["decisao_id"] and Decisao.objects.get(id=d["decisao_id"]).situacao == "expirada"


# ---------- geradores ----------

def test_rotina_e_idempotente_e_situacao_resolvida_fica_sem_efeito(atacadao):
    i = Item.objects.create(nome="Requeijão", tipo="ingrediente", unidade_base="g", controla_validade=False,
                            estoque_minimo=D("1000"))
    rodar_rotina()
    r = rodar_rotina()
    [d] = caixa("estoque_baixo")
    assert r["geradores"]["estoque_baixo"] == {"origem": "estoque_baixo", "criadas": 0, "atualizadas": 0,
                                               "sem_efeito": 0, "pendentes": 1}
    assert d["texto"] == "Requeijão está abaixo do mínimo: tem 0 g, o mínimo é 1 kg."
    entrada_manual(item_id=i.id, quantidade=D("300"), unidade="g", custo_total=D("6"), motivo="compra", autor="dono")
    rodar_rotina()
    [d2] = caixa("estoque_baixo")
    assert d2["decisao_id"] == d["decisao_id"] and "tem 300 g" in d2["texto"]  # números em dia, mesma decisão
    entrada_manual(item_id=i.id, quantidade=D("1"), unidade="kg", custo_total=D("20"), motivo="compra", autor="dono")
    rodar_rotina()
    assert caixa("estoque_baixo") == [] and Decisao.objects.get().situacao == "sem_efeito"
    assert Decisao.objects.count() == 1


def test_validade_vencidos_vencendo_e_disponivel():
    leite = Item.objects.create(nome="Leite", tipo="ingrediente", unidade_base="mL", controla_validade=True,
                                estoque_minimo=D("2000"))
    entrada_manual(item_id=leite.id, quantidade=D("2"), unidade="L", custo_total=D("10"), motivo="compra",
                   lote_codigo="L1", validade=hoje() - timedelta(days=1), autor="dono")
    entrada_manual(item_id=leite.id, quantidade=D("500"), unidade="mL", custo_total=D("3"), motivo="compra",
                   lote_codigo="L2", validade=hoje() + timedelta(days=1), autor="dono")
    entrada_manual(item_id=leite.id, quantidade=D("1"), unidade="L", custo_total=D("5"), motivo="compra",
                   lote_codigo="L3", validade=hoje() + timedelta(days=10), autor="dono")
    assert disponivel(leite) == D("1500")  # RN-03: o vencido não conta
    [baixo] = itens_abaixo_do_minimo()  # saldo 3,5 L passa do mínimo, mas o disponível não
    assert (baixo["disponivel"], baixo["falta"]) == (D("1500"), D("500"))
    rodar_rotina()
    [vencido] = caixa("lotes_vencidos")
    assert vencido["texto"].startswith("Leite venceu em") and "2 L no lote L1" in vencido["texto"]
    [vencendo] = caixa("lotes_vencendo")
    assert "Leite vence amanhã" in vencendo["texto"] and "500 mL no lote L2" in vencendo["texto"]


def test_ultimo_dia_de_validade_vira_pergunta_mesmo_com_ciencia_do_aviso_anterior():
    leite = Item.objects.create(nome="Leite", tipo="ingrediente", unidade_base="mL", controla_validade=True)
    amanha = hoje() + timedelta(days=1)
    entrada_manual(item_id=leite.id, quantidade=D("500"), unidade="mL", custo_total=D("3"), motivo="compra",
                   lote_codigo="L2", validade=amanha, autor="dono")
    rodar_rotina()
    [aviso] = caixa("lotes_vencendo")
    assert aviso["texto"].endswith("no lote L2.") and "último dia" not in aviso["texto"]
    aprovar_decisao(decisao_id=aviso["decisao_id"], autor="dono")
    assert caixa("lotes_vencendo") == []
    rodar_rotina(hoje=amanha)
    [pergunta] = caixa("lotes_vencendo")
    assert "Leite vence hoje" in pergunta["texto"] and "o que vai fazer com isso?" in pergunta["texto"]
    assert "Ainda dá para usar hoje; a partir de amanhã só sai com motivo." in pergunta["texto"]
    assert pergunta["detalhes"]["ultimo_dia"] is True


def test_contas_vencidas_e_a_vencer_e_pagamento_tira_da_caixa(atacadao, farinha):
    venc = [hoje() - timedelta(days=2), hoje() + timedelta(days=1), hoje() + timedelta(days=20)]
    registrar_compra(fornecedor_id=atacadao, data_compra=hoje(), total=D("300"), condicao="a_prazo",
                     linhas=[{"item_id": farinha.id, "quantidade": D("50"), "unidade": "kg", "valor": D("300")}],
                     parcelas=[{"valor": D("100"), "vencimento": v} for v in venc], autor="dono")
    rodar_rotina()
    [v] = caixa("contas_vencidas")
    assert v["texto"].startswith("Conta vencida: Atacadão, parcela 1 de 3, R$ 100,00, venceu em")
    [a] = caixa("contas_a_vencer")  # só a que vence em até 3 dias
    assert a["texto"].startswith("Conta a pagar amanhã") and "parcela 2 de 3" in a["texto"]
    registrar_pagamento(parcela_id=Parcela.objects.get(numero=1).id, autor="dono")
    rodar_rotina()
    assert caixa("contas_vencidas") == [] and detalhe_decisao(v["decisao_id"])["situacao"] == "sem_efeito"


def test_recebimento_atrasado_e_aviso_de_ajuste(atacadao, farinha):
    r = registrar_compra(fornecedor_id=atacadao, data_compra=hoje() - timedelta(days=8), total=D("60"),
                         condicao="a_vista",
                         linhas=[{"item_id": farinha.id, "quantidade": D("10"), "unidade": "kg", "valor": D("60")}],
                         autor="dono")
    registrar_compra(fornecedor_id=atacadao, data_compra=hoje() - timedelta(days=2), total=D("12"),
                     condicao="a_vista",
                     linhas=[{"item_id": farinha.id, "quantidade": D("2"), "unidade": "kg", "valor": D("12")}],
                     autor="dono")
    rodar_rotina()
    [d] = caixa("recebimento_atrasado")  # a de 2 dias ainda não é atraso
    assert "há 8 dias" in d["texto"] and "Farinha de trigo (10 kg)" in d["texto"]
    encerrar_pendencia(compra_id=r["compra_id"], motivo="fornecedor sem estoque", autor="dono")
    rodar_rotina()
    assert caixa("recebimento_atrasado") == []
    [aviso] = caixa("avisos_ajuste")
    assert "fornecedor sem estoque" in aviso["texto"]
    resolver_aviso(aviso_id=aviso["detalhes"]["aviso_id"], observacao="abateu no boleto", autor="dono")
    rodar_rotina()
    assert caixa("avisos_ajuste") == []


def test_sugestao_de_ficha_pelo_rendimento(bolinha, farinha):
    farinha_em_estoque(farinha)
    for _ in range(4):
        produzir(bolinha, boas=9)
    rodar_rotina()
    assert caixa("ficha_rendimento") == []  # só 4 produções: ainda não sugere
    produzir(bolinha, boas=9)
    rodar_rotina()
    [s] = caixa("ficha_rendimento")
    assert s["tipo"] == "aviso" and s["operacao"] == ""  # só sugere, não muda a ficha
    assert "as últimas 5 produções renderam em média 90% das unidades planejadas" in s["texto"]
    assert D(s["detalhes"]["rendimento_medio"]) == D("0.9") and len(s["detalhes"]["producoes"]) == 5
    produzir(bolinha, boas=10)  # uma produção normal quebra a sequência
    rodar_rotina()
    assert caixa("ficha_rendimento") == [] and Decisao.objects.get(origem="ficha_rendimento").situacao == "sem_efeito"


def test_sugestao_de_ficha_pelo_uso_de_ingrediente(bolinha, farinha):
    farinha_em_estoque(farinha)
    for _ in range(5):
        produzir(bolinha, usado="1150")
    rodar_rotina()
    [s] = caixa("ficha_rendimento")
    assert "usaram em média 115% do Farinha de trigo previsto" in s["texto"] and "renderam" not in s["texto"]
    [ing] = s["detalhes"]["ingredientes"]
    assert ing["item"] == "Farinha de trigo" and D(ing["media"]) == D("1.15")


def test_sincronizar_isola_por_origem():
    sincronizar(origem="a", itens=[{"assunto": "a:1", "texto": "um"}])
    sincronizar(origem="b", itens=[])
    assert [d["assunto"] for d in decisoes()] == ["a:1"]
    with pytest.raises(RegraViolada, match="não pode ser decidida"):
        sincronizar(origem="a", itens=[{"assunto": "a:2", "texto": "x", "operacao": "nada", "parametros": {}}])
    assert Decisao.objects.count() == 1  # a falha não grava nada


def test_comando_rotina_diaria(capsys):
    Item.objects.create(nome="Sal", tipo="ingrediente", unidade_base="g", controla_validade=False,
                        estoque_minimo=D("500"))
    call_command("rotina_diaria")
    call_command("rotina_diaria")
    saida = capsys.readouterr().out
    assert "estoque_baixo: 1 novas" in saida and "estoque_baixo: 0 novas" in saida
    assert Decisao.objects.count() == 1


# ---------- resumo do dia e histórico ----------

def test_resumo_do_dia_soma_os_totais(atacadao, bolinha, farinha):
    farinha_em_estoque(farinha)
    registrar_compra(fornecedor_id=atacadao, data_compra=hoje(), total=D("150"), condicao="a_prazo",
                     linhas=[{"item_id": farinha.id, "quantidade": D("10"), "unidade": "kg", "valor": D("150")}],
                     parcelas=[{"valor": D("100"), "vencimento": hoje() - timedelta(days=1)},
                               {"valor": D("50"), "vencimento": hoje() + timedelta(days=5)}], autor="dono")
    iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")
    Item.objects.create(nome="Sal", tipo="ingrediente", unidade_base="g", controla_validade=False,
                        estoque_minimo=D("500"))
    rodar_rotina()
    r = resumo_do_dia()
    t = r["totais"]
    assert (t["contas_vencidas"], t["valor_contas_vencidas"]) == (1, D("100"))
    assert (t["contas_a_vencer"], t["valor_contas_a_vencer"]) == (1, D("50"))
    assert r["contas"]["total_devido"] == D("150")
    assert (t["compras_a_chegar"], t["compras_atrasadas"]) == (1, 0)
    assert t["producoes_em_andamento"] == 1 and r["producoes"]["em_andamento"][0]["produto"] == bolinha.nome
    assert t["itens_abaixo_do_minimo"] == 1 and r["estoque_baixo"][0]["item"] == "Sal"
    assert t["avisos_pendentes"] == len([d for d in r["decisoes"] if d["tipo"] == "aviso"]) > 0
    assert contar_pendentes()["total"] == t["avisos_pendentes"] + t["decisoes_pendentes"]
    assert t["operacoes_hoje"] >= 3


def test_historico_filtra_por_periodo_autor_canal_e_nome(atacadao):
    salvar_fornecedor(nome="Assaí", autor="agente", canal="agente")
    with pytest.raises(RegraViolada):
        salvar_fornecedor(nome="assai", autor="agente", canal="agente")
    todas = historico_operacoes(de=hoje(), ate=hoje())
    assert [h["nome"] for h in todas] == ["salvar_fornecedor"] * 3
    assert todas[0]["status"] == "erro" and todas[0]["rotulo"] == "Fornecedor salvo"
    assert [h["autor"] for h in historico_operacoes(canal="agente", status="sucesso")] == ["agente"]
    assert len(historico_operacoes(autor="dono")) == 1
    assert historico_operacoes(nome="registrar_compra") == []
    assert historico_operacoes(de=hoje() + timedelta(days=1)) == []
    assert historico_operacoes(ate=hoje() - timedelta(days=1)) == []
    assert len(historico_operacoes(limite=1)) == 1
