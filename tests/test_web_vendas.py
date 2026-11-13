"""Plano 6, fase 2a: telas de vendas, encomendas, fritura, sobras, clientes, preços e contas a receber.
Cada tela abre, cada formulário grava pelo serviço e o erro de regra aparece na tela."""
import datetime as dt
import html as _html
import re
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Cliente, Item
from cadastros.servicos import salvar_cliente
from estoque.models import CriterioValidade, Lote, Movimento
from estoque.servicos import saldo, saldo_lote
from financeiro.models import Conta, Pagamento, Parcela
from nucleo.models import RegistroOperacao
from vendas.consultas import total_dos_itens
from vendas.models import Apresentacao, Encomenda, Reserva, Venda
from vendas.servicos import criar_encomenda, registrar_venda, salvar_apresentacao

pytestmark = pytest.mark.django_db
HOJE = timezone.localdate()


def dia(n):
    return HOJE + dt.timedelta(days=n)


def texto(r):
    return _html.unescape(r.content.decode())


def limpo(r):
    """O texto da página como se lê na tela: sem tags e com espaços simples."""
    return " ".join(re.sub(r"<[^>]+>", " ", texto(r)).split())


@pytest.fixture
def coxinha():
    return Item.objects.create(nome="Coxinha 150 g", tipo="produto", unidade_base="un", oleo_ref_un=D("0.05"))


def lote(produto, n, *, validade, forma="cru", estado="congelado", custo="0.60", codigo=""):
    l = Lote.objects.create(item=produto, codigo=codigo, forma=forma, validade=validade, custo_unitario=D(custo))
    Movimento.objects.create(tipo="entrada_producao", item=produto, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado=estado, validade=validade)
    return l


@pytest.fixture
def unidade(coxinha):
    return salvar_apresentacao(produto_id=coxinha.id, nome="unidade", forma="cru", estado="congelado", unidades=1,
                               preco_varejo=D("5"), preco_atacado=D("4"), autor="dono")["apresentacao_id"]


@pytest.fixture
def estoque(coxinha):
    return lote(coxinha, 20, validade=dia(30), codigo="K1")


@pytest.fixture
def joao():
    return salvar_cliente(nome="João", autor="dono")["cliente_id"]


def venda_post(unidade, **extra):
    return {"chave": "v1", "tabela": "varejo", "condicao": "a_vista", f"qtd_{unidade}": "3", **extra}


# ---------- acesso ----------

NOMES = ["vender", "vendas", "encomendas", "encomenda_nova", "necessidade", "fritura", "sobras", "clientes",
         "cliente_novo", "precos", "preco_novo", "receber"]


def test_telas_exigem_login(client):
    for nome in NOMES:
        assert client.get(reverse(nome)).status_code == 302, nome
    for nome in ("anotar_recebimento", "estornar_recebimento_cliente"):
        assert client.post(reverse(nome), {}).status_code == 302, nome
    assert client.post(reverse("cancelar_venda", args=[1]), {}).status_code == 302
    assert client.post(reverse("descartar", args=[1]), {}).status_code == 302
    assert client.get(reverse("encomenda", args=[1])).status_code == 302


def test_telas_abrem(client, dono, coxinha, unidade, estoque, joao):
    for nome in NOMES + ["inicio"]:
        assert client.get(reverse(nome)).status_code == 200, nome
    e = criar_encomenda(cliente_id=joao, entrega_data=dia(1), itens=[{"apresentacao_id": unidade, "quantidade": 2}],
                        autor="dono")["encomenda_id"]
    assert client.get(reverse("encomenda", args=[e])).status_code == 200
    assert client.get(reverse("encomenda", args=[9999])).status_code == 404
    assert client.get(reverse("cliente", args=[joao])).status_code == 200
    assert client.get(reverse("cliente", args=[9999])).status_code == 404
    assert client.get(reverse("preco", args=[unidade])).status_code == 200
    assert client.get(reverse("preco", args=[9999])).status_code == 404
    assert client.get(reverse("fritura"), {"produto": coxinha.id}).status_code == 200
    assert client.get(reverse("vendas"), {"de": "lixo"}).status_code == 200
    for sit in ("abertas", "pronta", "entregue", "todas", "invalida"):
        assert client.get(reverse("encomendas"), {"situacao": sit}).status_code == 200
    assert client.get(reverse("encomendas"), {"periodo": "hoje"}).status_code == 200


