from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.utils import timezone

from estoque.models import CriterioValidade, Lote, Movimento
from estoque.servicos import entrada_manual, saldo_lote
from nucleo.operacoes import RegraViolada
from producao.models import Producao
from producao.servicos import concluir_producao, iniciar_producao, origem, registrar_peso, usar_previsto_restantes

pytestmark = pytest.mark.django_db
hoje = timezone.localdate()


def _producao(bolinha, forma):
    f = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    CriterioValidade.objects.create(produto=bolinha, forma=forma, estado="resfriado", dias=3)
    for q, c, d in (("600", "3", 1), ("1000", "8", 6)):
        entrada_manual(item_id=f.id, quantidade=D(q), unidade="g", custo_total=D(c), motivo="compra",
                       validade=hoje + timedelta(days=d), autor="dono")
    a, b = Lote.objects.filter(item=f).order_by("id")
    p = Producao.objects.get(id=iniciar_producao(produto_id=bolinha.id, unidades=10, forma=forma, autor="dono")["producao_id"])
    return p, a, b


@pytest.fixture
def producao(bolinha):
    return _producao(bolinha, "cru")


@pytest.fixture
def producao_pesada(producao):
    usar_previsto_restantes(producao_id=producao[0].id, autor="dono")
    return producao


@pytest.fixture
def producao_frita_pesada(bolinha):
    p, a, b = _producao(bolinha, "frito")
    usar_previsto_restantes(producao_id=p.id, autor="dono")
    return p, a, b


def concluir(p, boa=9, perdas=1, **kw):
    kw.setdefault("perda_motivo", "rasgou" if perdas else "")
    return concluir_producao(producao_id=p.id, quantidade_boa=boa, perdas=perdas, estado="resfriado", autor="dono", **kw)


def test_conclui_cru_custo_fefo(producao_pesada):
    p, lote_a, lote_b = producao_pesada
    r = concluir(p)
    assert (D(r["custo_total"]), D(r["custo_unitario"])) == (D("6.20"), D("0.6889"))
    assert (saldo_lote(lote_a), saldo_lote(lote_b)) == (D("0"), D("600"))
    lote = Lote.objects.get(id=r["lote_id"])
    assert (saldo_lote(lote, "resfriado"), lote.validade, lote.forma) == (D("9"), hoje + timedelta(days=3), "cru")
    assert (lote.custo_unitario, lote.codigo) == (D("0.6889"), f"{hoje:%y%m%d}-{p.id}")
    assert origem(lote) == [(lote_a, D("600")), (lote_b, D("400"))]
    p.refresh_from_db()
    assert (p.status, p.quantidade_boa, p.perdas, p.lote_id, p.custo_total) == ("concluida", 9, 1, lote.id, D("6.20"))
    assert p.encerrada_em is not None


def test_conclui_frito_soma_oleo_de_referencia(producao_frita_pesada):
    p, _, _ = producao_frita_pesada
    r = concluir(p)
    assert (D(r["custo_total"]), D(r["custo_unitario"])) == (D("6.70"), D("0.7444"))
    assert Lote.objects.get(id=r["lote_id"]).forma == "frito"


def test_pesou_mais_que_o_estoque_recusa_e_continua(producao_pesada):
    p, _, _ = producao_pesada
    l = p.linhas.get()
    registrar_peso(linha_id=l.id, usado=D("1700"), autor="dono")
    n = Movimento.objects.count()
    with pytest.raises(RegraViolada, match="Falta 100 g de 'Farinha de trigo' no estoque."):
        concluir(p)
    p.refresh_from_db()
    l.refresh_from_db()
    assert (p.status, Movimento.objects.count(), l.usado) == ("andamento", n, D("1700"))


def test_dupla_conclusao_um_lote(producao_pesada):
    p, _, _ = producao_pesada
    r = concluir(p, chave="k1")
    assert concluir(p, chave="k1") == r
    assert Lote.objects.filter(item=p.produto).count() == 1
    with pytest.raises(RegraViolada, match="Esta produção já foi encerrada."):
        concluir(p, chave="k2")


def test_perda_total_exige_confirmacao_e_nao_cria_lote(producao_pesada):
    p, _, _ = producao_pesada
    with pytest.raises(RegraViolada, match="Nenhuma unidade boa: confirme a perda total."):
        concluir(p, boa=0, perdas=10)
    r = concluir(p, boa=0, perdas=10, confirmar_perda_total=True)
    assert (r["lote_id"], D(r["custo_total"]), r["custo_unitario"]) == (None, D("6.20"), None)
    assert not Lote.objects.filter(item=p.produto).exists()
    p.refresh_from_db()
    assert (p.status, p.lote) == ("concluida", None)


def test_perdas_sem_motivo_recusa(producao_pesada):
    p, _, _ = producao_pesada
    with pytest.raises(RegraViolada, match="Informe o motivo das perdas."):
        concluir(p, perda_motivo="")


def test_sem_pesar_ou_sem_conservacao_recusa(producao):
    p, _, _ = producao
    with pytest.raises(RegraViolada, match="Pese ou marque 'usei o previsto' em: Farinha de trigo."):
        concluir(p)
    usar_previsto_restantes(producao_id=p.id, autor="dono")
    with pytest.raises(RegraViolada, match="Escolha a conservação."):
        concluir_producao(producao_id=p.id, quantidade_boa=10, estado="", autor="dono")


def test_lote_fixado_no_peso_e_respeitado(producao):
    p, lote_a, lote_b = producao
    registrar_peso(linha_id=p.linhas.get().id, usado=None, lote_id=lote_b.id, autor="dono")
    r = concluir(p)
    assert (saldo_lote(lote_a), saldo_lote(lote_b)) == (D("600"), D("0"))
    assert D(r["custo_total"]) == D("8.00")
    assert origem(Lote.objects.get(id=r["lote_id"])) == [(lote_b, D("1000"))]
