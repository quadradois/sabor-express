import datetime as dt
import html as _html
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from decisoes.geradores import rodar_rotina
from decisoes.models import Decisao
from decisoes.servicos import criar_decisao
from estoque.models import ConsumoPendente, Movimento
from estoque.servicos import entrada_manual
from nucleo.models import RegistroOperacao
from producao.servicos import concluir_producao, iniciar_producao, usar_previsto_restantes

pytestmark = pytest.mark.django_db


def texto(r):
    return _html.unescape(r.content.decode())


@pytest.fixture
def conciliacao(bolinha):
    """Uma decisão com operação (conciliar consumo) pronta na caixa."""
    farinha = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono",
                         pendente_justificativa="nota atrasada")["producao_id"]
    usar_previsto_restantes(producao_id=p, autor="dono")
    concluir_producao(producao_id=p, quantidade_boa=9, perdas=1, perda_motivo="rasgou", estado="resfriado",
                      validade_manual=timezone.localdate(), justificativa="t", autor="dono")
    entrada_manual(item_id=farinha.id, quantidade=D("10"), unidade="kg", custo_total=D("50"), motivo="compra",
                   autor="dono")
    rodar_rotina()
    return Decisao.objects.get(origem="consumo_pendente", operacao="conciliar_consumo")


@pytest.fixture
def aviso():
    r = criar_decisao(origem="agente", texto="Aviso de teste sobre a farinha", assunto="teste:1", autor="dono")
    return Decisao.objects.get(id=r["decisao_id"])


def test_telas_abrem(client, dono, conciliacao):
    for nome in ("inicio", "caixa", "historico"):
        assert client.get(reverse(nome)).status_code == 200
    for filtro in ("pendente", "decididas", "aprovada", "recusada", "expirada", "sem_efeito", "invalido"):
        assert client.get(reverse("caixa"), {"situacao": filtro}).status_code == 200


def test_telas_exigem_login(client):
    for nome in ("inicio", "caixa", "historico"):
        assert client.get(reverse(nome)).status_code == 302


def test_caixa_mostra_decisao_com_numeros_e_links(client, dono, conciliacao):
    t = texto(client.get(reverse("caixa")))
    assert conciliacao.texto in t and "Aprovar" in t and "Recusar" in t
    assert reverse("consumos") in t


def test_aprovar_pela_tela_grava_uma_vez_mesmo_reenviando(client, dono, conciliacao):
    dados = {"decisao": conciliacao.id, "acao": "aprovar", "chave": "k1"}
    t = texto(client.post(reverse("caixa"), dados, follow=True))
    assert "Decisão aprovada" in t
    # reenvio do mesmo formulário (mesma chave) e de outro envio (outra chave): nunca executa de novo
    texto(client.post(reverse("caixa"), dados, follow=True))
    texto(client.post(reverse("caixa"), dados | {"chave": "k2"}, follow=True))
    assert RegistroOperacao.objects.filter(nome="conciliar_consumo", status="sucesso").count() == 1
    assert Movimento.objects.filter(motivo__startswith="Conciliação").count() == 1
    conciliacao.refresh_from_db()
    assert conciliacao.situacao == "aprovada" and conciliacao.decidida_por == "dono"
    assert not ConsumoPendente.objects.get().aberto
    assert conciliacao.texto not in texto(client.get(reverse("caixa")))
    dec = texto(client.get(reverse("caixa"), {"situacao": "decididas"}))
    assert conciliacao.texto in dec and "Aprovada" in dec and "por dono" in dec


def test_recusar_sem_motivo_mostra_erro_e_nao_decide(client, dono, conciliacao):
    t = texto(client.post(reverse("caixa"), {"decisao": conciliacao.id, "acao": "recusar", "motivo": " ", "chave": "k1"},
                          follow=True))
    assert "motivo" in t.lower() and conciliacao.texto in t
    conciliacao.refresh_from_db()
    assert conciliacao.situacao == "pendente"