def test_vender_mostra_apresentacoes_com_precos_e_estoque(client, dono, unidade, estoque):
    t = texto(client.get(reverse("vender")))
    assert "Coxinha 150 g" in t and "R$ 5,00" in t and "R$ 4,00" in t and "Dá para vender" in t
    assert "20" in t


# ---------- vender ----------

def test_venda_a_vista_grava_pelo_servico(client, dono, coxinha, unidade, estoque):
    r = client.post(reverse("vender"), venda_post(unidade, forma_pagamento="pix"), follow=True)
    t = texto(r)
    assert "Venda 1 registrada: R$ 15,00." in t and "Venda 1" in t
    v = Venda.objects.get()
    assert (v.total, v.recebido_na_hora, v.forma_pagamento) == (D("15"), D("15"), "pix")
    assert saldo(coxinha) == 17
    assert RegistroOperacao.objects.get(nome="registrar_venda").canal == "web"


def test_venda_atacado_e_desconto_manual(client, dono, unidade, estoque):
    client.post(reverse("vender"), venda_post(unidade, tabela="atacado", **{f"preco_{unidade}": "3,50"}))
    l = Venda.objects.get().linhas.get()
    assert (l.preco_tabela, l.preco, l.total) == (D("4"), D("3.50"), D("10.50"))


def test_dois_envios_com_a_mesma_chave_uma_venda(client, dono, coxinha, unidade, estoque):
    d = venda_post(unidade)
    client.post(reverse("vender"), d)
    client.post(reverse("vender"), d)
    assert Venda.objects.count() == 1 and saldo(coxinha) == 17


def test_venda_sem_estoque_mostra_a_mensagem_e_nao_grava(client, dono, coxinha, unidade, estoque):
    r = client.post(reverse("vender"), venda_post(unidade, **{f"qtd_{unidade}": "25"}))
    t = texto(r)
    assert r.status_code == 200 and "Só há 20 un" in t and 'class="erro"' in t
    assert Venda.objects.count() == 0 and saldo(coxinha) == 20
    assert 'value="25"' in t  # não perde o que foi digitado


def test_venda_sem_item_ou_quantidade_invalida_e_recusada(client, dono, unidade, estoque):
    assert "ao menos um item" in texto(client.post(reverse("vender"), {"chave": "a", "condicao": "a_vista"}))
    assert "número inteiro" in texto(client.post(reverse("vender"), venda_post(unidade, **{f"qtd_{unidade}": "1,5"})))
    assert "Formulário sem chave" in texto(client.post(reverse("vender"), {f"qtd_{unidade}": "1"}))
    assert Venda.objects.count() == 0


def test_venda_a_prazo_divide_as_parcelas_e_vira_conta_a_receber(client, dono, unidade, estoque, joao):
    r = client.post(reverse("vender"), venda_post(unidade, condicao="a_prazo", cliente=joao, parcelas_n="2",
                                                 primeiro_vencimento="2030-01-10", intervalo="15",
                                                 **{f"qtd_{unidade}": "5"}), follow=True)
    assert "virou conta a receber" in texto(r)
    c = Conta.objects.get()
    assert (c.tipo, c.cliente_id, c.total) == ("receber", joao, D("25"))
    assert [(p.valor, p.vencimento) for p in c.parcelas.order_by("numero")] == [
        (D("12.50"), dt.date(2030, 1, 10)), (D("12.50"), dt.date(2030, 1, 25))]
    assert Venda.objects.get().recebido_na_hora == 0


