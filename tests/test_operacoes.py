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

def test_corrida_mesma_chave_devolve_resultado_gravado(monkeypatch):
    import nucleo.operacoes as ops
    RegistroOperacao.objects.create(nome="teste", chave="k-race", canal="web", autor="dono",
                                    status="sucesso", resultado={"n": 7})
    real = ops._sucesso
    chamadas = []
    # a 1a consulta "perde" a corrida: não vê a linha que já existe
    monkeypatch.setattr(ops, "_sucesso", lambda c: None if not chamadas.append(1) and len(chamadas) == 1 else real(c))
    r = executar("teste", lambda op: {"n": 99}, autor="dono", chave="k-race")
    assert r == {"n": 7}
    assert RegistroOperacao.objects.count() == 1

def test_retry_apos_falha_mantem_erro_e_sucesso():
    def falha(op): raise RegraViolada("x")
    with pytest.raises(RegraViolada):
        executar("teste", falha, autor="dono", chave="k3")
    executar("teste", lambda op: {"ok": 1}, autor="dono", chave="k3")
    erro = RegistroOperacao.objects.get(status="erro")
    assert erro.chave is None and "k3" in erro.erro
    assert RegistroOperacao.objects.get(chave="k3").status == "sucesso"

def test_chave_vazia_repetida_nao_levanta():
    executar("teste", lambda op: {"a": 1}, autor="dono", chave="")
    executar("teste", lambda op: {"a": 1}, autor="dono", chave="")
    assert RegistroOperacao.objects.count() == 2
