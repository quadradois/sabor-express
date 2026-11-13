import datetime as dt
from decimal import Decimal as D

import pytest
from django.utils import timezone

from estoque.etiquetas import dados_etiqueta, registrar_impressao
from estoque.models import EtiquetaImpressa, Lote, Movimento
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db
hoje = timezone.localdate()


@pytest.fixture
def lote(bolinha):
    l = Lote.objects.create(item=bolinha, forma="cru", codigo="L1", validade=hoje + dt.timedelta(days=3), custo_unitario=D("1"))
    Movimento.objects.create(tipo="entrada_producao", item=bolinha, lote=l, quantidade=D("250"), quantidade_informada=D("250"),
                             unidade_informada="un", fator=D("1"), motivo="x", estado="resfriado", validade=l.validade,
                             validade_manual=True)
    return l


def imprimir(l, copias):
    return registrar_impressao(lote_id=l.id, estado="resfriado", copias=copias, autor="dono")


def test_impressao_e_reimpressao(lote):
    assert imprimir(lote, 10)["reimpressao"] is False
    assert imprimir(lote, 2)["reimpressao"] is True
    assert [(e.copias, e.reimpressao) for e in EtiquetaImpressa.objects.order_by("id")] == [(10, False), (2, True)]
    assert Lote.objects.get(id=lote.id).validade == lote.validade


def test_dados_etiqueta_iguais_ao_lote(lote):
    assert dados_etiqueta(lote, "resfriado") == {
        "produto": lote.item.nome, "lote": "L1", "fabricacao": timezone.localdate(lote.criado_em),
        "dia_producao": timezone.localdate(lote.criado_em).day, "nome_lote": "lote do dia "
        f"{timezone.localdate(lote.criado_em).day}",
        "validade": lote.validade, "validade_manual": True, "conservacao": "Resfriado", "forma": "Cru",
        "quantidade": D("250")}


def test_copias_zero_recusa(lote):
    with pytest.raises(RegraViolada):
        imprimir(lote, 0)
    assert not EtiquetaImpressa.objects.exists()
