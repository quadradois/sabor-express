import datetime as dt
import html as _html
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Fornecedor, Item
from cadastros.servicos import salvar_fornecedor
from compras.models import Compra, Recebimento
from compras.servicos import registrar_compra
from financeiro.models import Conta
from estoque.models import ConsumoPendente
from estoque.servicos import saldo
from producao.models import Producao

pytestmark = pytest.mark.django_db


def texto(r):
    return _html.unescape(r.content.decode())


@pytest.fixture
def atacadao():
    return Fornecedor.objects.get(id=salvar_fornecedor(nome="Atacadão", autor="dono")["fornecedor_id"])


@pytest.fixture
def farinha():
    return Item.objects.create(nome="Farinha de trigo", tipo="ingrediente", unidade_base="g", controla_validade=False)


@pytest.fixture
def leite():
    return Item.objects.create(nome="Leite", tipo="ingrediente", unidade_base="mL", controla_validade=True)


@pytest.fixture
def compra10kg(atacadao, farinha):
    r = registrar_compra(fornecedor_id=atacadao.id, data_compra=timezone.localdate(), total=D("60"),
                         linhas=[{"item_id": farinha.id, "quantidade": D("10"), "unidade": "kg", "valor": D("60")}],
                         condicao="a_prazo", parcelas=[{"valor": D("60"), "vencimento": timezone.localdate()}],
                         autor="dono")
    return Compra.objects.get(id=r["compra_id"])


def dados_compra(atacadao, farinha, **extra):
    d = {"chave": "c1", "fornecedor": atacadao.id, "item_0": farinha.id, "quantidade_0": "10", "unidade_0": "kg",
         "valor_0": "60,00", "total": "60,00", "condicao": "a_vista", "forma_pagamento": "pix"}
    return d | extra


def test_telas_abrem(client, dono, compra10kg):
    for nome in ["fornecedores", "fornecedor_novo", "compras", "compra_nova", "falta_receber", "bonificacao",
                 "contas", "avisos", "consumos", "inicio"]:
        assert client.get(reverse(nome)).status_code == 200, nome
    assert client.get(reverse("compra", args=[compra10kg.id])).status_code == 200
    assert client.get(reverse("compra", args=[9999])).status_code == 404


def test_fornecedor_criar_editar_inativar(client, dono):
    r = client.post(reverse("fornecedor_novo"), {"nome": "Mercadão", "chave": "f1"}, follow=True)
    assert "Fornecedor salvo." in texto(r) and "Mercadão" in texto(r)
    f = Fornecedor.objects.get(nome="Mercadão")
    client.post(reverse("fornecedor", args=[f.id]), {"nome": "Mercadão Sul", "contato": "9999", "chave": "f2"})
    assert Fornecedor.objects.get(id=f.id).nome == "Mercadão Sul"
    r = client.post(reverse("fornecedor", args=[f.id]), {"acao": "inativar", "chave": "f3"}, follow=True)
    assert "Fornecedor inativado." in texto(r) and not Fornecedor.objects.get(id=f.id).ativo


def test_fornecedor_nome_vazio_recusado(client, dono):
    r = client.post(reverse("fornecedor_novo"), {"nome": " ", "chave": "f1"})
    assert r.status_code == 200 and "nome" in texto(r).lower() and not Fornecedor.objects.exists()


def test_compra_a_vista_com_recebi_tudo(client, dono, atacadao, farinha):
    r = client.post(reverse("compra_nova"), dados_compra(atacadao, farinha, recebi_tudo="1"), follow=True)
    t = texto(r)
    assert "Compra lançada." in t and "Tudo recebido no estoque." in t
    assert saldo(farinha.id) == D("10000")
    assert Recebimento.objects.count() == 1


def test_compra_a_prazo_em_parcelas(client, dono, atacadao, farinha):
    d = dados_compra(atacadao, farinha, condicao="a_prazo", parcelas_n="3", primeiro_vencimento="2030-01-10")
    client.post(reverse("compra_nova"), d)
    c = Conta.objects.get()
    assert [p.valor for p in c.parcelas.order_by("numero")] == [D("20"), D("20"), D("20")]


