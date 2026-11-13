import json
from datetime import timedelta
from decimal import Decimal as D

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone
from mcp.shared.memory import create_connected_server_and_client_session

from agente.compras import quando, reais
from agente.ferramentas import REGISTRO, criar_servidor
from agente.models import Proposta
from cadastros.models import Fornecedor, Item
from cadastros.servicos import salvar_fornecedor
from compras.models import Compra, Recebimento
from compras.servicos import receber_compra, registrar_compra
from estoque.models import ConsumoPendente
from estoque.servicos import saldo
from financeiro.models import AvisoAjuste, Pagamento
from financeiro.servicos import registrar_pagamento
from nucleo.models import RegistroOperacao
from producao.models import Producao
from producao.servicos import usar_previsto_restantes

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


def confirmar(r):
    assert "confirmar" in r, r
    return chamar("confirmar_proposta", proposta_id=r["proposta_id"])


def ferramentas():
    async def acao(s):
        return (await s.list_tools()).tools
    return {t.name: t for t in _sessao(acao)}


@pytest.fixture
def atacadao():
    return Fornecedor.objects.get(id=salvar_fornecedor(nome="Atacadão", autor="dono")["fornecedor_id"])


@pytest.fixture
def makro():
    return Fornecedor.objects.get(id=salvar_fornecedor(nome="Makro", autor="dono")["fornecedor_id"])


@pytest.fixture
def farinha():
    return Item.objects.create(nome="Farinha de trigo", tipo="ingrediente", unidade_base="g", controla_validade=False)


@pytest.fixture
def leite():
    return Item.objects.create(nome="Leite", tipo="ingrediente", unidade_base="mL", controla_validade=True)


def comprar(fornecedor, item, q, un, valor, dias=30, data=None):
    return registrar_compra(fornecedor_id=fornecedor.id, data_compra=data or hoje,
                            linhas=[{"item_id": item.id, "quantidade": D(q), "unidade": un, "valor": D(valor)}],
                            total=D(valor), condicao="a_prazo",
                            parcelas=[{"valor": D(valor), "vencimento": hoje + timedelta(days=dias)}], autor="dono")


def dia(n):
    return quando(hoje + timedelta(days=n))


# --- registro e alçada ----------------------------------------------------------

def test_alcada_das_ferramentas_de_compras():
    nivel = {f.nome: f.nivel for f in REGISTRO}
    leitura = {"buscar_fornecedores", "ver_compras_em_aberto", "ver_falta_receber", "ver_compra", "ver_contas",
               "ver_divida_fornecedores", "ver_avisos_de_ajuste", "ver_consumos_pendentes", "ultimo_preco"}
    assert {n: nivel[n] for n in leitura} == dict.fromkeys(leitura, 0)
    assert (nivel["cadastrar_fornecedor"], nivel["resolver_aviso"]) == (1, 1)
    # tudo que mexe com dinheiro ou estoque espera o "sim"
    for n in ("registrar_compra", "receber_compra", "encerrar_pendencia", "registrar_pagamento", "estornar_pagamento",
              "estornar_recebimento", "cancelar_compra", "devolver_ao_fornecedor", "receber_bonificacao",
              "conciliar_consumo"):
        assert nivel[n] == 2, n
    t = ferramentas()
    assert {n for n in leitura if t[n].annotations.readOnlyHint} == leitura


def test_esquemas_sem_ref_para_o_gemini():
    for nome, t in ferramentas().items():
        assert "$ref" not in json.dumps(t.inputSchema), nome
    itens = ferramentas()["registrar_compra"].inputSchema["properties"]["itens"]["items"]
    assert itens["required"] == ["item", "quantidade", "unidade", "valor"]


def test_falas_de_dinheiro_e_data():
    assert [reais(v) for v in ("90", "1", "12.5", "0.5", "1234.05", "0")] == [
        "90 reais", "1 real", "12 reais e 50 centavos", "50 centavos", "1.234 reais e 5 centavos", "zero real"]
    assert (quando(hoje), dia(1), dia(-1)) == ("hoje", "amanhã", "ontem")
    assert dia(30).startswith("em ")


# --- fornecedores -------------------------------------------------------------------