def test_venda_a_prazo_sem_cliente_e_recusada_e_nada_grava(client, dono, coxinha, unidade, estoque):
    t = texto(client.post(reverse("vender"), venda_post(unidade, condicao="a_prazo")))
    assert "precisa do cliente" in t and not Venda.objects.exists() and not Conta.objects.exists()


def test_total_dos_itens_usa_a_regra_do_servico(unidade):
    assert total_dos_itens(itens=[{"apresentacao_id": unidade, "quantidade": 3}]) == D("15")
    assert total_dos_itens(itens=[{"apresentacao_id": unidade, "quantidade": 3, "preco": "4.50"}]) == D("13.50")
    assert total_dos_itens(itens=[{"apresentacao_id": unidade, "quantidade": 3}], tabela="atacado") == D("12")


# ---------- vendas do dia e cancelamento ----------

def test_vendas_do_dia_com_totais(client, dono, unidade, estoque):
    registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 2}], forma_pagamento="pix", autor="dono")
    t = limpo(client.get(reverse("vendas")))
    assert "1 venda(s): R$ 10,00" in t and "Pix: R$ 10,00" in t and "2 × Coxinha 150 g" in t


def test_cancelar_venda_vai_para_perda_por_padrao(client, dono, coxinha, unidade, estoque):
    v = registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 3}], autor="dono")["venda_id"]
    r = client.post(reverse("cancelar_venda", args=[v]), {"motivo": "desistiu", "chave": "c1"}, follow=True)
    assert f"Venda {v} cancelada." in texto(r) and "R$ 15,00" in texto(r)
    venda = Venda.objects.get()
    assert (venda.situacao, venda.destino, saldo(coxinha)) == ("cancelada", "perda", 17)


def test_cancelar_venda_volta_ao_estoque_e_exige_motivo(client, dono, coxinha, unidade, estoque):
    v = registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 3}], autor="dono")["venda_id"]
    r = client.post(reverse("cancelar_venda", args=[v]), {"motivo": "", "chave": "c1"}, follow=True)
    assert "motivo" in texto(r).lower() and Venda.objects.get().situacao == "concluida"
    r = client.post(reverse("cancelar_venda", args=[v]), {"motivo": "voltou fechado", "destino": "estoque",
                                                          "chave": "c2"}, follow=True)
    assert "voltaram ao estoque" in texto(r) and saldo_lote(estoque, "congelado") == 20


# ---------- encomendas ----------

def encomenda_post(unidade, joao, **extra):
    return {"chave": "e1", "cliente": joao, "entrega_data": dia(2).isoformat(), "entrega_hora": "15:30",
            "modo": "retirada", "tabela": "varejo", f"qtd_{unidade}": "30", "sinal": "20,00", "sinal_forma": "pix"} | extra


def test_encomenda_nova_reserva_o_que_ha_e_mostra_o_que_falta(client, dono, coxinha, unidade, estoque, joao):
    r = client.post(reverse("encomenda_nova"), encomenda_post(unidade, joao), follow=True)
    t = texto(r)
    e = Encomenda.objects.get()
    assert (e.total, e.sinal, e.entrega_hora) == (D("150"), D("20"), dt.time(15, 30))
    assert "faltam 10 un" in t and "falta reservar 10 un" in t and "reservado 20 de 30 un" in t
    assert "Completar reserva" in t and "Entregar" not in t.split("Completar reserva")[1].split("Cancelar")[0]
    assert Reserva.objects.get().quantidade == 20


def test_encomenda_erros_aparecem_e_mantem_o_digitado(client, dono, unidade, estoque, joao):
    t = texto(client.post(reverse("encomenda_nova"), encomenda_post(unidade, joao, cliente="")))
    assert "precisa do cliente" in t and f'value="{dia(2).isoformat()}"' in t
    t = texto(client.post(reverse("encomenda_nova"), encomenda_post(unidade, joao, entrega_data=dia(-1).isoformat())))
    assert "já passou" in t
    t = texto(client.post(reverse("encomenda_nova"), encomenda_post(unidade, joao, sinal="999")))
    assert "sinal deve ficar entre" in t
    assert not Encomenda.objects.exists()