def test_compra_recusada_mostra_mensagem(client, dono, atacadao, farinha):
    r = client.post(reverse("compra_nova"), dados_compra(atacadao, farinha, total="99"))
    assert r.status_code == 200 and not Compra.objects.exists()
    assert "erro" in r.content.decode()


def test_compra_duplicada_avisa_e_deixa_lancar_mesmo_assim(client, dono, atacadao, farinha, compra10kg):
    d = dados_compra(atacadao, farinha, chave="c2")
    t = texto(client.post(reverse("compra_nova"), d))
    assert "Compra parecida" in t and Compra.objects.count() == 1
    client.post(reverse("compra_nova"), d | {"ciente": "1", "chave": "c3"})
    assert Compra.objects.count() == 2


def test_duplo_envio_uma_compra(client, dono, atacadao, farinha):
    d = dados_compra(atacadao, farinha)
    client.post(reverse("compra_nova"), d)
    client.post(reverse("compra_nova"), d | {"ciente": "1"})
    assert Compra.objects.count() == 1


def test_recebimento_parcial_depois_total(client, dono, compra10kg, farinha):
    url = reverse("compra", args=[compra10kg.id])
    linha = compra10kg.linhas.get()
    r = client.post(url, {"acao": "receber", f"quantidade_{linha.id}": "4", f"lote_{linha.id}": "L1", "chave": "r1"}, follow=True)
    t = texto(r)
    assert "Recebimento registrado." in t and "falta 6 kg" in t
    assert saldo(farinha.id) == D("4000")
    client.post(url, {"acao": "receber", f"quantidade_{linha.id}": "6", "chave": "r2"})
    compra10kg.refresh_from_db()
    assert compra10kg.status == "recebida"


def test_recebimento_excesso_recusado(client, dono, compra10kg):
    linha = compra10kg.linhas.get()
    r = client.post(reverse("compra", args=[compra10kg.id]),
                    {"acao": "receber", f"quantidade_{linha.id}": "11", "chave": "r1"}, follow=True)
    assert "só faltam receber" in texto(r).lower()
    assert not Recebimento.objects.exists()


def test_recebimento_exige_validade(client, dono, atacadao, leite):
    r = registrar_compra(fornecedor_id=atacadao.id, data_compra=timezone.localdate(), total=D("10"),
                         linhas=[{"item_id": leite.id, "quantidade": D("2"), "unidade": "L", "valor": D("10")}],
                         condicao="a_vista", autor="dono")
    linha = Compra.objects.get(id=r["compra_id"]).linhas.get()
    t = texto(client.post(reverse("compra", args=[r["compra_id"]]),
                          {"acao": "receber", f"quantidade_{linha.id}": "2", "chave": "r1"}, follow=True))
    assert "validade" in t.lower() and not Recebimento.objects.exists()


def test_encerrar_pendencia_e_aviso(client, dono, compra10kg):
    linha = compra10kg.linhas.get()
    url = reverse("compra", args=[compra10kg.id])
    client.post(url, {"acao": "receber", f"quantidade_{linha.id}": "4", "chave": "r1"})
    assert "motivo" in texto(client.post(url, {"acao": "encerrar", "motivo": "", "chave": "e0"}, follow=True)).lower()
    t = texto(client.post(url, {"acao": "encerrar", "motivo": "faltou no fornecedor", "chave": "e1"}, follow=True))
    assert "Pendência encerrada." in t
    avisos = texto(client.get(reverse("avisos")))
    aviso = Conta.objects.get().avisos.get()
    t = texto(client.post(reverse("avisos"), {"aviso": aviso.id, "observacao": "acertado por telefone", "chave": "a1"}, follow=True))
    assert "Aviso resolvido." in t and avisos != t