def test_recusar_com_motivo_e_idempotente(client, dono, conciliacao):
    dados = {"decisao": conciliacao.id, "acao": "recusar", "motivo": "Não quero agora", "chave": "k1"}
    assert "Decisão recusada" in texto(client.post(reverse("caixa"), dados, follow=True))
    texto(client.post(reverse("caixa"), dados, follow=True))  # reenvio
    conciliacao.refresh_from_db()
    assert conciliacao.situacao == "recusada" and conciliacao.motivo == "Não quero agora"
    assert RegistroOperacao.objects.filter(nome="recusar_decisao", status="sucesso").count() == 1
    assert not Movimento.objects.filter(motivo__startswith="Conciliação").exists()
    rec = texto(client.get(reverse("caixa"), {"situacao": "recusada"}))
    assert "Não quero agora" in rec and "por dono" in rec


def test_ciencia_tira_o_aviso_da_lista(client, dono, aviso):
    t = texto(client.get(reverse("caixa")))
    assert aviso.texto in t and "Dar ciência" in t
    assert "Anotado" in texto(client.post(reverse("caixa"), {"decisao": aviso.id, "acao": "aprovar", "chave": "c1"},
                                          follow=True))
    aviso.refresh_from_db()
    assert aviso.situacao == "aprovada"
    assert aviso.texto not in texto(client.get(reverse("caixa")))


def test_aviso_nao_se_recusa(client, dono, aviso):
    t = texto(client.post(reverse("caixa"), {"decisao": aviso.id, "acao": "recusar", "motivo": "x", "chave": "c1"},
                          follow=True))
    assert "Aviso não se recusa" in t
    aviso.refresh_from_db()
    assert aviso.situacao == "pendente"


def test_erro_do_nucleo_aparece_e_decisao_continua_pendente(client, dono, conciliacao):
    # o lote deixa de cobrir antes da aprovação: o núcleo recusa
    Movimento.objects.filter(lote_id=conciliacao.parametros["lote_id"]).delete()
    t = texto(client.post(reverse("caixa"), {"decisao": conciliacao.id, "acao": "aprovar", "chave": "k1"}, follow=True))
    assert "class=\"erro\"" in _html.unescape(client.get(reverse("caixa")).content.decode()) or "só tem" in t or "saldo" in t
    conciliacao.refresh_from_db()
    assert conciliacao.situacao == "pendente"
    assert "Não deu para aprovar" in texto(client.get(reverse("caixa")))


def test_post_sem_chave_ou_decisao_invalida(client, dono):
    assert "sem chave" in texto(client.post(reverse("caixa"), {"decisao": 1, "acao": "aprovar"}, follow=True))
    assert "não encontrada" in texto(client.post(reverse("caixa"), {"decisao": 999, "acao": "aprovar", "chave": "z"},
                                                 follow=True)).lower()


def test_hoje_mostra_resumo_e_caixa(client, dono, conciliacao):
    t = texto(client.get(reverse("inicio")))
    for esperado in ("Caixa de decisões", "1 decisão(ões)", "Validade", "O que falta", "O que pagar", "O que chega",
                     "Produção", "consumo(s) pendente(s)", "aviso(s) de ajuste", "operação(ões) feita(s) hoje"):
        assert esperado in t
    assert reverse("caixa") in t and reverse("historico") in t


def test_hoje_alerta_de_backup(client, dono, settings):
    assert "Não há nenhum backup" in texto(client.get(reverse("inicio")))
    pasta = settings.BACKUP_DIR
    pasta.mkdir(parents=True)
    velho = dt.datetime.now() - dt.timedelta(days=3)
    (pasta / f"sabor-express-{velho:%Y%m%d-%H%M%S}.tar.gz").write_bytes(b"x")
    assert "Está velho" in texto(client.get(reverse("inicio")))
    novo = dt.datetime.now() - dt.timedelta(hours=1)
    (pasta / f"sabor-express-{novo:%Y%m%d-%H%M%S}.tar.gz").write_bytes(b"x")
    t = texto(client.get(reverse("inicio")))
    assert "Backup em dia" in t and "Está velho" not in t