def test_encomenda_lista_filtra_por_situacao_e_dia(client, dono, coxinha, unidade, estoque, joao):
    pronta = criar_encomenda(cliente_id=joao, entrega_data=HOJE, itens=[{"apresentacao_id": unidade, "quantidade": 5}],
                             autor="dono")["encomenda_id"]
    falta = criar_encomenda(cliente_id=joao, entrega_data=dia(3), itens=[{"apresentacao_id": unidade, "quantidade": 40}],
                            autor="dono")["encomenda_id"]
    t = texto(client.get(reverse("encomendas")))
    assert f"#{pronta} João" in t and f"#{falta} João" in t and "pronta" in t and "falta 25 un" in t
    t = texto(client.get(reverse("encomendas"), {"periodo": "hoje"}))
    assert f"#{pronta} João" in t and f"#{falta} João" not in t
    t = texto(client.get(reverse("encomendas"), {"situacao": "pronta"}))
    assert f"#{pronta} João" in t and f"#{falta} João" not in t


def test_completar_reserva_quando_entra_estoque(client, dono, coxinha, unidade, estoque, joao):
    e = criar_encomenda(cliente_id=joao, entrega_data=dia(2), itens=[{"apresentacao_id": unidade, "quantidade": 30}],
                        autor="dono")["encomenda_id"]
    url = reverse("encomenda", args=[e])
    t = texto(client.post(url, {"acao": "completar", "chave": "k1"}, follow=True))
    assert "Ainda faltam 10 un" in t
    lote(coxinha, 20, validade=dia(30), codigo="K2")
    t = texto(client.post(url, {"acao": "completar", "chave": "k2"}, follow=True))
    assert "Tudo reservado" in t and "Entregar e fechar a venda" in t


def test_entregar_a_vista_vira_venda_uma_vez(client, dono, coxinha, unidade, estoque, joao):
    e = criar_encomenda(cliente_id=joao, entrega_data=HOJE, sinal="10",
                        itens=[{"apresentacao_id": unidade, "quantidade": 5}], autor="dono")["encomenda_id"]
    url = reverse("encomenda", args=[e])
    d = {"acao": "entregar", "condicao": "a_vista", "forma_pagamento": "dinheiro", "chave": "ent1"}
    t = texto(client.post(url, d, follow=True))
    assert "Encomenda entregue" in t and "Saldo: R$ 15,00" in t
    client.post(url, d, follow=True)
    v = Venda.objects.get()
    assert (v.encomenda_id, v.recebido_na_hora, saldo(coxinha)) == (e, D("15"), 15)
    t = texto(client.post(url, d | {"chave": "ent2"}, follow=True))
    assert "já foi entregue" in t and Venda.objects.count() == 1


def test_entregar_a_prazo_divide_o_saldo(client, dono, coxinha, unidade, estoque, joao):
    e = criar_encomenda(cliente_id=joao, entrega_data=HOJE, sinal="5",
                        itens=[{"apresentacao_id": unidade, "quantidade": 5}], autor="dono")["encomenda_id"]
    client.post(reverse("encomenda", args=[e]), {"acao": "entregar", "condicao": "a_prazo", "parcelas_n": "2",
                                                 "primeiro_vencimento": "2030-03-01", "chave": "ent1"})
    c = Conta.objects.get()
    assert (c.tipo, c.total) == ("receber", D("20")) and [p.valor for p in c.parcelas.order_by("numero")] == [D("10"), D("10")]


def test_entregar_faltando_reserva_mostra_erro_na_tela(client, dono, unidade, estoque, joao):
    e = criar_encomenda(cliente_id=joao, entrega_data=HOJE, itens=[{"apresentacao_id": unidade, "quantidade": 30}],
                        autor="dono")["encomenda_id"]
    r = client.post(reverse("encomenda", args=[e]), {"acao": "entregar", "chave": "x"})
    assert r.status_code == 200 and "Falta reservar 10 un" in texto(r) and not Venda.objects.exists()


