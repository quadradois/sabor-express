from decimal import Decimal as D
import datetime as dt
import pytest
from cadastros.models import Item
from estoque.models import Lote, Movimento
from estoque.servicos import entrada_manual, saldo
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db

@pytest.fixture
def requeijao(): return Item.objects.create(nome="Requeijão", tipo="ingrediente", unidade_base="g")

def test_entrada_cria_lote_e_movimento_em_unidade_base(requeijao):
    r = entrada_manual(item_id=requeijao.id, quantidade=D("1.5"), unidade="kg", custo_total=D("45.00"),
                       motivo="estoque inicial", lote_codigo="REQ-1012", validade=dt.date(2026, 10, 24), autor="dono")
    lote = Lote.objects.get(id=r["lote_id"])
    assert lote.custo_unitario == D("0.0300")
    assert saldo(requeijao) == D("1500")
    assert Movimento.objects.get().operacao.nome == "entrada_manual"

def test_sem_codigo_marca_sem_lote(requeijao):
    r = entrada_manual(item_id=requeijao.id, quantidade=D("200"), unidade="g", custo_total=D("6"),
                       motivo="estoque inicial", validade=dt.date(2026, 10, 30), autor="dono")
    assert Lote.objects.get(id=r["lote_id"]).sem_lote is True

def test_motivo_obrigatorio(requeijao):
    with pytest.raises(RegraViolada, match="Informe o motivo"):
        entrada_manual(item_id=requeijao.id, quantidade=D("1"), unidade="g", custo_total=D("1"), motivo=" ", autor="dono")

def test_quantidade_deve_ser_positiva(requeijao):
    with pytest.raises(RegraViolada, match="maior que zero"):
        entrada_manual(item_id=requeijao.id, quantidade=D("0"), unidade="g", custo_total=D("1"), motivo="x", autor="dono")

def test_validade_obrigatoria_quando_item_controla(requeijao):
    with pytest.raises(RegraViolada, match="Informe a validade"):
        entrada_manual(item_id=requeijao.id, quantidade=D("1"), unidade="g", custo_total=D("1"), motivo="x", autor="dono")

def test_saldo_sem_movimentos_e_zero(requeijao):
    assert saldo(requeijao) == D("0")

def test_movimento_guarda_como_foi_informado(requeijao):
    entrada_manual(item_id=requeijao.id, quantidade=D("1.5"), unidade="Kg", custo_total=D("45"),
                   motivo="x", validade=dt.date(2026, 10, 24), autor="dono")
    m = Movimento.objects.get()
    assert (m.quantidade_informada, m.unidade_informada, m.fator, m.quantidade) == (D("1.5"), "kg", D("1000"), D("1500"))

def test_recusa_fica_na_trilha(requeijao):
    from nucleo.models import RegistroOperacao
    with pytest.raises(RegraViolada):
        entrada_manual(item_id=requeijao.id, quantidade=D("1"), unidade="g", custo_total=D("1"), motivo="", autor="dono")
    reg = RegistroOperacao.objects.get()
    assert reg.status == "erro" and reg.parametros["quantidade"] == "1"