def test_cadastrar_e_buscar_fornecedor():
    r = chamar("cadastrar_fornecedor", nome="Atacadão", contato="11 99999-0000")
    assert r["dito"] == "Fornecedor Atacadão cadastrado."
    assert chamar("cadastrar_fornecedor", nome="atacadão")["repetida"] is True  # o modelo repetiu
    assert Fornecedor.objects.count() == 1
    assert chamar("buscar_fornecedores", busca="atacadao")["texto"] == "Fornecedores: Atacadão."
    op = RegistroOperacao.objects.get(nome="salvar_fornecedor")
    assert (op.canal, op.autor) == ("agente", "agente-mcp")


def test_fornecedor_repetido_recusado_pelo_nucleo(atacadao):
    assert chamar("cadastrar_fornecedor", nome="ATACADÃO") == {"erro": "Já existe o fornecedor 'Atacadão'."}


# --- registrar compra -------------------------------------------------------------

def test_registrar_compra_falada(atacadao, farinha):
    # "comprei 20 quilos de farinha por 90 reais no Atacadão, pago em 30 dias"
    r = chamar("registrar_compra", fornecedor="atacadao", condicao="a prazo", prazo_dias=30,
               itens=[{"item": "farinha", "quantidade": 20, "unidade": "quilos", "valor": 90}])
    assert r["confirmar"] == (f"Lançar compra do fornecedor Atacadão, hoje: 20 kg de Farinha de trigo por 90 reais. "
                              f"Total 90 reais, a prazo, vence {dia(30)}. Confirma?")
    assert not Compra.objects.exists() and not Proposta.objects.exclude(estado="pendente").exists()
    a, b = confirmar(r), confirmar(r)
    c = Compra.objects.get()
    assert a["dito"] == f"Feito: {r['confirmar'].removesuffix('. Confirma?')}. É a compra {c.id}."
    assert a["resultado"] == b["resultado"]
    assert RegistroOperacao.objects.filter(nome="registrar_compra", status="sucesso").count() == 1
    assert c.conta.parcelas.get().vencimento == hoje + timedelta(days=30)
    l = c.linhas.get()
    assert (l.quantidade, l.unidade, l.quantidade_base, l.custo_unitario) == (D("20"), "kg", D("20000"), D("0.0045"))
    assert c.operacao.canal == "agente"


def test_compra_parcelada_com_frete_e_total_somado_pelo_sistema(atacadao, farinha, leite):
    r = chamar("registrar_compra", fornecedor="Atacadão", condicao="boleto", vencimento=str(hoje + timedelta(days=10)),
               parcelas=2, frete=10, documento="NF 123",
               itens=[{"item": "farinha", "quantidade": 10, "unidade": "kg", "valor": 60},
                      {"item": "leite", "quantidade": 12, "unidade": "litros", "valor": 50.5}])
    assert r["confirmar"] == (
        f"Lançar compra do fornecedor Atacadão, hoje: 10 kg de Farinha de trigo por 60 reais e 12 L de Leite por "
        f"50 reais e 50 centavos, frete de 10 reais. Total 120 reais e 50 centavos, a prazo em 2 parcelas: "
        f"60 reais e 25 centavos {dia(10)} e 60 reais e 25 centavos {dia(40)}, documento NF 123. Confirma?")
    confirmar(r)
    assert [p.valor for p in Compra.objects.get().conta.parcelas.all()] == [D("60.25"), D("60.25")]


def test_compra_a_prazo_sem_vencimento_pergunta(atacadao, farinha):
    r = chamar("registrar_compra", fornecedor="Atacadão", condicao="a_prazo",
               itens=[{"item": "farinha", "quantidade": 20, "unidade": "kg", "valor": 90}])
    assert r == {"erro": "Quando vence? Diga o prazo em dias (ex.: 30) ou a data do vencimento."}
    assert not Proposta.objects.exists()