def test_cancelar_encomenda_libera_reserva_e_devolve_o_sinal(client, dono, unidade, estoque, joao):
    e = criar_encomenda(cliente_id=joao, entrega_data=dia(2), sinal="20",
                        itens=[{"apresentacao_id": unidade, "quantidade": 5}], autor="dono")["encomenda_id"]
    url = reverse("encomenda", args=[e])
    t = texto(client.post(url, {"acao": "cancelar", "motivo": "", "chave": "c1"}))
    assert "motivo" in texto(client.post(url, {"acao": "cancelar", "motivo": "", "chave": "c1b"})).lower()
    t = texto(client.post(url, {"acao": "cancelar", "motivo": "mudou a data", "devolver_sinal": "1", "chave": "c2"},
                          follow=True))
    assert "Encomenda cancelada" in t and "Sinal devolvido: R$ 20,00" in t
    enc = Encomenda.objects.get()
    assert (enc.situacao, enc.sinal_devolvido) == ("cancelada", D("20"))
    assert Reserva.objects.get().situacao == "liberada"
    assert "Ação desconhecida" in texto(client.post(url, {"acao": "x", "chave": "c3"}))


# ---------- necessidade de produção ----------

def test_necessidade_leva_a_producao_sem_criar_nenhuma(client, dono, coxinha, unidade, estoque, joao):
    criar_encomenda(cliente_id=joao, entrega_data=dia(1), itens=[{"apresentacao_id": unidade, "quantidade": 50}],
                    autor="dono")
    t = texto(client.get(reverse("necessidade")))
    assert "Coxinha 150 g" in t and "produzir 30 un" in t
    assert f"produto={coxinha.id}&unidades=30&forma=cru" in t
    from producao.models import Producao
    assert not Producao.objects.exists()


def test_necessidade_vazia(client, dono):
    assert "Nada a produzir" in texto(client.get(reverse("necessidade")))


# ---------- fritura e sobras ----------

def test_fritura_registra_pelo_servico_e_mostra_o_custo(client, dono, coxinha, estoque):
    CriterioValidade.objects.create(produto=coxinha, forma="frito", estado="fresco", dias=1)
    t = texto(client.get(reverse("fritura"), {"produto": coxinha.id}))
    assert "lote K1" in t and "(vence primeiro)" in t and f'value="{estoque.id}|congelado"' in t
    d = {"chave": "f1", "produto": coxinha.id, "porcao": f"{estoque.id}|congelado", "quantidade": "10", "boas": "9",
         "perda_motivo": "estourou", "estado_destino": "fresco"}
    t = texto(client.post(reverse("fritura"), d, follow=True))
    assert "Fritura registrada: 9 boas e 1 perdas" in t and "R$ 0,72 por unidade" in t
    frito = Lote.objects.get(forma="frito")
    assert (saldo_lote(estoque, "congelado"), saldo_lote(frito, "fresco")) == (10, 9)
    client.post(reverse("fritura"), d)  # mesma chave: nada em dobro
    assert Lote.objects.filter(forma="frito").count() == 1


def test_fritura_erros_aparecem(client, dono, coxinha, estoque):
    CriterioValidade.objects.create(produto=coxinha, forma="frito", estado="fresco", dias=1)
    base = {"chave": "f1", "produto": coxinha.id, "porcao": f"{estoque.id}|congelado", "quantidade": "10", "boas": "9"}
    assert "motivo das perdas" in texto(client.post(reverse("fritura"), base))
    assert "Escolha o lote" in texto(client.post(reverse("fritura"), base | {"porcao": ""}))
    assert "Só há 20 un" in texto(client.post(reverse("fritura"), base | {"quantidade": "50", "boas": "50"}))
    assert "confirme a perda total" in texto(client.post(reverse("fritura"), base | {
        "boas": "0", "perda_motivo": "queimou"}))
    assert not Lote.objects.filter(forma="frito").exists()


