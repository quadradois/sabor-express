from decimal import Decimal as D
import datetime as dt
import pytest
from django.utils import timezone
from cadastros.models import Item
from estoque.models import Lote, Movimento
from estoque.servicos import alocar_fefo, entrada_manual, saldo_lote, validade_porcao
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db
hoje = timezone.localdate()

@pytest.fixture
def frango(): return Item.objects.create(nome="Frango", tipo="ingrediente", unidade_base="g", controla_validade=False)

def lote(item, qtd, dias=None):
    v = hoje + dt.timedelta(days=dias) if dias is not None else None
    return Lote.objects.get(id=entrada_manual(item_id=item.id, quantidade=D(qtd), unidade="g", custo_total=D("10"),
                                              motivo="x", validade=v, autor="dono")["lote_id"])

def test_fefo_menor_validade_primeiro(frango):
    a, b = lote(frango, "500", 5), lote(frango, "500", 2)
    assert alocar_fefo(frango, D("700"), hoje=hoje) == [(b, D("500")), (a, D("200"))]

def test_fefo_sem_validade_entrada_mais_antiga(frango):
    a, b = lote(frango, "500"), lote(frango, "500")
    assert alocar_fefo(frango, D("600"), hoje=hoje) == [(a, D("500")), (b, D("100"))]

def test_fefo_pula_lote_vencido(frango):
    a = lote(frango, "500", 5)
    lote(frango, "1000", -1)
    assert alocar_fefo(frango, D("300"), hoje=hoje) == [(a, D("300"))]

def test_fefo_falta_conta_so_lotes_validos(frango):
    lote(frango, "500", 5)
    lote(frango, "1000", -1)
    with pytest.raises(RegraViolada, match=r"Falta 500 g de 'Frango' no estoque\."):
        alocar_fefo(frango, D("1000"), hoje=hoje)

def mov(l, q, estado, validade=None):
    return Movimento.objects.create(tipo="t", item=l.item, lote=l, quantidade=D(q), quantidade_informada=D(q),
                                    unidade_informada="g", fator=D("1"), motivo="x", estado=estado, validade=validade)

def test_saldo_lote_por_estado(frango):
    l = lote(frango, "10", 5)
    mov(l, "10", "resfriado"); mov(l, "-4", "resfriado"); mov(l, "4", "congelado")
    assert (saldo_lote(l, "resfriado"), saldo_lote(l, "congelado"), saldo_lote(l)) == (D("6"), D("4"), D("10"))

def test_validade_porcao_menor_entrada_ou_do_lote(frango):
    l = lote(frango, "10", 5)
    assert validade_porcao(l, "congelado") == l.validade
    mov(l, "3", "congelado", hoje + dt.timedelta(days=90)); mov(l, "3", "congelado", hoje + dt.timedelta(days=60))
    mov(l, "-1", "congelado", hoje + dt.timedelta(days=1))
    assert validade_porcao(l, "congelado") == hoje + dt.timedelta(days=60)
