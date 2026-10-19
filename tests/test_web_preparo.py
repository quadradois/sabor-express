import html as _html
import re
import uuid
from decimal import Decimal as D

import pytest
from django.test import Client

from estoque.models import CriterioValidade
from estoque.servicos import entrada_manual
from producao.models import Producao
from producao.servicos import iniciar_producao

pytestmark = pytest.mark.django_db


def texto(r):
    return _html.unescape(r.content.decode())


@pytest.fixture
def producao(bolinha):
    f = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    entrada_manual(item_id=f.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra", autor="dono")
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="resfriado", dias=3)
    return Producao.objects.get(id=iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"])


def url(p):
    return f"/producao/{p.id}/"


def post(client, p, **dados):
    return client.post(url(p), {"chave": uuid.uuid4().hex, **dados}, follow=True)


def fins(r):
    return re.findall(r'data-fim="([^"]+)"', texto(r))


def test_fluxo_completo_pela_tela(client, dono, producao):
    assert "Mise en place" in texto(client.get(url(producao)))
    post(client, producao, acao="previsto_todos")
    post(client, producao, acao="etapa", indice=1)
    h = texto(client.get(url(producao)))
    assert "Etapa 1 de 2" in h and "Sove a massa" in h and "Iniciar cronômetro (5 min)" in h
    r = post(client, producao, acao="etapa", indice=3)
    assert "Fechamento" in texto(r) and "Só se não houver critério de validade" in texto(r)
    r = post(client, producao, acao="concluir", quantidade_boa=10, perdas=0, estado="resfriado", anotacao="sobrou massa")
    p = Producao.objects.get()
    assert p.status == "concluida" and p.anotacao == "sobrou massa"
    h = texto(client.get(url(producao)))
    assert "Previsto" in h and "1 kg" in h and p.lote.codigo in h and "Cancelar produção" not in h


def test_peso_com_ponto_recusado(client, dono, producao):
    l = producao.linhas.get()
    r = post(client, producao, acao="peso", linha=l.id, usado="1.5")
    assert "Use vírgula para decimais (ex.: 1,5)." in texto(r)
    l.refresh_from_db()
    assert l.usado is None
    post(client, producao, acao="peso", linha=l.id, usado="990,5")
    l.refresh_from_db()
    assert l.usado == D("990.5")
    assert "Usado: 990,5 g" in texto(client.get(url(producao)))


def test_sair_do_mise_en_place_sem_pesar_mostra_erro(client, dono, producao):
    r = post(client, producao, acao="etapa", indice=1)
    assert "Pese ou marque 'usei o previsto' em: Farinha de trigo." in texto(r)
    assert Producao.objects.get().etapa_atual == 0


def test_outro_aparelho_ve_o_mesmo_estado(client, dono, producao, django_user_model):
    post(client, producao, acao="previsto_todos")
    post(client, producao, acao="etapa", indice=1)
    r1 = post(client, producao, acao="cronometro")
    outro = Client()
    outro.force_login(django_user_model.objects.create_user("ajudante", password="x"))
    r2 = outro.get(url(producao))
    assert "Etapa 1 de 2" in texto(r2) and fins(r2) == fins(r1) and len(fins(r1)) == 1
    assert fins(r1)[0].endswith("Z")


def test_cronometro_aparece_em_todas_as_etapas(client, dono, producao):
    post(client, producao, acao="previsto_todos")
    post(client, producao, acao="etapa", indice=1)
    fim = fins(post(client, producao, acao="cronometro"))
    for i in (2, 3, 0):
        assert fins(post(client, producao, acao="etapa", indice=i)) == fim
    c = producao.cronometros.get()
    assert fins(post(client, producao, acao="parar", cronometro=c.id)) == []


def test_cancelar_pede_motivo(client, dono, producao):
    assert "Informe o motivo do cancelamento." in texto(post(client, producao, acao="cancelar", motivo=""))
    r = post(client, producao, acao="cancelar", motivo="faltou gás")
    assert Producao.objects.get().status == "cancelada" and "faltou gás" in texto(r)


def test_tela_carrega_preparo_js(client, dono, producao):
    assert "web/preparo.js" in texto(client.get(url(producao)))