@pytest.fixture
def frito(coxinha):
    return lote(coxinha, 12, validade=dia(1), forma="frito", estado="fresco", custo="0.70", codigo="F1")


def test_sobras_listam_e_perda_registra_pelo_servico(client, dono, coxinha, frito):
    t = texto(client.get(reverse("sobras")))
    assert "Coxinha 150 g" in t and "F1" in t and "12 un" in t
    r = client.post(reverse("sobras"), {"lote": frito.id, "estado": "fresco", "quantidade": "12",
                                         "motivo": "sobra do dia", "chave": "s1"}, follow=True)
    assert "Perda registrada: 12 un" in texto(r) and saldo(coxinha) == 0
    m = Movimento.objects.get(tipo="perda")
    assert m.motivo == "sobra do dia" and "Nenhuma sobra frita" in texto(r)


def test_sobras_perda_sem_motivo_ou_demais_mostra_erro(client, dono, coxinha, frito):
    t = texto(client.post(reverse("sobras"), {"lote": frito.id, "estado": "fresco", "quantidade": "3", "motivo": " ",
                                               "chave": "s1"}, follow=True))
    assert "motivo da perda" in t
    t = texto(client.post(reverse("sobras"), {"lote": frito.id, "estado": "fresco", "quantidade": "99", "motivo": "x",
                                               "chave": "s2"}, follow=True))
    assert "Só há 12 un" in t and saldo(coxinha) == 12


def test_descartar_vencido_pela_tela_do_lote_e_pelo_hoje(client, dono, coxinha):
    velho = lote(coxinha, 7, validade=dia(-2), codigo="VELHO")
    assert "Vencido" in texto(client.get(reverse("lote", args=[velho.id])))
    hoje = texto(client.get(reverse("inicio")))
    assert reverse("descartar", args=[velho.id]) in hoje
    r = client.post(reverse("descartar", args=[velho.id]), {"estado": "congelado", "quantidade": "7",
                                                            "motivo": "vencido", "chave": "d1", "next": "/"}, follow=True)
    assert "Descartado: 7 un" in texto(r) and saldo(coxinha) == 0
    assert Movimento.objects.get(tipo="perda").motivo == "vencido"
    lote_ok = lote(coxinha, 3, validade=dia(9))
    assert "Vencido" not in texto(client.get(reverse("lote", args=[lote_ok.id])))
    r = client.post(reverse("descartar", args=[lote_ok.id]), {"estado": "congelado", "quantidade": "1",
                                                              "motivo": "", "chave": "d2"}, follow=True)
    assert "motivo da perda" in texto(r)


# ---------- clientes ----------

def test_cliente_criar_editar_inativar(client, dono):
    r = client.post(reverse("cliente_novo"), {"nome": "Maria", "contato": "9999", "chave": "c1"}, follow=True)
    assert "Cliente salvo." in texto(r) and "Maria" in texto(r)
    c = Cliente.objects.get(nome="Maria")
    client.post(reverse("cliente", args=[c.id]), {"nome": "Maria Souza", "contato": "8888", "chave": "c2"})
    assert Cliente.objects.get(id=c.id).nome == "Maria Souza"
    r = client.post(reverse("cliente", args=[c.id]), {"acao": "inativar", "chave": "c3"}, follow=True)
    assert "Cliente inativado." in texto(r) and not Cliente.objects.get(id=c.id).ativo
    assert "inativo" in texto(r)
    r = client.post(reverse("cliente", args=[c.id]), {"acao": "reativar", "chave": "c4"}, follow=True)
    assert Cliente.objects.get(id=c.id).ativo


def test_cliente_repetido_ou_sem_nome_mostra_erro(client, dono, joao):
    t = texto(client.post(reverse("cliente_novo"), {"nome": " JOAO ", "chave": "c1"}))
    assert "Já existe o cliente" in t and Cliente.objects.count() == 1
    assert "nome do cliente" in texto(client.post(reverse("cliente_novo"), {"nome": " ", "chave": "c2"}))


# ---------- preços ----------