def test_hoje_mostra_valor_vencido(client, dono, bolinha):
    farinha = bolinha.ficha.proporcoes.get().preparacao.itens.get().item
    farinha.controla_validade = True
    farinha.save()
    entrada_manual(item_id=farinha.id, quantidade=D("2"), unidade="kg", custo_total=D("10"), motivo="compra",
                   validade=timezone.localdate() - dt.timedelta(days=2), autor="dono")
    t = texto(client.get(reverse("inicio")))
    assert "1 lote(s) vencido(s): R$ 10,00" in t


# ---------- histórico ----------

@pytest.fixture
def trilha(db):
    antigo = RegistroOperacao.objects.create(nome="salvar_fornecedor", autor="maria", canal="agente", status="sucesso",
                                             parametros={"nome": "Atacadão"}, resultado={})
    RegistroOperacao.objects.filter(id=antigo.id).update(criado_em=timezone.now() - dt.timedelta(days=5))
    RegistroOperacao.objects.create(nome="registrar_compra", autor="dono", canal="web", status="sucesso",
                                    parametros={"total": "10"}, resultado={})
    RegistroOperacao.objects.create(nome="registrar_pagamento", autor="dono", canal="web", status="erro",
                                    parametros={}, resultado=None, erro="Valor maior que o saldo")


def test_historico_padrao_e_hoje_com_rotulos(client, dono, trilha):
    t = texto(client.get(reverse("historico")))
    assert "<strong>Compra lançada</strong>" in t and "<strong>Pagamento anotado</strong>" in t and "<strong>Fornecedor salvo</strong>" not in t
    assert "Valor maior que o saldo" in t and "recusada" in t


def test_historico_filtros(client, dono, trilha):
    url = reverse("historico")
    amplo = {"de": "2000-01-01", "ate": "2100-01-01"}
    t = texto(client.get(url, amplo))
    assert "<strong>Fornecedor salvo</strong>" in t and "<strong>Compra lançada</strong>" in t
    t = texto(client.get(url, amplo | {"autor": "maria"}))
    assert "<strong>Fornecedor salvo</strong>" in t and "<strong>Compra lançada</strong>" not in t
    t = texto(client.get(url, amplo | {"canal": "web"}))
    assert "<strong>Compra lançada</strong>" in t and "<strong>Fornecedor salvo</strong>" not in t
    t = texto(client.get(url, amplo | {"nome": "registrar_compra"}))
    assert "<strong>Compra lançada</strong>" in t and "<strong>Pagamento anotado</strong>" not in t
    t = texto(client.get(url, amplo | {"status": "erro"}))
    assert "<strong>Pagamento anotado</strong>" in t and "<strong>Compra lançada</strong>" not in t
    dia = (timezone.localdate() - dt.timedelta(days=5)).isoformat()
    t = texto(client.get(url, {"de": dia, "ate": dia}))
    assert "<strong>Fornecedor salvo</strong>" in t and "<strong>Compra lançada</strong>" not in t


def test_historico_data_invalida_nao_quebra(client, dono, trilha):
    r = client.get(reverse("historico"), {"de": "ontem"})
    assert r.status_code == 200 and "Data inválida" in texto(r)


def test_historico_pagina(client, dono):
    for i in range(35):
        RegistroOperacao.objects.create(nome="registrar_compra", autor="dono", canal="web", status="sucesso",
                                        parametros={}, resultado={})
    t = texto(client.get(reverse("historico")))
    assert "Página 1 de 2" in t and "35 operação(ões)" in t
    t2 = texto(client.get(reverse("historico"), {"pagina": 2}))
    assert "Página 2 de 2" in t2 and "Anterior" in t2
