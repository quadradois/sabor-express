import pytest
from nucleo.operacoes import executar, RegraViolada
from nucleo.models import RegistroOperacao

pytestmark = pytest.mark.django_db

def test_sucesso_registra_auditoria():
    r = executar("teste", lambda op: {"ok": 1}, autor="dono", canal="web")
    assert r == {"ok": 1}
    reg = RegistroOperacao.objects.get()
    assert (reg.nome, reg.status, reg.canal, reg.autor, reg.resultado) == ("teste", "sucesso", "web", "dono", {"ok": 1})

def test_repeticao_com_mesma_chave_nao_reexecuta():
    chamadas = []
    f = lambda op: chamadas.append(1) or {"n": len(chamadas)}
    a = executar("teste", f, autor="dono", chave="k1")
    b = executar("teste", f, autor="dono", chave="k1")
    assert a == b == {"n": 1}
    assert len(chamadas) == 1
    assert RegistroOperacao.objects.count() == 1

def test_erro_desfaz_gravacao_parcial_e_registra_erro():
    def f(op):
        RegistroOperacao.objects.create(nome="lixo", canal="web", autor="x", status="sucesso")
        raise RegraViolada("saldo insuficiente")
    with pytest.raises(RegraViolada, match="saldo insuficiente"):
        executar("teste", f, autor="dono", chave="k2")
    assert not RegistroOperacao.objects.filter(nome="lixo").exists()
    reg = RegistroOperacao.objects.get(nome="teste")
    assert reg.status == "erro" and "saldo insuficiente" in reg.erro

def test_chave_que_falhou_pode_ser_tentada_de_novo():
    def falha(op): raise RegraViolada("x")
    with pytest.raises(RegraViolada):
        executar("teste", falha, autor="dono", chave="k3")
    assert executar("teste", lambda op: {"ok": 1}, autor="dono", chave="k3") == {"ok": 1}