def test_compra_com_total_divergente_pede_justificativa(atacadao, farinha):
    r = chamar("registrar_compra", fornecedor="Atacadão", condicao="a_vista", total=95,
               itens=[{"item": "farinha", "quantidade": 20, "unidade": "kg", "valor": 90}])
    assert r["erro"].startswith("Os itens somam R$ 90,00 e o total do documento é R$ 95,00")
    r = chamar("registrar_compra", fornecedor="Atacadão", condicao="a_vista", total=95, justificativa="taxa da nota",
               itens=[{"item": "farinha", "quantidade": 20, "unidade": "kg", "valor": 90}], forma_pagamento="pix")
    assert "Total 95 reais, à vista, já pago no pix" in r["confirmar"]


def test_duplicata_entra_no_confirma(atacadao, farinha):
    anterior = comprar(atacadao, farinha, "20", "kg", "90")["compra_id"]
    r = chamar("registrar_compra", fornecedor="Atacadão", condicao="a_prazo", prazo_dias=30,
               itens=[{"item": "farinha", "quantidade": 20, "unidade": "kg", "valor": 90}])
    assert r["confirmar"].endswith(f"Atenção: Possível duplicata: a compra {anterior} é do mesmo fornecedor, na "
                                   "mesma data e com o mesmo total. Confirma?")


def test_compra_ja_recebida_entra_no_estoque(atacadao, farinha, leite):
    validade = hoje + timedelta(days=5)
    itens = [{"item": "farinha", "quantidade": 20, "unidade": "kg", "valor": 90},
             {"item": "leite", "quantidade": 6, "unidade": "L", "valor": 30}]
    r = chamar("registrar_compra", fornecedor="Atacadão", condicao="à vista", ja_recebido=True, itens=itens)
    assert r == {"erro": "Informe a validade de 'Leite'."}  # recusa do núcleo, já na proposta
    itens[1]["validade"] = str(validade)
    r = chamar("registrar_compra", fornecedor="Atacadão", condicao="à vista", ja_recebido=True, itens=itens)
    assert r["confirmar"].endswith(f"de Leite por 30 reais, validade {quando(validade)}. Total 120 reais, à vista, "
                                   "já pago. Já chegou: entra no estoque agora. Confirma?")
    assert saldo(farinha) == 0
    confirmar(r)
    confirmar(r)
    assert (saldo(farinha), saldo(leite)) == (D("20000"), D("6000"))
    assert Compra.objects.get().status == "recebida"
    assert Recebimento.objects.count() == 2


def test_item_ambiguo_e_inexistente(atacadao, farinha):
    Item.objects.create(nome="Farinha de rosca", tipo="ingrediente", unidade_base="g", controla_validade=False)
    r = chamar("registrar_compra", fornecedor="Atacadão", condicao="a_vista",
               itens=[{"item": "farinha", "quantidade": 1, "unidade": "kg", "valor": 5}])
    assert sorted(r["opcoes"]) == ["Farinha de rosca", "Farinha de trigo"]
    r = chamar("registrar_compra", fornecedor="Assaí", condicao="a_vista",
               itens=[{"item": "farinha de trigo", "quantidade": 1, "unidade": "kg", "valor": 5}])
    assert r == {"erro": "Nenhum fornecedor com o nome 'Assaí'."}


# --- recebimento ------------------------------------------------------------------

def test_chegaram_8_dos_10_quilos(atacadao, farinha):
    cid = comprar(atacadao, farinha, "10", "kg", "60")["compra_id"]
    r = chamar("receber_compra", fornecedor="atacadão", item="farinha", quantidade=8, unidade="quilos")
    assert r["confirmar"] == (f"Receber da compra {cid}, fornecedor Atacadão: 8 kg de Farinha de trigo. "
                              "Fica faltando 2 kg de Farinha de trigo. Confirma?")
    assert saldo(farinha) == 0
    confirmar(r)
    confirmar(r)
    assert saldo(farinha) == D("8000")
    assert Compra.objects.get().status == "parcial"
    v = chamar("ver_falta_receber")
    assert v["texto"] == f"Falta receber: 2 kg de Farinha de trigo, fornecedor Atacadão, compra {cid} de hoje."
    # o resto chega: sem quantidade, recebe tudo o que falta
    r = chamar("receber_compra", item="farinha")
    assert r["confirmar"].endswith("2 kg de Farinha de trigo. Com isso a compra fica completa. Confirma?")
    confirmar(r)
    assert Compra.objects.get().status == "recebida"


