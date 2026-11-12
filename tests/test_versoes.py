from html.parser import HTMLParser

import pytest

from cadastros.models import Item
from fichas.models import Etapa, Ficha, FichaVersao
from fichas.versoes import salvar_versao, versao_vigente
from nucleo.models import RegistroOperacao

pytestmark = pytest.mark.django_db


class _Form(HTMLParser):
    def __init__(self):
        super().__init__()
        self.dados, self._select, self._textarea = {}, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        nome = a.get("name")
        if tag == "input" and nome and a.get("type") not in ("submit", "button", "file"):
            if a.get("type") == "checkbox":
                if "checked" in a:
                    self.dados[nome] = a.get("value", "on")
            else:
                self.dados[nome] = a.get("value", "")
        elif tag == "select" and nome:
            self._select = nome
            self.dados.setdefault(nome, "")
        elif tag == "option" and self._select and "selected" in a:
            self.dados[self._select] = a.get("value", "")
        elif tag == "textarea" and nome:
            self._textarea = nome
            self.dados[nome] = ""

    def handle_data(self, data):
        if self._textarea:
            self.dados[self._textarea] += data

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None
        elif tag == "textarea":
            self._textarea = None


def dados_admin(client, url):
    p = _Form()
    p.feed(client.get(url).content.decode())
    # ignora os formulários-modelo vazios dos inlines e o campo de busca
    return {k: v for k, v in p.dados.items() if "__prefix__" not in k and k not in ("q", "csrfmiddlewaretoken")}


def test_salvar_versao_so_quando_muda(coxinha):
    v1 = salvar_versao(coxinha)
    assert v1.numero == 1 and salvar_versao(coxinha) == v1
    Etapa.objects.create(ficha=coxinha, ordem=2, instrucao="Empane")
    assert salvar_versao(coxinha).numero == 2


def test_versao_antiga_nao_muda(coxinha):
    v1 = versao_vigente(coxinha)
    antes = v1.conteudo
    assert antes["etapas"] == [["Modele as coxinhas", None, ""]]
    assert antes["proporcoes"][0][2] == "33.000"
    Etapa.objects.filter(ficha=coxinha).update(instrucao="Modele bem")
    salvar_versao(coxinha)
    v1.refresh_from_db()
    assert v1.conteudo == antes and versao_vigente(coxinha).numero == 2


def test_admin_salva_ficha_pelo_nucleo(client, admin_user, coxinha):
    client.force_login(admin_user)
    url = f"/admin/fichas/ficha/{coxinha.pk}/change/"
    dados = dados_admin(client, url) | {"nome": "Coxinha nova"}
    r = client.post(url, dados)
    assert r.status_code == 302
    coxinha.refresh_from_db()
    assert coxinha.nome == "Coxinha nova"
    op = RegistroOperacao.objects.get(nome="salvar_ficha")
    assert op.status == "sucesso" and op.autor == admin_user.username
    v = FichaVersao.objects.get(ficha=coxinha)
    assert v.operacao == op and v.numero == 1


def test_admin_ficha_invalida_nao_cria_versao(client, admin_user, coxinha):
    client.force_login(admin_user)
    url = f"/admin/fichas/ficha/{coxinha.pk}/change/"
    dados = dados_admin(client, url) | {"proporcoes-0-percentual": "23", "nome": "Outra"}
    r = client.post(url, dados, follow=True)
    assert "somam 90%" in r.content.decode()
    assert not FichaVersao.objects.exists()
    coxinha.refresh_from_db()
    assert coxinha.nome == "Coxinha de frango"
    assert coxinha.proporcoes.get(ordem=1).percentual == 33
    assert not RegistroOperacao.objects.exists()  # o atomic do admin desfaz também o registro de erro


def test_admin_salva_item_pelo_nucleo(client, admin_user):
    client.force_login(admin_user)
    dados = dados_admin(client, "/admin/cadastros/item/add/") | {
        "nome": "Sal", "tipo": "ingrediente", "unidade_base": "g",
    }
    r = client.post("/admin/cadastros/item/add/", dados)
    assert r.status_code == 302
    item = Item.objects.get(nome="Sal")
    op = RegistroOperacao.objects.get(nome="salvar_item")
    assert op.status == "sucesso" and op.resultado == {"id": item.pk}


def test_admin_resalvar_sem_mudar_nao_cria_versao(client, admin_user):
    client.force_login(admin_user)
    add = "/admin/fichas/ficha/add/"
    dados = dados_admin(client, add) | {"nome": "Molho", "tipo": "preparacao", "rendimento_g": "500"}
    assert client.post(add, dados).status_code == 302
    ficha = Ficha.objects.get(nome="Molho")
    url = f"/admin/fichas/ficha/{ficha.pk}/change/"
    assert client.post(url, dados_admin(client, url)).status_code == 302
    assert FichaVersao.objects.filter(ficha=ficha).count() == 1


def test_admin_excluir_em_massa_pelo_nucleo(client, admin_user):
    client.force_login(admin_user)
    item = Item.objects.create(nome="Sal", tipo="ingrediente", unidade_base="g", controla_validade=False)
    r = client.post("/admin/cadastros/item/", {
        "action": "delete_selected", "_selected_action": [item.pk], "post": "yes",
    })
    assert r.status_code == 302 and not Item.objects.filter(pk=item.pk).exists()
    op = RegistroOperacao.objects.get(nome="excluir_item")
    assert op.status == "sucesso" and op.parametros == {"id": item.pk}