def test_preco_criar_e_editar(client, dono, coxinha):
    d = {"chave": "p1", "produto": coxinha.id, "nome": "caixa com 25", "forma": "cru", "estado": "congelado",
         "unidades": "25", "preco_varejo": "45,00", "preco_atacado": "40,50", "ativo": "1"}
    r = client.post(reverse("preco_novo"), d, follow=True)
    assert "Preço salvo" in texto(r) and "R$ 45,00" in texto(r) and "R$ 40,50" in texto(r)
    a = Apresentacao.objects.get()
    assert (a.unidades, a.preco_varejo, a.preco_atacado) == (25, D("45"), D("40.50"))
    t = texto(client.get(reverse("preco", args=[a.id])))
    assert 'value="45,00"' in t and 'value="40,50"' in t
    client.post(reverse("preco", args=[a.id]), d | {"chave": "p2", "preco_varejo": "50", "preco_atacado": ""})
    a.refresh_from_db()
    assert (a.preco_varejo, a.preco_atacado) == (D("50"), None)
    client.post(reverse("preco", args=[a.id]), d | {"chave": "p3", "ativo": "", "preco_varejo": "50"})
    assert not Apresentacao.objects.get().ativo
    assert "inativa" in texto(client.get(reverse("precos")))


def test_preco_erros_aparecem(client, dono, coxinha):
    d = {"chave": "p1", "produto": coxinha.id, "nome": "unidade", "forma": "cru", "estado": "congelado",
         "unidades": "1", "preco_varejo": "5", "ativo": "1"}
    assert "Preço de varejo" in texto(client.post(reverse("preco_novo"), d | {"preco_varejo": "5.50"}))
    assert "preço de varejo" in texto(client.post(reverse("preco_novo"), d | {"preco_varejo": ""})).lower()
    assert "Produto: escolha" in texto(client.post(reverse("preco_novo"), d | {"produto": ""}))
    client.post(reverse("preco_novo"), d)
    assert "já tem a apresentação" in texto(client.post(reverse("preco_novo"), d | {"chave": "p2"}))
    assert Apresentacao.objects.count() == 1


# ---------- contas a receber ----------

@pytest.fixture
def fiado(coxinha, unidade, estoque, joao):
    r = registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 20}], condicao="a_prazo", cliente_id=joao,
                        parcelas=[{"valor": "50", "vencimento": dia(-3)}, {"valor": "50", "vencimento": dia(4)}],
                        autor="dono")
    return Conta.objects.get(id=r["conta_id"])


def test_receber_mostra_vencidas_a_vencer_e_por_cliente(client, dono, fiado):
    t = texto(client.get(reverse("receber")))
    assert "3 dia(s) de atraso" in t and "João" in t and "R$ 100,00" in t and "vencido R$ 50,00" in t
    assert "Nada vencido." not in t
    t = texto(client.get(reverse("receber"), {"cliente": fiado.cliente_id}))
    assert "João" in t and "parcela 2/2" in t and "Em aberto" in t


def test_anotar_recebimento_parcial_e_quitando(client, dono, fiado):
    p1 = fiado.parcelas.get(numero=1)
    t = texto(client.post(reverse("anotar_recebimento"), {"parcela": p1.id, "valor": "20", "forma": "pix",
                                                           "chave": "r1"}, follow=True))
    assert "Recebimento anotado: R$ 20,00." in t and "Ainda falta R$ 30,00" in t
    t = texto(client.post(reverse("anotar_recebimento"), {"parcela": p1.id, "chave": "r2"}, follow=True))
    assert "Parcela quitada." in t
    assert Pagamento.objects.count() == 2


def test_anotar_recebimento_duas_vezes_mesma_chave_um_recebimento(client, dono, fiado):
    d = {"parcela": fiado.parcelas.get(numero=1).id, "valor": "10", "chave": "r1"}
    client.post(reverse("anotar_recebimento"), d)
    client.post(reverse("anotar_recebimento"), d)
    assert Pagamento.objects.count() == 1