def test_receber_com_duas_compras_pede_qual(atacadao, makro, farinha):
    a = comprar(atacadao, farinha, "10", "kg", "60")["compra_id"]
    b = comprar(makro, farinha, "5", "kg", "35")["compra_id"]
    r = chamar("receber_compra", item="farinha")
    assert r["opcoes"] == [f"Compra {a}, fornecedor Atacadão, de hoje: falta 10 kg de Farinha de trigo",
                           f"Compra {b}, fornecedor Makro, de hoje: falta 5 kg de Farinha de trigo"]
    assert not Proposta.objects.exists()
    assert chamar("receber_compra", item="farinha", fornecedor="makro")["confirmar"].startswith(f"Receber da compra {b}")
    assert chamar("receber_compra", item="farinha", compra_id=a)["confirmar"].startswith(f"Receber da compra {a}")


def test_receber_varios_itens_e_chegou_tudo(atacadao, farinha, leite):
    r = registrar_compra(fornecedor_id=atacadao.id, data_compra=hoje, total=D("90"), condicao="a_vista",
                         linhas=[{"item_id": farinha.id, "quantidade": "10", "unidade": "kg", "valor": "60"},
                                 {"item_id": leite.id, "quantidade": "6", "unidade": "L", "valor": "30"}], autor="dono")
    validade = str(hoje + timedelta(days=4))
    p = chamar("receber_compra", fornecedor="Atacadão", itens=[
        {"item": "farinha", "quantidade": 4, "unidade": "kg"}, {"item": "leite", "validade": validade}])
    assert p["confirmar"] == (f"Receber da compra {r['compra_id']}, fornecedor Atacadão: 4 kg de Farinha de trigo e "
                              f"6 L de Leite, validade {dia(4)}. Fica faltando 6 kg de Farinha de trigo. Confirma?")
    chamar("recusar_proposta", proposta_id=p["proposta_id"])
    # "chegou tudo do Atacadão, o leite vence dia tal": a validade vale para quem controla validade
    p = chamar("receber_compra", fornecedor="Atacadão", validade=validade)
    confirmar(p)
    assert (saldo(farinha), saldo(leite)) == (D("10000"), D("6000"))
    assert Recebimento.objects.get(linha__item=farinha).lote.validade is None


def test_recusas_do_recebimento_viram_erro_falavel(atacadao, farinha, leite):
    comprar(atacadao, farinha, "10", "kg", "60")
    assert chamar("receber_compra", item="farinha", quantidade=12, unidade="kg") == {
        "erro": "'Farinha de trigo': só faltam receber 10 kg. O excesso entra como bonificação (sem custo) "
                "ou numa nova compra."}
    comprar(atacadao, leite, "6", "L", "30")
    assert chamar("receber_compra", item="leite") == {"erro": "Informe a validade de 'Leite'."}
    assert chamar("receber_compra", item="óleo") == {"erro": "Nada de 'óleo' esperando entrega."}
    assert not Proposta.objects.exists()


def test_encerrar_pendencia_e_resolver_aviso(atacadao, farinha):
    cid = comprar(atacadao, farinha, "10", "kg", "60")["compra_id"]
    l = Compra.objects.get().linhas.get()
    receber_compra(compra_id=cid, linhas=[{"linha_id": l.id, "quantidade": "8"}], autor="dono")
    r = chamar("encerrar_pendencia", fornecedor="Atacadão", motivo="acabou no fornecedor")
    assert r["confirmar"] == (f"Encerrar o que falta da compra {cid}, fornecedor Atacadão: 2 kg de Farinha de trigo "
                              "não vai ser entregue (motivo: acabou no fornecedor). O valor da conta não muda; fica um "
                              "aviso para ajustar no pagamento. Confirma?")
    assert not AvisoAjuste.objects.exists()
    confirmar(r)
    assert Compra.objects.get().status == "encerrada"
    v = chamar("ver_avisos_de_ajuste")
    aviso = AvisoAjuste.objects.get()
    assert v["texto"].startswith(f"1 aviso de ajuste em aberto. Aviso {aviso.id}: Compra {cid}: não entregue 2 kg")
    r = chamar("resolver_aviso", observacao="o Atacadão abateu no boleto")
    assert r["dito"] == f"Aviso {aviso.id} resolvido: o Atacadão abateu no boleto."
    assert chamar("resolver_aviso", observacao="de novo") == {"erro": "Não há aviso de ajuste em aberto."}
    assert chamar("ver_avisos_de_ajuste")["texto"] == "Nenhum aviso de ajuste em aberto."


