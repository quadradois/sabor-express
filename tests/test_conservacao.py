import datetime as dt
from decimal import Decimal as D

import pytest
from django.utils import timezone

from estoque.models import CriterioValidade, Lote, Movimento
from estoque.servicos import calcular_validade, saldo_lote, transferir_estado, validade_porcao
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db
hoje = timezone.localdate()


@pytest.fixture
def lote(bolinha):
    CriterioValidade.objects.create(produto=bolinha, forma="cru", estado="congelado", dias=60)
    l = Lote.objects.create(item=bolinha, forma="cru", validade=hoje + dt.timedelta(days=3), custo_unitario=D("1"))
    Movimento.objects.create(tipo="entrada_producao", item=bolinha, lote=l, quantidade=D("250"), quantidade_informada=D("250"),
                             unidade_informada="un", fator=D("1"), motivo="x", estado="resfriado", validade=l.validade)
    return l


def transf(l, q="200", para="congelado", **kw):
    return transferir_estado(lote_id=l.id, quantidade=D(q), de="resfriado", para=para, autor="dono", **kw)


def test_transferir_parcial_mantem_lote(lote):
    r = transf(lote)
    assert (saldo_lote(lote, "resfriado"), saldo_lote(lote, "congelado")) == (D("50"), D("200"))
    assert validade_porcao(lote, "congelado") == hoje + dt.timedelta(days=60)
    assert r == {"lote_id": lote.id, "validade": (hoje + dt.timedelta(days=60)).isoformat(), "validade_manual": False}


def test_transferir_mais_que_a_porcao_recusa(lote):
    with pytest.raises(RegraViolada, match=r"Só há 250 un em resfriado\."):
        transf(lote, "300")


def test_recusas_basicas(lote):
    with pytest.raises(RegraViolada):
        transf(lote, "0")
    with pytest.raises(RegraViolada):
        transf(lote, para="resfriado")
    with pytest.raises(RegraViolada):
        transf(lote, para="quente")


def test_sem_criterio_exige_validade_e_justificativa(lote):
    with pytest.raises(RegraViolada, match="Sem critério de validade"):
        transf(lote, para="fresco")
    with pytest.raises(RegraViolada, match="Justifique"):
        transf(lote, para="fresco", validade_manual=hoje + dt.timedelta(days=2))
    assert saldo_lote(lote, "fresco") == 0


def test_validade_manual_fica_marcada(lote):
    v = hoje + dt.timedelta(days=2)
    r = transf(lote, para="fresco", validade_manual=v, justificativa="avaliado")
    assert r["validade_manual"] is True
    m = Movimento.objects.get(lote=lote, estado="fresco")
    assert (m.validade, m.validade_manual, m.tipo) == (v, True, "transferencia_estado")


def test_com_criterio_ignora_manual(lote):
    assert calcular_validade(lote.item, "cru", "congelado", hoje=hoje, manual=hoje, justificativa="") == (hoje + dt.timedelta(days=60), False)


def test_porcao_vencida_nao_transfere(lote):
    Movimento.objects.filter(lote=lote).update(validade=hoje - dt.timedelta(days=1))
    with pytest.raises(RegraViolada, match="só aceita descarte"):
        transf(lote)
