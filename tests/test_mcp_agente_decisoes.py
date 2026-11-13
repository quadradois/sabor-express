import json
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone
from mcp.shared.memory import create_connected_server_and_client_session

from agente.ferramentas import REGISTRO, criar_servidor
from agente.models import Proposta
from backup.nucleo import FORMATO, PREFIXO
from cadastros.models import Item
from cadastros.servicos import salvar_fornecedor
from compras.servicos import registrar_compra
from decisoes.consultas import decisoes, detalhe_decisao
from decisoes.geradores import rodar_rotina
from decisoes.models import Decisao
from decisoes.servicos import criar_decisao
from estoque.models import ConsumoPendente, CriterioValidade, Movimento
from estoque.servicos import entrada_manual
from nucleo.models import RegistroOperacao
from nucleo.operacoes import RegraViolada
from producao.servicos import concluir_producao, iniciar_producao, usar_previsto_restantes

pytestmark = pytest.mark.django_db


def hoje():
    return timezone.localdate()


@async_to_sync
async def _sessao(acao):
    async with create_connected_server_and_client_session(criar_servidor()) as s:
        return await acao(s)


def chamar(ferramenta, **args):
    async def acao(s):
        return await s.call_tool(ferramenta, args)
    r = _sessao(acao)
    assert not r.isError, r.content
    return json.loads(r.content[0].text)


def ferramentas():
    async def acao(s):
        return (await s.list_tools()).tools
    return {t.name: t for t in _sessao(acao)}


def backup_feito(pasta, horas_atras=1):
    nome = f"{PREFIXO}{(datetime.now() - timedelta(hours=horas_atras)).strftime(FORMATO)}.tar.gz"
    (pasta / nome).write_bytes(b"x" * 2_000_000)


@pytest.fixture(autouse=True)
def pasta_backup(settings, tmp_path):
    """Nunca olha a pasta de backup real; por padrão, há um backup de uma hora atrás (em dia)."""
    settings.BACKUP_DIR = tmp_path
    backup_feito(tmp_path)
    return tmp_path


@pytest.fixture
def farinha(bolinha):
    return bolinha.ficha.proporcoes.get().preparacao.itens.get().item


def produzir_sem_estoque(bolinha):
    """10 bolinhas de 100 g sem farinha no estoque: 1 kg de farinha fica pendente de conciliar."""
    CriterioValidade.objects.get_or_create(produto=bolinha, forma="cru", estado="congelado", dias=30)
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono",
                         pendente_justificativa="nota não lançada")["producao_id"]
    usar_previsto_restantes(producao_id=p, autor="dono")
    concluir_producao(producao_id=p, quantidade_boa=10, perdas=0, estado="congelado", autor="dono")
    return p


@pytest.fixture
def conciliacao(bolinha, farinha):
    """Uma decisão de conciliar 1 kg de farinha com um lote de 10 kg (custo 5 reais)."""
    produzir_sem_estoque(bolinha)
    entrada_manual(item_id=farinha.id, quantidade=D("10"), unidade="kg", custo_total=D("50"), motivo="compra",
                   autor="dono")
    rodar_rotina()
    [d] = decisoes(tipo="decisao")
    return d


def aviso(texto="O freezer 2 está fazendo barulho.", origem="agente"):
    return criar_decisao(origem=origem, texto=texto, autor="dono")["decisao_id"]


# --- registro e alçada -----------------------------------------------------------

def test_alcada_das_ferramentas_de_decisoes():
    nivel = {f.nome: f.nivel for f in REGISTRO}
    leitura = {"ver_resumo_do_dia", "ver_decisoes", "ver_decisao", "ver_historico", "ver_backup"}
    assert {n: nivel[n] for n in leitura} == dict.fromkeys(leitura, 0)
    assert (nivel["dar_ciencia"], nivel["recusar_decisao"]) == (1, 1)
    assert nivel["aprovar_decisao"] == 2  # executa operação: repete e espera o sim
    t = ferramentas()
    assert {n for n in leitura if t[n].annotations.readOnlyHint} == leitura
    assert t["recusar_decisao"].inputSchema["required"] == ["decisao_id", "motivo"]


# --- vazio fala natural ----------------------------------------------------------