def test_estornar_recebimento(atacadao, farinha):
    cid = comprar(atacadao, farinha, "10", "kg", "60")["compra_id"]
    l = Compra.objects.get().linhas.get()
    receber_compra(compra_id=cid, linhas=[{"linha_id": l.id, "quantidade": "10"}], autor="dono")
    r = chamar("estornar_recebimento", fornecedor="Atacadão", motivo="lancei errado")
    assert r["confirmar"] == (f"Estornar o recebimento de 10 kg de Farinha de trigo, compra {cid}, fornecedor "
                              "Atacadão, recebido hoje (motivo: lancei errado). Sai do estoque e volta a ficar "
                              "pendente de entrega. Confirma?")
    confirmar(r)
    assert saldo(farinha) == 0
    assert Compra.objects.get().status == "aprovada"
    assert chamar("estornar_recebimento", fornecedor="Atacadão", motivo="x") == {
        "erro": "Nenhum recebimento encontrado para estornar."}


def test_devolver_e_bonificar(atacadao, farinha):
    cid = comprar(atacadao, farinha, "10", "kg", "60")["compra_id"]
    l = Compra.objects.get().linhas.get()
    receber_compra(compra_id=cid, linhas=[{"linha_id": l.id, "quantidade": "10"}], autor="dono")
    r = chamar("devolver_ao_fornecedor", item="farinha", quantidade=1, unidade="kg", motivo="saco furado")
    assert r["confirmar"] == (f"Devolver 1 kg de Farinha de trigo ao fornecedor Atacadão, compra {cid} (motivo: saco "
                              "furado). Ficam 9 kg nesse lote. O valor da conta não muda; fica um aviso para ajustar "
                              "no pagamento. Confirma?")
    confirmar(r)
    assert saldo(farinha) == D("9000") and AvisoAjuste.objects.count() == 1
    r = chamar("receber_bonificacao", item="farinha", quantidade=500, unidade="gramas", motivo="brinde",
               fornecedor="Atacadão")
    assert r["confirmar"] == ("Entrada de 500 g de Farinha de trigo como bonificação, sem custo "
                              "(motivo: brinde (Atacadão)). Confirma?")
    confirmar(r)
    assert saldo(farinha) == D("9500")


def test_cancelar_compra(atacadao, farinha):
    a = comprar(atacadao, farinha, "10", "kg", "60")["compra_id"]
    r = chamar("cancelar_compra", fornecedor="Atacadão", motivo="lancei em dobro")
    assert r["confirmar"] == (f"Cancelar a compra {a}, fornecedor Atacadão, de hoje, total 60 reais; a conta a pagar "
                              "é cancelada junto (motivo: lancei em dobro). Confirma?")
    confirmar(r)
    assert Compra.objects.get().status == "cancelada"
    b = comprar(atacadao, farinha, "10", "kg", "60")["compra_id"]
    registrar_pagamento(parcela_id=Compra.objects.get(id=b).conta.parcelas.get().id, autor="dono")
    assert chamar("cancelar_compra", compra_id=b, motivo="x") == {
        "erro": "Esta compra já tem pagamento anotado: estorne o pagamento antes de cancelar."}


# --- contas a pagar ------------------------------------------------------------------

