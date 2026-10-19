from decimal import Decimal as D

import pytest
from django.contrib.auth import get_user_model

from fichas.models import Ficha

pytestmark = pytest.mark.django_db


def test_ficha_invalida_nao_persiste_e_mostra_erro(client):
    client.force_login(get_user_model().objects.create_superuser("adm", password="x"))
    massa = Ficha.objects.create(nome="Massa", tipo="preparacao", rendimento_g=D("1000"))
    antes = Ficha.objects.count()
    dados = {
        "nome": "Coxinha", "tipo": "produto", "ativa": "on", "rendimento_g": "",
        "itens-TOTAL_FORMS": "0", "itens-INITIAL_FORMS": "0",
        "subpreparacoes-TOTAL_FORMS": "0", "subpreparacoes-INITIAL_FORMS": "0",
        "etapas-TOTAL_FORMS": "0", "etapas-INITIAL_FORMS": "0",
        "proporcoes-TOTAL_FORMS": "1", "proporcoes-INITIAL_FORMS": "0",
        "proporcoes-0-preparacao": massa.pk, "proporcoes-0-percentual": "90", "proporcoes-0-ordem": "1",
    }
    r = client.post("/admin/fichas/ficha/add/", dados, follow=True)
    html = r.content.decode()
    assert Ficha.objects.count() == antes
    assert "somam 90%" in html
    assert "foi adicionado com sucesso" not in html