def test_estornar_recebimento_e_devolver(client, dono, compra10kg, farinha):
    url = reverse("compra", args=[compra10kg.id])
    linha = compra10kg.linhas.get()
    client.post(url, {"acao": "receber", f"quantidade_{linha.id}": "10", "chave": "r1"})
    rec = Recebimento.objects.get()
    t = texto(client.post(url, {"acao": "devolver", "lote_id": rec.lote_id, "quantidade": "1000", "motivo": "estragou", "chave": "d1"}, follow=True))
    assert "Devolução registrada." in t and saldo(farinha.id) == D("9000")
    t = texto(client.post(url, {"acao": "estornar_recebimento", "recebimento_id": rec.id, "motivo": "", "chave": "s0"}, follow=True))
    assert "motivo" in t.lower()


def test_cancelar_compra(client, dono, compra10kg):
    t = texto(client.post(reverse("compra", args=[compra10kg.id]), {"acao": "cancelar", "motivo": "errei", "chave": "x1"}, follow=True))
    compra10kg.refresh_from_db()
    assert compra10kg.status == "cancelada" and "Compra cancelada." in t


def test_cancelar_sem_motivo_recusado(client, dono, compra10kg):
    t = texto(client.post(reverse("compra", args=[compra10kg.id]), {"acao": "cancelar", "motivo": "", "chave": "x1"}, follow=True))
    compra10kg.refresh_from_db()
    assert compra10kg.status != "cancelada" and "motivo" in t.lower()


def test_falta_receber_lista_pendencia(client, dono, compra10kg):
    t = texto(client.get(reverse("falta_receber")))
    assert "Farinha de trigo" in t and "falta 10 kg" in t


def test_bonificacao(client, dono, farinha):
    r = client.post(reverse("bonificacao"), {"item": farinha.id, "quantidade": "2", "unidade": "kg", "motivo": "brinde", "chave": "b1"}, follow=True)
    assert "Bonificação recebida" in texto(r) and saldo(farinha.id) == D("2000")
    r = client.post(reverse("bonificacao"), {"item": farinha.id, "quantidade": "2", "unidade": "kg", "motivo": "", "chave": "b2"})
    assert "motivo" in texto(r).lower() and saldo(farinha.id) == D("2000")


def test_comecar_producao_com_falta_e_justificar(client, dono, bolinha):
    # a farinha da bolinha é outra: faltando → recusa sem justificativa, aceita com
    d = {"produto": bolinha.id, "unidades": 10, "forma": "cru", "chave": "p1"}
    assert "Falta" in texto(client.post("/producao/nova/", d)) and not Producao.objects.exists()
    t = texto(client.get("/producao/nova/", {"produto": bolinha.id, "unidades": 10, "forma": "cru"}))
    assert "Justificativa para começar com falta" in t
    r = client.post("/producao/nova/", d | {"chave": "p2", "pendente_justificativa": "nota atrasada"})
    assert r.status_code == 302 and Producao.objects.count() == 1


def test_consumos_pendentes_concilia(client, dono, bolinha):
    from producao.servicos import concluir_producao, iniciar_producao, usar_previsto_restantes
    from compras.servicos import receber_compra
    farinha = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono", pendente_justificativa="nota atrasada")["producao_id"]
    usar_previsto_restantes(producao_id=p, autor="dono")
    concluir_producao(producao_id=p, quantidade_boa=9, perdas=1, perda_motivo="rasgou", estado="resfriado",
                      validade_manual=timezone.localdate(), justificativa="t", autor="dono")
    pend = ConsumoPendente.objects.get()
    assert "Farinha de trigo" in texto(client.get(reverse("consumos")))
    f = salvar_fornecedor(nome="X", autor="dono")["fornecedor_id"]
    r = registrar_compra(fornecedor_id=f, data_compra=timezone.localdate(), total=D("10"), condicao="a_vista",
                         linhas=[{"item_id": farinha.id, "quantidade": D("2"), "unidade": "kg", "valor": D("10")}], autor="dono")
    rec = receber_compra(compra_id=r["compra_id"], linhas=[{"linha_id": r["linhas"][0]["linha_id"], "quantidade": D("2")}], autor="dono")
    t = texto(client.post(reverse("consumos"), {"pendente": pend.id, "lote": rec["recebimentos"][0]["lote_id"], "chave": "k1"}, follow=True))
    pend.refresh_from_db()
    assert "Consumo conciliado" in t and pend.lote_id