def test_quanto_devo_e_paguei_o_boleto(atacadao, makro, farinha):
    comprar(atacadao, farinha, "10", "kg", "60", dias=-3)
    cid = comprar(atacadao, farinha, "20", "kg", "90", dias=30)["compra_id"]
    comprar(makro, farinha, "5", "kg", "35", dias=5)
    d = chamar("ver_divida_fornecedores", fornecedor="atacadao")
    assert d["texto"] == (f"Com o fornecedor Atacadão, você deve 150 reais em 2 parcelas, 60 reais já vencidos. "
                          f"A mais antiga: parcela única, 60 reais, venceu {dia(-3)}.")
    assert d["total"] == {"valor": 150.0, "texto": "150 reais"}
    assert chamar("ver_divida_fornecedores")["texto"] == (
        "Você deve 185 reais no total. Atacadão, 150 reais, sendo 60 reais vencidos; Makro, 35 reais.")
    v = chamar("ver_contas", situacao="vencidas")
    assert v["texto"].startswith("1 conta vencida, somando 60 reais. Atacadão, compra")
    assert chamar("ver_contas", situacao="a_vencer", dias=7)["total"]["valor"] == 35.0
    assert chamar("ver_contas")["texto"].startswith("3 contas em aberto, somando 185 reais, dos quais 60 reais já vencidos.")

    # duas compras em aberto no Atacadão: pergunta qual; o valor dito desfaz a dúvida
    r = chamar("registrar_pagamento", fornecedor="Atacadão")
    assert len(r["opcoes"]) == 2 and "venceu" in r["opcoes"][0]
    r = chamar("registrar_pagamento", fornecedor="Atacadão", valor=90, forma="pix")
    assert r["confirmar"] == (f"Anotar que você pagou 90 reais hoje ao fornecedor Atacadão, compra {cid}, parcela "
                              f"única, 90 reais, vence {dia(30)}, no pix. A parcela fica quitada. Confirma?")
    assert not Pagamento.objects.exists()
    confirmar(r)
    confirmar(r)
    assert Pagamento.objects.get().operacao.canal == "agente"
    # sobrou uma conta: vai direto nela, com juros
    r = chamar("registrar_pagamento", fornecedor="Atacadão", juros=2.5, motivo_diferenca="atraso")
    assert "pagou 62 reais e 50 centavos hoje" in r["confirmar"] and "com 2 reais e 50 centavos de juros" in r["confirmar"]
    confirmar(r)
    assert chamar("ver_divida_fornecedores", fornecedor="Atacadão")["texto"] == "Nada em aberto com o fornecedor Atacadão."


def test_pagamento_parcial_e_parcelas_da_mesma_compra(atacadao, farinha):
    registrar_compra(fornecedor_id=atacadao.id, data_compra=hoje, total=D("100"), condicao="a_prazo",
                     linhas=[{"item_id": farinha.id, "quantidade": "10", "unidade": "kg", "valor": "100"}],
                     parcelas=[{"valor": "50", "vencimento": hoje + timedelta(days=30)},
                               {"valor": "50", "vencimento": hoje + timedelta(days=60)}], autor="dono")
    r = chamar("registrar_pagamento", fornecedor="Atacadão", valor=20)
    assert "parcela 1 de 2, 50 reais" in r["confirmar"]  # mesma compra: a mais antiga
    assert r["confirmar"].endswith("Ficam faltando 30 reais nesta parcela. Confirma?")
    assert chamar("registrar_pagamento", fornecedor="Atacadão", valor=80)["erro"] == (
        "O valor passa do saldo da parcela (R$ 50,00).")
    assert chamar("registrar_pagamento", fornecedor="Atacadão", juros=1, multa=1) == {
        "erro": "Diga só um entre juros, multa e desconto."}
    assert chamar("registrar_pagamento", fornecedor="Atacadão", juros=1)["erro"] == "Informe o motivo da diferença."


def test_estornar_pagamento(atacadao, farinha):
    cid = comprar(atacadao, farinha, "10", "kg", "60")["compra_id"]
    registrar_pagamento(parcela_id=Compra.objects.get(id=cid).conta.parcelas.get().id, autor="dono")
    r = chamar("estornar_pagamento", fornecedor="Atacadão", motivo="paguei outro boleto")
    assert r["confirmar"] == (f"Estornar o pagamento de 60 reais pagos hoje, Compra {cid} — Atacadão (motivo: paguei "
                              "outro boleto). A parcela volta a ficar em aberto com 60 reais. Confirma?")
    confirmar(r)
    assert Pagamento.objects.get().estorno_operacao is not None
    assert chamar("estornar_pagamento", fornecedor="Atacadão", motivo="x") == {
        "erro": "Nenhum pagamento anotado do fornecedor Atacadão."}