def test_caixa_vazia_e_dia_vazio_com_texto_natural():
    r = chamar("ver_decisoes")
    assert (r["total"], r["texto"]) == (0, "A caixa de decisões está vazia: nada esperando você.")
    assert chamar("ver_decisoes", tipo="aviso")["texto"] == "Nenhum aviso na caixa."
    assert chamar("ver_decisoes", origem="contas")["texto"] == \
        "Nada sobre conta a vencer e conta vencida na caixa."
    dia = chamar("ver_resumo_do_dia")
    assert dia["assuntos"] == []
    assert dia["texto"].startswith("Dia tranquilo: nada vencido nem para vencer")
    assert dia["texto"].endswith("A caixa de decisões está vazia.")
    assert chamar("ver_historico", periodo="ontem")["texto"] == "Ontem, nenhuma operação."


# --- leitura da caixa --------------------------------------------------------------

def test_caixa_fala_os_tres_mais_urgentes_com_o_numero(conciliacao):
    ids = [aviso(f"Aviso {i}.") for i in range(4)]
    vencida = aviso("Conta vencida: Atacadão, R$ 100,00.", origem="contas_vencidas")
    r = chamar("ver_decisoes")
    total = len(decisoes())
    assert r["total"] == total and r["decisoes"] == 1
    t = r["texto"]
    assert t.startswith(f"Na caixa, 1 decisão para aprovar e {total - 1} avisos.")
    # a decisão primeiro, depois o aviso de conta vencida (mais urgente que os do agente)
    assert t.index(f"Número {conciliacao['decisao_id']}, para aprovar: Consumo pendente de 1 kg") < \
        t.index(f"Número {vencida}, aviso: Conta vencida")
    assert t.endswith(f"E tem mais {total - 3}.") and f"Número {ids[-1]}" not in t
    assert [i["decisao_id"] for i in r["itens"]][:2] == [conciliacao["decisao_id"], vencida]
    so_avisos = chamar("ver_decisoes", tipo="aviso")
    assert so_avisos["decisoes"] == 0 and so_avisos["avisos"] == total - 1
    contas = chamar("ver_decisoes", origem="contas")
    assert [i["decisao_id"] for i in contas["itens"]] == [vencida]
    assert chamar("ver_decisoes", origem="conciliar")["itens"][0]["decisao_id"] == conciliacao["decisao_id"]
    errado = chamar("ver_decisoes", origem="dinossauro")
    assert "Não conheço o assunto" in errado["erro"] and "produto vencido" in errado["opcoes"]


def test_ver_decisao_em_detalhe(conciliacao):
    r = chamar("ver_decisao", decisao_id=conciliacao["decisao_id"])
    assert r["situacao"] == "pendente" and r["tipo"] == "decisao"
    assert r["texto"].startswith(f"Número {conciliacao['decisao_id']}, decisão para aprovar, consumo pendente:")
    assert r["texto"].endswith("Está na caixa desde hoje.")
    assert chamar("ver_decisao", decisao_id=999)["erro"] == "Não achei a decisão número 999."


# --- aprovar (nível 2) -------------------------------------------------------------

def test_aprovar_por_voz_so_grava_depois_do_sim_e_uma_vez(conciliacao):
    n = conciliacao["decisao_id"]
    r = chamar("aprovar_decisao", decisao_id=n)
    assert r["confirmar"].startswith(f"Aprovar o número {n}: Consumo pendente de 1 kg de Farinha de trigo")
    assert "custo de 5 reais" in r["confirmar"] and r["confirmar"].endswith("Confirma?")
    # nada gravado: a simulação não deixa rastro
    assert detalhe_decisao(n)["situacao"] == "pendente" and ConsumoPendente.objects.get().aberto
    assert not RegistroOperacao.objects.filter(nome__in=["aprovar_decisao", "conciliar_consumo"]).exists()
    feito = chamar("confirmar_proposta", proposta_id=r["proposta_id"])
    assert feito["dito"].startswith(f"Feito: Aprovar o número {n}")
    assert detalhe_decisao(n)["situacao"] == "aprovada" and not ConsumoPendente.objects.get().aberto
    # confirmar de novo e aprovar de novo não executam outra vez
    assert chamar("confirmar_proposta", proposta_id=r["proposta_id"])["resultado"] == feito["resultado"]
    de_novo = chamar("aprovar_decisao", decisao_id=n)
    assert de_novo["erro"] == f"O número {n} já está aprovado pelo agente; não faço de novo."
    assert Movimento.objects.filter(motivo__startswith="Conciliação").count() == 1
    assert RegistroOperacao.objects.filter(nome="conciliar_consumo", status="sucesso").count() == 1
    assert RegistroOperacao.objects.filter(nome="aprovar_decisao", status="sucesso").count() == 1
    salvo = Decisao.objects.get(id=n)
    assert (salvo.decidida_por, salvo.registro.canal) == ("agente-mcp", "agente")


