import html as _html

import pytest
from django.urls import reverse

from estoque.models import EtiquetaImpressa

pytestmark = pytest.mark.django_db


def texto(r):
    return _html.unescape(r.content.decode())


def test_lote_mostra_saldos_e_origem(client, dono, lote_produzido):
    t = texto(client.get(reverse("lote", args=[lote_produzido.id])))
    assert "9 un" in t and "Resfriado" in t and "Farinha de trigo" in t


def test_mudar_conservacao_pela_tela(client, dono, lote_produzido):
    url = reverse("lote", args=[lote_produzido.id])
    r = client.post(url, {"quantidade": "5", "de": "resfriado", "para": "congelado",
                            "validade_manual": "2030-01-01", "justificativa": "freezer", "chave": "k1"}, follow=True)
    t = texto(r)
    assert "Conservação alterada." in t
    assert "4 un" in t and "5 un" in t and "Congelado" in t and "informada manualmente" in t


def test_etiquetas_tem_uso_interno_e_nao_registram_no_get(client, dono, lote_produzido):
    r = client.get(reverse("etiquetas", args=[lote_produzido.id]), {"estado": "resfriado", "copias": 2})
    t = texto(r)
    assert t.count("USO INTERNO") == 2 and "Validade" in t and "Fabricação" in t
    assert not EtiquetaImpressa.objects.exists()


def test_copias_limitadas_de_1_a_200(client, dono, lote_produzido):
    url = reverse("etiquetas", args=[lote_produzido.id])
    assert texto(client.get(url, {"estado": "resfriado", "copias": 5000})).count("USO INTERNO") == 200
    assert texto(client.get(url, {"estado": "resfriado", "copias": -3})).count("USO INTERNO") == 1
    client.post(url + "?estado=resfriado", {"copias": 999999, "chave": "a"})
    assert EtiquetaImpressa.objects.get().copias == 200


def test_saiu_certo_registra_e_depois_reimpressao(client, dono, lote_produzido):
    url = reverse("etiquetas", args=[lote_produzido.id]) + "?estado=resfriado"
    r = client.post(url, {"copias": 3, "chave": "a"}, follow=True)
    assert "Impressão registrada." in texto(r) and EtiquetaImpressa.objects.get().copias == 3
    r = client.post(url, {"copias": 1, "chave": "b"}, follow=True)
    assert "Reimpressão registrada." in texto(r)