def test_anotar_recebimento_erro_aparece(client, dono, fiado):
    t = texto(client.post(reverse("anotar_recebimento"), {"parcela": fiado.parcelas.get(numero=1).id,
                                                           "valor": "999", "chave": "r1"}, follow=True))
    assert 'class="erro"' in t and not Pagamento.objects.exists()
    assert "Parcela: escolha" in texto(client.post(reverse("anotar_recebimento"), {"chave": "r2"}, follow=True))
    assert client.get(reverse("anotar_recebimento")).status_code == 302


def test_estornar_recebimento(client, dono, fiado):
    p1 = fiado.parcelas.get(numero=1)
    client.post(reverse("anotar_recebimento"), {"parcela": p1.id, "chave": "r1"})
    pg = Pagamento.objects.get()
    assert "Estornar recebimento" in texto(client.get(reverse("receber")))
    t = texto(client.post(reverse("estornar_recebimento_cliente"), {"pagamento": pg.id, "motivo": "", "chave": "e1"},
                          follow=True))
    assert "motivo" in t.lower() and not Pagamento.objects.get().estorno_operacao_id
    t = texto(client.post(reverse("estornar_recebimento_cliente"), {"pagamento": pg.id, "motivo": "pix não caiu",
                                                                     "chave": "e2"}, follow=True))
    assert "Recebimento estornado." in t and Pagamento.objects.get().estorno_operacao_id


def test_contas_a_pagar_nao_mostram_recebiveis_e_o_pagar_recusa_parcela_de_cliente(client, dono, fiado):
    assert "João" not in texto(client.get(reverse("contas")))
    t = texto(client.post(reverse("pagar"), {"parcela": fiado.parcelas.get(numero=1).id, "chave": "p1"}, follow=True))
    assert "anote como recebimento" in t and not Pagamento.objects.exists()


# ---------- Hoje ----------

def test_hoje_mostra_os_blocos_novos(client, dono, coxinha, unidade, estoque, joao, frito):
    registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 4}], forma_pagamento="pix", autor="dono")
    registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 2}], condicao="a_prazo", cliente_id=joao,
                    parcelas=[{"valor": "10", "vencimento": dia(-2)}], autor="dono")
    criar_encomenda(cliente_id=joao, entrega_data=dia(1), itens=[{"apresentacao_id": unidade, "quantidade": 30}],
                    autor="dono")
    Lote.objects.filter(id=frito.id).update(criado_em=timezone.now() - dt.timedelta(days=1))
    r = client.get(reverse("inicio"))
    t, bruto = limpo(r), texto(r)
    assert "Vendas de hoje" in t and "2 venda(s): R$ 30,00" in t and "entrou R$ 20,00, a prazo R$ 10,00" in t
    assert "#1 João" in t and "falta 16 un" in t and "Falta produzir:" in t
    assert "1 parcela(s) vencida(s): R$ 10,00" in t and "Total a receber: R$ 10,00" in t
    assert "Sobras fritas" in t and "F1" not in t and "Coxinha 150 g" in t
    for nome in ("vender", "vendas", "encomendas", "necessidade", "fritura", "sobras", "receber", "clientes", "precos"):
        assert f'href="{reverse(nome)}"' in bruto, nome


def test_caixa_traz_origens_novas_com_rotulo_e_link(client, dono, coxinha, unidade, estoque, joao):
    from decisoes.geradores import rodar_rotina
    registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 2}], condicao="a_prazo", cliente_id=joao,
                    parcelas=[{"valor": "10", "vencimento": dia(-2)}], autor="dono")
    criar_encomenda(cliente_id=joao, entrega_data=dia(1), itens=[{"apresentacao_id": unidade, "quantidade": 30}],
                    autor="dono")
    rodar_rotina()
    t = texto(client.get(reverse("caixa")))
    assert "Encomenda sem estoque" in t and "Cliente atrasado" in t
    assert reverse("receber") in t and reverse("encomenda", args=[1]) in t