def test_nao_ao_aprovar_nao_grava_nada(conciliacao):
    n = conciliacao["decisao_id"]
    r = chamar("aprovar_decisao", decisao_id=n)
    assert chamar("recusar_proposta", proposta_id=r["proposta_id"])["dito"].startswith("Certo, não gravei nada")
    assert detalhe_decisao(n)["situacao"] == "pendente" and ConsumoPendente.objects.get().aberto
    assert Proposta.objects.get().estado == "recusada"


def test_aprovar_quando_o_nucleo_recusa_continua_pendente(bolinha, farinha):
    produzir_sem_estoque(bolinha)
    entrada_manual(item_id=farinha.id, quantidade=D("1"), unidade="kg", custo_total=D("5"), motivo="compra",
                   autor="dono")
    rodar_rotina()
    [d] = decisoes(tipo="decisao")
    r = chamar("aprovar_decisao", decisao_id=d["decisao_id"])
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"]
    usar_previsto_restantes(producao_id=p, autor="dono")
    concluir_producao(producao_id=p, quantidade_boa=10, perdas=0, estado="congelado", autor="dono")  # usou o lote
    erro = chamar("confirmar_proposta", proposta_id=r["proposta_id"])
    assert "só tem" in erro["erro"]
    assert detalhe_decisao(d["decisao_id"])["situacao"] == "pendente"
    assert "Da última vez não deu para aprovar: O lote só tem" in chamar("ver_decisoes")["texto"]


def test_aviso_nao_se_aprova_nem_se_recusa():
    n = aviso()
    assert "é um aviso, não tem o que aprovar" in chamar("aprovar_decisao", decisao_id=n)["erro"]
    assert "aviso não se recusa" in chamar("recusar_decisao", decisao_id=n, motivo="não quero")["erro"]
    assert not Proposta.objects.exists() and detalhe_decisao(n)["situacao"] == "pendente"


# --- ciência e recusa (nível 1) ------------------------------------------------------

def test_dar_ciencia_grava_e_repete(conciliacao):
    n = aviso()
    r = chamar("dar_ciencia", decisao_id=n)
    assert r["dito"] == f"Ciente do número {n}: O freezer 2 está fazendo barulho. Saiu da caixa."
    assert chamar("dar_ciencia", decisao_id=n).get("repetida")  # o modelo repetiu a chamada
    assert RegistroOperacao.objects.filter(nome="aprovar_decisao", status="sucesso").count() == 1
    d = detalhe_decisao(n)
    assert (d["situacao"], d["decidida_por"]) == ("aprovada", "agente-mcp")
    assert "não é aviso" in chamar("dar_ciencia", decisao_id=conciliacao["decisao_id"])["erro"]
    assert detalhe_decisao(conciliacao["decisao_id"])["situacao"] == "pendente"


def test_recusar_exige_motivo_e_repete_o_que_entendeu(conciliacao):
    n = conciliacao["decisao_id"]
    sem = chamar("recusar_decisao", decisao_id=n, motivo="  ")
    assert sem["erro"].startswith("Para recusar, preciso do motivo")
    assert detalhe_decisao(n)["situacao"] == "pendente"
    r = chamar("recusar_decisao", decisao_id=n, motivo="vou lançar a nota amanhã")
    assert r["dito"].startswith(f"Recusei o número {n} (Consumo pendente de 1 kg")
    assert r["dito"].endswith("Motivo: vou lançar a nota amanhã.")
    d = detalhe_decisao(n)
    assert (d["situacao"], d["motivo"]) == ("recusada", "vou lançar a nota amanhã")
    assert ConsumoPendente.objects.get().aberto  # recusar não executa nada
    assert "já foi recusado pelo agente (vou lançar a nota amanhã)" in \
        chamar("aprovar_decisao", decisao_id=n)["erro"]
    assert chamar("ver_decisao", decisao_id=n)["texto"].endswith(
        "Recusada pelo agente hoje: vou lançar a nota amanhã.")


# --- resumo do dia -------------------------------------------------------------------

