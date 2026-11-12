from decimal import Decimal as D

import pytest
from fichas.models import Etapa
from fichas.versoes import salvar_versao
from estoque.servicos import entrada_manual
from nucleo.operacoes import RegraViolada
from producao.models import Producao
from producao.servicos import iniciar_producao

pytestmark = pytest.mark.django_db


@pytest.fixture
def farinha_em_estoque(bolinha):
    f = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    entrada_manual(item_id=f.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra", autor="dono")


def _ini(b, forma="cru"):
    return iniciar_producao(produto_id=b.id, unidades=10, forma=forma, autor="dono")["producao_id"]


def test_iniciar_copia_linhas_e_etapas(bolinha, farinha_em_estoque):
    p = Producao.objects.get(id=_ini(bolinha))
    assert [(l.bloco, l.item.nome, l.previsto, l.usado) for l in p.linhas.all()] == [("Massa simples", "Farinha de trigo", D("1000"), None)]
    assert [e["instrucao"] for e in p.etapas] == ["Sove a massa", "Modele as bolinhas"]
    assert (p.status, p.etapa_atual, p.versao.numero, p.fechamento) == ("andamento", 0, 1, 3)


def test_frito_acrescenta_fritura_por_ultimo(bolinha, farinha_em_estoque):
    p = Producao.objects.get(id=_ini(bolinha, "frito"))
    assert p.etapas[-1]["instrucao"] == "Frite as 10 unidades."


def test_iniciar_com_falta_recusa(bolinha):
    with pytest.raises(RegraViolada, match="Falta 1 kg de 'Farinha de trigo'. Dê entrada no estoque antes de começar."):
        _ini(bolinha)
    assert not Producao.objects.exists()


def test_frito_sem_referencia_de_oleo_recusa(bolinha, farinha_em_estoque):
    bolinha.oleo_ref_un = None
    bolinha.save()
    with pytest.raises(RegraViolada, match="Cadastre a referência de óleo"):
        _ini(bolinha, "frito")


def test_produto_inativo_e_forma_invalida_recusam(bolinha, farinha_em_estoque):
    with pytest.raises(RegraViolada, match="Forma inválida"):
        _ini(bolinha, "assado")
    bolinha.ativo = False
    bolinha.save()
    with pytest.raises(RegraViolada, match="inativo"):
        _ini(bolinha)


def test_editar_ficha_nao_muda_producao_em_andamento(bolinha, farinha_em_estoque):
    p = Producao.objects.get(id=_ini(bolinha))
    antes = ([(l.item_id, l.previsto) for l in p.linhas.all()], p.etapas, p.versao.numero)
    massa = bolinha.ficha.proporcoes.get().preparacao
    c = massa.itens.get()
    c.quantidade = D("500")
    c.save()
    Etapa.objects.create(ficha=massa, ordem=2, instrucao="Descanse")
    salvar_versao(bolinha.ficha)
    p = Producao.objects.get(id=p.id)
    assert ([(l.item_id, l.previsto) for l in p.linhas.all()], p.etapas, p.versao.numero) == antes
