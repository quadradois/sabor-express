import datetime as dt
import html as _html
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Item
from cadastros.servicos import salvar_fornecedor
from compras.servicos import registrar_compra
from financeiro.models import Conta, Pagamento, Parcela

pytestmark = pytest.mark.django_db
HOJE = timezone.localdate


def texto(r):
    return _html.unescape(r.content.decode())


@pytest.fixture
def conta():
    f = salvar_fornecedor(nome="Atacadão", autor="dono")["fornecedor_id"]
    farinha = Item.objects.create(nome="Farinha", tipo="ingrediente", unidade_base="g", controla_validade=False)
    venc = [HOJE() - dt.timedelta(days=2), HOJE() + dt.timedelta(days=5)]
    r = registrar_compra(fornecedor_id=f, data_compra=HOJE() - dt.timedelta(days=10), total=D("200"),
                         linhas=[{"item_id": farinha.id, "quantidade": D("50"), "unidade": "kg", "valor": D("200")}],
                         condicao="a_prazo", parcelas=[{"valor": D("100"), "vencimento": v} for v in venc],
                         autor="dono")
    return Conta.objects.get(id=r["conta_id"])


def test_contas_mostra_vencidas_a_vencer_e_por_fornecedor(client, dono, conta):
    t = texto(client.get(reverse("contas")))
    assert "2 dia(s) de atraso" in t and "Atacadão" in t and "R$ 200,00" in t
    assert "vencido R$ 100,00" in t


def test_inicio_resume_contas(client, dono, conta):
    t = texto(client.get(reverse("inicio")))
    assert "1 parcela(s) vencida(s)" in t and "1 parcela(s) a vencer" in t


def test_paguei_parcial_com_juros(client, dono, conta):
    p1 = conta.parcelas.get(numero=1)
    r = client.post(reverse("pagar"), {"parcela": p1.id, "valor": "40", "forma": "pix", "diferenca": "2,50",
                                       "diferenca_tipo": "juros", "diferenca_motivo": "atraso", "chave": "p1"}, follow=True)
    assert "Pagamento registrado." in texto(r)
    pg = Pagamento.objects.get()
    assert pg.valor == D("40") and pg.diferenca == D("2.50") and pg.diferenca_tipo == "juros"


def test_paguei_saldo_quita(client, dono, conta):
    p1 = conta.parcelas.get(numero=1)
    t = texto(client.post(reverse("pagar"), {"parcela": p1.id, "chave": "p1"}, follow=True))
    assert "Parcela quitada." in t


def test_paguei_volta_para_a_compra(client, dono, conta):
    p1 = conta.parcelas.get(numero=1)
    url = reverse("compra", args=[conta.compra_id])
    r = client.post(reverse("pagar"), {"parcela": p1.id, "chave": "p1", "next": url})
    assert r.status_code == 302 and r.url == url


def test_paguei_nao_redireciona_para_fora(client, dono, conta):
    p1 = conta.parcelas.get(numero=1)
    r = client.post(reverse("pagar"), {"parcela": p1.id, "chave": "p1", "next": "https://mau.example/"})
    assert r.url == reverse("contas")


def test_paguei_acima_do_saldo_recusado(client, dono, conta):
    p1 = conta.parcelas.get(numero=1)
    t = texto(client.post(reverse("pagar"), {"parcela": p1.id, "valor": "500", "chave": "p1"}, follow=True))
    assert "erro" in t and not Pagamento.objects.exists()


def test_paguei_diferenca_sem_tipo_recusada(client, dono, conta):
    p1 = conta.parcelas.get(numero=1)
    client.post(reverse("pagar"), {"parcela": p1.id, "diferenca": "5", "chave": "p1"})
    assert not Pagamento.objects.exists()


def test_estornar_pagamento(client, dono, conta):
    p1 = conta.parcelas.get(numero=1)
    client.post(reverse("pagar"), {"parcela": p1.id, "chave": "p1"})
    pg = Pagamento.objects.get()
    t = texto(client.post(reverse("estornar_pagamento"), {"pagamento": pg.id, "motivo": "", "chave": "s0"}, follow=True))
    assert "motivo" in t.lower() and not Pagamento.objects.get().estorno_operacao_id
    t = texto(client.post(reverse("estornar_pagamento"), {"pagamento": pg.id, "motivo": "errei", "chave": "s1"}, follow=True))
    assert "Pagamento estornado." in t and Pagamento.objects.get().estorno_operacao_id


def test_duplo_envio_um_pagamento(client, dono, conta):
    p1 = conta.parcelas.get(numero=1)
    d = {"parcela": p1.id, "valor": "10", "chave": "unica"}
    client.post(reverse("pagar"), d)
    client.post(reverse("pagar"), d)
    assert Pagamento.objects.count() == 1


def test_resolver_aviso_sem_observacao_recusado(client, dono, conta):
    from compras.servicos import encerrar_pendencia
    encerrar_pendencia(compra_id=conta.compra_id, motivo="x", autor="dono")
    aviso = conta.avisos.get()
    t = texto(client.post(reverse("avisos"), {"aviso": aviso.id, "observacao": "", "chave": "a0"}, follow=True))
    assert "observa" in t.lower() and aviso.__class__.objects.get(id=aviso.id).resolvido_operacao_id is None