# --- consultas -------------------------------------------------------------------

def test_compras_em_aberto_ver_compra_e_ultimo_preco(atacadao, farinha):
    assert chamar("ultimo_preco", item="farinha")["texto"] == "Ainda não há compra de Farinha de trigo."
    cid = comprar(atacadao, farinha, "20", "kg", "90")["compra_id"]
    l = Compra.objects.get().linhas.get()
    receber_compra(compra_id=cid, linhas=[{"linha_id": l.id, "quantidade": "15"}], autor="dono")
    assert chamar("ver_compras_em_aberto", fornecedor="atacadão")["texto"] == (
        f"1 compra do fornecedor Atacadão esperando entrega. Compra {cid}, fornecedor Atacadão, comprada hoje: "
        "falta 5 kg de Farinha de trigo.")
    v = chamar("ver_compra", compra_id=cid)
    assert v["texto"] == (f"Compra {cid}, fornecedor Atacadão, hoje, total 90 reais, parcialmente recebida. Itens: "
                          f"20 kg de Farinha de trigo, chegaram 15 kg, faltam 5 kg. Conta: parcela única, 90 reais, "
                          f"vence {dia(30)}.")
    assert v["linhas"][0]["pendente"]["texto"] == "5 kg"
    assert chamar("ultimo_preco", item="farinha")["texto"] == (
        "Última compra de Farinha de trigo: fornecedor Atacadão, hoje, 4 reais e 50 centavos o quilo, "
        "já com frete e desconto rateados.")
    assert chamar("ver_compra", compra_id=999) == {"erro": "Compra não encontrada."}


# --- consumo pendente ------------------------------------------------------------

def test_produzir_sem_estoque_e_conciliar_quando_chega(bolinha, atacadao):
    farinha = Item.objects.get(nome="Farinha de trigo")
    assert chamar("iniciar_producao", produto="bolinha", unidades=10)["erro"].startswith("Falta 1 kg")
    r = chamar("iniciar_producao", produto="bolinha", unidades=10, justificativa_falta="farinha chega à tarde")
    assert r["confirmar"] == ("Iniciar a produção de 10 Bolinha 100 g, cru, mesmo faltando estoque (farinha chega à "
                              "tarde): o que faltar fica pendente de conciliar. Confirma?")
    confirmar(r)
    p = Producao.objects.get()
    usar_previsto_restantes(producao_id=p.id, autor="dono")
    r = chamar("concluir_producao", quantidade_boa=10, conservacao="fresco", validade=str(hoje + timedelta(days=1)),
               justificativa="sem critério")
    assert "Sem estoque, fica pendente de conciliar: 1 kg de Farinha de trigo" in r["confirmar"]
    confirmar(r)
    assert chamar("ver_consumos_pendentes")["texto"] == (
        f"1 consumo pendente. 1 kg de Farinha de trigo da produção {p.id}, ainda sem lote com saldo.")
    assert chamar("conciliar_consumo", item="farinha")["erro"] == (
        "Ainda não há lote de Farinha de trigo com 1 kg disponíveis para conciliar.")

    comprar(atacadao, farinha, "2", "kg", "10")
    r = confirmar(chamar("receber_compra", item="farinha"))
    assert r["dito"].endswith(f"Há consumo pendente que pode ser conciliado com o que entrou: 1 kg de Farinha de trigo "
                              f"da produção {p.id}. Quer conciliar?")
    r = chamar("conciliar_consumo", item="farinha")
    assert r["confirmar"] == ("Conciliar 1 kg de Farinha de trigo da produção "
                              f"{p.id} com o lote sem código: custo de 5 reais. O custo da produção fica fechado. Confirma?")
    assert ConsumoPendente.objects.get().lote is None
    confirmar(r)
    confirmar(r)
    p.refresh_from_db()
    assert (p.custo_pendente, p.custo_total) == (False, D("5.00"))
    assert saldo(farinha) == D("1000")
    assert chamar("ver_consumos_pendentes")["texto"] == "Nenhum consumo pendente."