def test_resumo_fala_os_totais_e_os_tres_mais_urgentes(bolinha, farinha, pasta_backup):
    leite = Item.objects.create(nome="Leite", tipo="ingrediente", unidade_base="mL", controla_validade=True)
    entrada_manual(item_id=leite.id, quantidade=D("2"), unidade="L", custo_total=D("10"), motivo="compra",
                   validade=hoje() - timedelta(days=1), autor="dono")
    fornecedor = salvar_fornecedor(nome="Atacadão", autor="dono")["fornecedor_id"]
    registrar_compra(fornecedor_id=fornecedor, data_compra=hoje(), total=D("150"), condicao="a_prazo",
                     linhas=[{"item_id": farinha.id, "quantidade": D("10"), "unidade": "kg", "valor": D("150")}],
                     parcelas=[{"valor": D("100"), "vencimento": hoje() - timedelta(days=1)},
                               {"valor": D("50"), "vencimento": hoje() + timedelta(days=5)}], autor="dono")
    Item.objects.create(nome="Sal", tipo="ingrediente", unidade_base="g", controla_validade=False,
                        estoque_minimo=D("500"))
    iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono",
                     pendente_justificativa="farinha chega à tarde")
    rodar_rotina()
    r = chamar("ver_resumo_do_dia")
    t = r["texto"]
    assert t.startswith("Na caixa, ")
    assert "Atenção: 1 lote vencido em estoque, 10 reais em mercadoria: Leite. Vencido não pode ser usado." in t
    assert "1 conta vencida, somando 100 reais." in t
    chaves = [a["assunto"] for a in r["assuntos"]]
    assert chaves[:2] == ["vencidos", "contas_vencidas"] and "backup" not in chaves  # backup em dia: não fala
    assert len(chaves) > 3 and f"Tem mais {len(chaves) - 3} assunto" in t and t.count("Atenção") == 1
    assert "Hoje já foram feitas" in t
    assert r["totais"]["valor_contas_vencidas"] == 100.0

    for f in pasta_backup.iterdir():  # sem backup, o resumo avisa logo depois do vencido
        f.unlink()
    assert [a["assunto"] for a in chamar("ver_resumo_do_dia")["assuntos"]][:2] == ["vencidos", "backup"]


# --- histórico -------------------------------------------------------------------------

def test_historico_do_dia_curto_e_com_filtros():
    salvar_fornecedor(nome="Atacadão", autor="dono")
    for nome in ("Makro", "Assaí", "Roldão"):
        chamar("cadastrar_fornecedor", nome=nome)
    with pytest.raises(RegraViolada):  # recusado pelo núcleo: fica na trilha como erro
        salvar_fornecedor(nome="makro", autor="agente-mcp", canal="agente")
    rodar_rotina()  # operações da rotina ficam de fora por padrão
    r = chamar("ver_historico")
    assert r["total"] == 4 and r["por_tipo"] == {"Fornecedor salvo": 4}
    assert r["texto"].startswith("Hoje, 4 operações. As mais recentes: Fornecedor salvo às ")
    assert ", pelo agente." in r["texto"] and r["texto"].endswith("E mais 1.")
    assert chamar("ver_historico", autor="dono")["texto"].startswith("Hoje, 1 operação por dono. Fornecedor salvo")
    assert chamar("ver_historico", canal="voz")["total"] == 3
    assert chamar("ver_historico", canal="sistema")["total"] == RegistroOperacao.objects.filter(
        canal="sistema").count() > 0
    assert chamar("ver_historico", operacao="fornecedor")["total"] == 4
    assert chamar("ver_historico", operacao="pagamento")["texto"] == "Hoje, nenhuma operação de pagamento."
    erros = chamar("ver_historico", so_erros=True)
    assert erros["total"] == 1 and erros["texto"].startswith("Hoje, 1 tentativa recusada. Fornecedor salvo")
    assert "(Já existe o fornecedor 'Makro')." in erros["texto"]
    assert chamar("ver_historico", periodo="semana")["total"] == 4
    assert "periodo" in chamar("ver_historico", periodo="anteontem")["erro"]
    assert "Não conheço a operação" in chamar("ver_historico", operacao="xyzzy")["erro"]


# --- backup ----------------------------------------------------------------------------

def test_situacao_do_backup(pasta_backup):
    r = chamar("ver_backup")
    assert (r["existe"], r["atrasado"], r["quantidade"]) == (True, False, 1)
    assert r["texto"].startswith("Backup em dia: o último backup foi ") and "Há 1 backup guardado." in r["texto"]
    assert r["tamanho_mb"] == 2.0 and str(pasta_backup) not in json.dumps(r)
    for f in pasta_backup.iterdir():
        f.unlink()
    backup_feito(pasta_backup, horas_atras=24 * 3)
    atrasado = chamar("ver_backup")
    assert atrasado["atrasado"] and atrasado["texto"].startswith("Atenção: o backup está atrasado")
    assert "há 3 dias" in atrasado["texto"]
    for f in pasta_backup.iterdir():
        f.unlink()
    nenhum = chamar("ver_backup")
    assert not nenhum["existe"] and nenhum["texto"].startswith("Atenção: não encontrei nenhum backup")
