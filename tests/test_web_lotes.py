"""Plano 9, fase 2a: telas de lotes na operação — separação no balcão e na entrega, lote indicado ("peguei de
outro lote"), data da venda, motivo do vencido, conferência do vencido, contagem, destino da perda, "Venda
primeiro", etiqueta com o dia e histórico com o motivo. As views só chamam o núcleo; aqui se confere o que a
tela mostra e o que ela grava."""
import datetime as dt
import html as _html
import re
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Item
from cadastros.servicos import salvar_cliente
from decisoes.geradores import rodar_rotina
from decisoes.models import Decisao
from estoque.lotes import nome_lote
from estoque.models import CriterioValidade, Lote, Movimento
from estoque.servicos import saldo_lote
from vendas.models import LinhaVenda, Venda
from vendas.servicos import criar_encomenda, registrar_venda, salvar_apresentacao

pytestmark = pytest.mark.django_db
HOJE = timezone.localdate()


def dia(n):
    return HOJE + dt.timedelta(days=n)


def texto(r):
    return _html.unescape(r.content.decode())


def limpo(r):
    return " ".join(re.sub(r"<[^>]+>", " ", texto(r)).split())


def visto(r):
    return re.search(r'name="visto" value="(\w+)"', texto(r)).group(1)


def feito_em(l, d):
    Lote.objects.filter(id=l.id).update(criado_em=timezone.make_aware(dt.datetime.combine(d, dt.time(10))))
    l.refresh_from_db()
    return l


def lote(produto, n, *, validade, feito=None, forma="cru", estado="congelado", custo="0.60", codigo=""):
    l = Lote.objects.create(item=produto, codigo=codigo, forma=forma, validade=validade, custo_unitario=D(custo))
    Movimento.objects.create(tipo="entrada_producao", item=produto, lote=l, quantidade=n, quantidade_informada=n,
                             unidade_informada="un", fator=1, motivo="teste", estado=estado, validade=validade)
    return feito_em(l, feito) if feito else l


def vence(l, validade):
    """Muda a validade do lote e da entrada dele (o saldo muda de 'válido' para 'vencido' sem mexer no resto)."""
    Lote.objects.filter(id=l.id).update(validade=validade)
    Movimento.objects.filter(lote=l).update(validade=validade)


@pytest.fixture
def coxinha():
    return Item.objects.create(nome="Coxinha 150 g", tipo="produto", unidade_base="un", oleo_ref_un=D("0.05"))


@pytest.fixture
def unidade(coxinha):
    return salvar_apresentacao(produto_id=coxinha.id, nome="unidade", forma="cru", estado="congelado", unidades=1,
                               preco_varejo=D("5"), autor="dono")["apresentacao_id"]


@pytest.fixture
def dois(coxinha):
    """O lote velho (18 un, vence amanhã) e o novo (30 un, vence em 10 dias)."""
    velho = lote(coxinha, 18, validade=dia(1), feito=dia(-3), codigo="A1")
    novo = lote(coxinha, 30, validade=dia(10), feito=dia(-1), codigo="B1")
    return velho, novo


def post_venda(unidade, qtd, **extra):
    return {"chave": f"k{qtd}{len(extra)}", "tabela": "varejo", "condicao": "a_vista", "forma_pagamento": "pix",
            f"qtd_{unidade}": str(qtd), **extra}


# ---------- 1. separação no balcão ----------

def test_vender_abre_com_data_de_hoje_e_botao_de_ver_de_onde_pegar(client, dono, unidade, dois):
    r = client.get(reverse("vender"))
    t = texto(r)
    assert f'name="data_venda" value="{HOJE:%Y-%m-%d}"' in t and f'max="{HOJE:%Y-%m-%d}"' in t
    assert 'value="separar"' in t and "Ver de onde pegar" in t and "Confirmar e registrar venda" not in t


def test_separar_mostra_de_qual_lote_pegar_sem_gravar(client, dono, coxinha, unidade, dois):
    velho, novo = dois
    r = client.post(reverse("vender"), post_venda(unidade, 30, acao="separar"))
    t = limpo(r)
    assert r.status_code == 200 and Venda.objects.count() == 0 and saldo_lote(velho, "congelado") == 18
    assert f"Pegar 18 un do {nome_lote(velho)} (código A1) · vence {dia(1):%d/%m}" in t
    assert "sobram" not in t.split("Pegar 18 un")[1].split("Pegar 12")[0] and "o lote zera" in t
    assert f"Pegar 12 un do {nome_lote(novo)} (código B1)" in t and "sobram 18 un nele" in t
    assert f"O {nome_lote(velho)} vence amanhã" in t
    assert "Confirmar e registrar venda" in t and "Peguei de outro lote" in t
    assert f"{nome_lote(velho)} (código A1, vence {dia(1):%d/%m}, 18 livres)" in t  # lista para "peguei de outro lote"


def test_confirmar_grava_baixa_da_separacao_e_mostra_os_avisos(client, dono, coxinha, unidade, dois):
    velho, novo = dois
    r = client.post(reverse("vender"), post_venda(unidade, 30, acao="confirmar"), follow=True)
    t = limpo(r)
    assert "Venda 1 registrada: R$ 150,00." in t
    assert f"O {nome_lote(velho)} vence amanhã" in t  # aviso do retorno da venda
    assert (saldo_lote(velho, "congelado"), saldo_lote(novo, "congelado")) == (0, 18)
    assert 'class="aviso"' in texto(r)


def test_enter_no_formulario_so_mostra_a_separacao(client, dono, unidade, dois):
    """Sem JavaScript: o primeiro botão do formulário é o de separar, então Enter nunca fecha a venda."""
    t = texto(client.post(reverse("vender"), post_venda(unidade, 3, acao="separar")))
    assert t.index('value="separar"') < t.index('value="confirmar"')


def test_mudou_os_lotes_depois_de_ver_a_separacao_mostra_de_novo_e_nao_grava(client, dono, coxinha, unidade, dois):
    velho, novo = dois
    d = post_venda(unidade, 10, acao="separar")
    r1 = client.post(reverse("vender"), d)
    d2 = {**d, "acao": "confirmar", "visto": visto(r1), f"lote_{unidade}_{novo.id}": "10"}  # mexeu depois de ver
    r2 = client.post(reverse("vender"), d2)
    assert Venda.objects.count() == 0 and "confira a separação de novo" in limpo(r2)
    assert "Ficaram 18 un" in limpo(r2)  # e a nova separação já mostra o que ficou para trás
    d3 = {**d2, "visto": visto(r2)}
    assert "registrada" in limpo(client.post(reverse("vender"), d3, follow=True))


def test_peguei_de_outro_lote_mostra_o_deixado_e_grava_com_lote_indicado(client, dono, coxinha, unidade, dois):
    velho, novo = dois
    d = post_venda(unidade, 10, acao="separar", **{f"lote_{unidade}_{novo.id}": "10"})
    r = client.post(reverse("vender"), d)
    t = limpo(r)
    assert f"Pegar 10 un do {nome_lote(novo)}" in t and t.count("Pegar ") == 1
    assert f"Ficaram 18 un do {nome_lote(velho)}, que vencem em {dia(1):%d/%m}: venda esse primeiro." in t
    assert 'value="10"' in texto(r)  # o que foi digitado continua nos campos
    r = client.post(reverse("vender"), {**d, "acao": "confirmar", "visto": visto(r), "chave": "outra"}, follow=True)
    assert "Ficaram 18 un" in limpo(r) and "registrada" in limpo(r)
    linha = LinhaVenda.objects.get()
    assert linha.lotes_indicados and linha.deixados[0]["lote_id"] == velho.id
    assert (saldo_lote(velho, "congelado"), saldo_lote(novo, "congelado")) == (18, 20)
    assert f"10 un do {nome_lote(novo)} (código B1)" in limpo(client.get(reverse("vendas")))  # nome junto do código


def test_separar_sem_estoque_nao_deixa_fechar_e_diz_o_que_falta(client, dono, unidade, dois):
    t = texto(client.post(reverse("vender"), post_venda(unidade, 60, acao="separar")))
    assert "Faltam 12 un" in t and "Não dá para fechar" in t and "Confirmar e registrar venda" not in t


def test_separar_sem_item_mostra_a_recusa(client, dono, unidade, dois):
    r = client.post(reverse("vender"), {"chave": "z", "acao": "separar"})
    assert "Informe ao menos um item." in texto(r) and Venda.objects.count() == 0


# ---------- 2. data da venda ----------

def test_data_passada_julga_a_validade_naquele_dia(client, dono, coxinha, unidade):
    v = lote(coxinha, 10, validade=dia(-1), feito=dia(-10), codigo="V1")
    d = post_venda(unidade, 4, data_venda=dia(-3).isoformat())
    t = limpo(client.post(reverse("vender"), {**d, "acao": "separar"}))
    assert f"Venda de {dia(-3):%d/%m/%Y}: a validade é julgada naquele dia" in t and f"Pegar 4 un do {nome_lote(v)}" in t
    assert "vencido" not in t.split("De onde pegar")[1].split("Peguei de outro lote")[0].replace("Lote vencido", "")
    r = client.post(reverse("vender"), {**d, "acao": "confirmar"}, follow=True)
    assert f"Venda 1 do dia {dia(-3):%d/%m/%Y} registrada" in limpo(r)
    assert Venda.objects.get().data == dia(-3) and saldo_lote(v, "congelado") == 6
    assert Movimento.objects.get(tipo="saida_venda").motivo_vencido == ""  # estava válido naquele dia: sem motivo


def test_data_de_hoje_com_lote_vencido_nao_vende_sozinha(client, dono, coxinha, unidade):
    lote(coxinha, 10, validade=dia(-1), feito=dia(-10), codigo="V1")
    t = limpo(client.post(reverse("vender"), {**post_venda(unidade, 4), "acao": "separar"}))
    assert "Faltam 4 un" in t and "só sai indicando o lote e um motivo" in t


def test_data_futura_mostra_a_mensagem_do_nucleo(client, dono, unidade, dois):
    for acao in ("separar", "confirmar"):
        r = client.post(reverse("vender"), post_venda(unidade, 2, acao=acao, data_venda=dia(2).isoformat()))
        assert f"A venda não pode ter data depois de hoje ({dia(2):%d/%m})." in texto(r)
    assert Venda.objects.count() == 0
    assert "Data da venda: data inválida." in texto(client.post(reverse("vender"), post_venda(unidade, 2, data_venda="ontem")))


# ---------- 4. motivo do vencido ----------

def test_vencido_indicado_pede_motivo_e_segue_com_ele(client, dono, coxinha, unidade):
    v = lote(coxinha, 10, validade=dia(-1), feito=dia(-10), codigo="V1")
    d = post_venda(unidade, 5, **{f"lote_{unidade}_{v.id}": "5"})
    r = client.post(reverse("vender"), {**d, "acao": "separar"})
    t = texto(r)
    assert "informe o motivo" in t and re.search(r'<details class="cancelar" open>\s*<summary>Lote vencido', t)
    r = client.post(reverse("vender"), {**d, "acao": "confirmar", "visto": visto(r)})  # sem motivo: o núcleo recusa
    t = texto(r)
    assert "Lote vencido só sai com um motivo" in t and Venda.objects.count() == 0
    assert re.search(r'<details class="cancelar" open>\s*<summary>Lote vencido', t) and 'name="motivo_vencido" value=""' in t
    r = client.post(reverse("vender"), {**d, "acao": "confirmar", "motivo_vencido": "conferi, está bom", "chave": "c2"},
                    follow=True)
    assert "registrada" in limpo(r) and saldo_lote(v, "congelado") == 5
    assert Movimento.objects.get(tipo="saida_venda").motivo_vencido == "conferi, está bom"
    assert "conferi, está bom" in limpo(client.get(reverse("vendas")))
    assert "Lote vencido, seguiu com o motivo: conferi, está bom" in limpo(client.get(reverse("historico")))


def test_o_motivo_nunca_vem_preenchido_sozinho(client, dono, coxinha, unidade):
    v = lote(coxinha, 10, validade=dia(-1), feito=dia(-10))
    r = client.post(reverse("vender"), {**post_venda(unidade, 5, **{f"lote_{unidade}_{v.id}": "5"}), "acao": "separar"})
    assert 'name="motivo_vencido" value=""' in texto(r)


def test_fritura_de_vencido_so_com_motivo(client, dono, coxinha):
    CriterioValidade.objects.create(produto=coxinha, forma="frito", estado="fresco", dias=1)
    v = lote(coxinha, 20, validade=dia(-1), feito=dia(-8), estado="resfriado", codigo="V1")
    t = texto(client.get(reverse("fritura"), {"produto": coxinha.id}))
    assert f'value="{v.id}|resfriado"' in t and f"venceu em {dia(-1):%d/%m/%Y}" in t and nome_lote(v) in t
    d = {"chave": "f1", "produto": coxinha.id, "porcao": f"{v.id}|resfriado", "quantidade": "2", "boas": "2",
         "estado_destino": "fresco"}
    t = texto(client.post(reverse("fritura"), d))
    assert "não pode ser frito sem um motivo" in t and re.search(r'<details class="cancelar" open>\s*<summary>Lote vencido', t)
    r = client.post(reverse("fritura"), {**d, "chave": "f2", "motivo_vencido": "lanche da equipe"}, follow=True)
    assert "Fritura registrada" in limpo(r)
    assert Movimento.objects.get(tipo="consumo_fritura").motivo_vencido == "lanche da equipe"


def test_mudar_conservacao_de_vencido_so_com_motivo(client, dono, coxinha):
    v = lote(coxinha, 20, validade=dia(-1), feito=dia(-8), estado="resfriado", codigo="V1")
    d = {"chave": "t1", "quantidade": "5", "de": "resfriado", "para": "congelado"}
    r = client.post(reverse("lote", args=[v.id]), d)
    assert "só aceita descarte" in texto(r) and "Motivo do vencido" in texto(r)
    r = client.post(reverse("lote", args=[v.id]), {**d, "chave": "t2", "motivo_vencido": "congelar até decidir"}, follow=True)
    assert "Conservação alterada." in limpo(r) and saldo_lote(v, "congelado") == 5
    assert "congelar até decidir" in str(Movimento.objects.filter(lote=v).values_list("motivo_vencido", flat=True))


def test_devolver_ao_estoque_lote_vencido_pede_motivo_e_reabre_o_cancelamento(client, dono, coxinha, unidade):
    bom = lote(coxinha, 10, validade=dia(5), feito=dia(-1), codigo="B1")
    venda = registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 2}], forma_pagamento="pix", autor="dono")
    vence(bom, dia(-1))
    r = client.post(reverse("cancelar_venda", args=[venda["venda_id"]]),
                    {"chave": "c1", "motivo": "devolveu", "destino": "estoque"}, follow=True)
    t = texto(r)
    assert "venceu: a devolução vai para perda" in t
    assert re.search(r'<details class="cancelar" open><summary>Cancelar venda', t) and "Lote vencido? Informe o motivo" in t
    assert Venda.objects.get().situacao == "concluida"
    r = client.post(reverse("cancelar_venda", args=[venda["venda_id"]]),
                    {"chave": "c2", "motivo": "devolveu", "destino": "estoque", "motivo_vencido": "vai para a conferência"},
                    follow=True)
    assert "cancelada" in limpo(r) and "voltaram ao estoque" in limpo(r)
    assert Movimento.objects.get(tipo="devolucao_cliente").motivo_vencido == "vai para a conferência"


def test_fechamento_da_producao_so_mostra_o_motivo_do_vencido_quando_o_sistema_pede(client, dono, bolinha):
    from producao.models import Producao
    from producao.servicos import iniciar_producao, ir_para_etapa, usar_previsto_restantes
    p = iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono",
                         pendente_justificativa="nota atrasada")["producao_id"]
    usar_previsto_restantes(producao_id=p, autor="dono")
    ir_para_etapa(producao_id=p, indice=Producao.objects.get(id=p).fechamento, autor="dono")
    url = reverse("producao", args=[p])
    assert "Motivo do vencido" not in texto(client.get(url))
    assert "Motivo do vencido" in texto(client.get(url, {"motivo": "1"}))


# ---------- 3. separação na entrega da encomenda ----------

@pytest.fixture
def joao():
    return salvar_cliente(nome="João", autor="dono")["cliente_id"]


def encomenda_pronta(joao, unidade, n=10):
    e = criar_encomenda(cliente_id=joao, entrega_data=dia(1), itens=[{"apresentacao_id": unidade, "quantidade": n}],
                        autor="dono")["encomenda_id"]
    return e


def test_entrega_mostra_de_qual_lote_pegar_pelas_reservas(client, dono, coxinha, unidade, dois, joao):
    velho, novo = dois
    e = encomenda_pronta(joao, unidade)
    t = limpo(client.get(reverse("encomenda", args=[e])))
    assert f"Pegar 10 un do {nome_lote(velho)} (código A1)" in t and "sobram 8 un nele" in t
    assert "Peguei de outro lote" in t and "Dia da entrega" in t
    r = client.post(reverse("encomenda", args=[e]), {"acao": "entregar", "chave": "e1", "condicao": "a_vista",
                                                     "forma_pagamento": "pix"}, follow=True)
    assert "Encomenda entregue" in limpo(r) and saldo_lote(velho, "congelado") == 8


def test_entrega_peguei_de_outro_lote_mostra_deixado_e_grava(client, dono, coxinha, unidade, dois, joao):
    velho, novo = dois
    e = encomenda_pronta(joao, unidade)
    item = Venda.objects  # (sem uso: o item da encomenda é o primeiro)
    from vendas.models import ItemEncomenda
    ie = ItemEncomenda.objects.get(encomenda_id=e)
    d = {"acao": "separar", "chave": "e1", "condicao": "a_vista", "forma_pagamento": "pix",
         f"lote_{ie.id}_{novo.id}": "10"}
    r = client.post(reverse("encomenda", args=[e]), d)
    t = limpo(r)
    assert f"Pegar 10 un do {nome_lote(novo)}" in t and f"Ficaram 18 un do {nome_lote(velho)}" in t
    r = client.post(reverse("encomenda", args=[e]), {**d, "acao": "entregar", "visto": visto(r), "chave": "e2"}, follow=True)
    assert "Encomenda entregue" in limpo(r) and "Ficaram 18 un" in limpo(r)
    assert (saldo_lote(velho, "congelado"), saldo_lote(novo, "congelado")) == (18, 20)


def test_entrega_com_reserva_vencida_pede_motivo(client, dono, coxinha, unidade, dois, joao):
    velho, novo = dois
    e = encomenda_pronta(joao, unidade)
    vence(velho, dia(-1))
    t = limpo(client.get(reverse("encomenda", args=[e])))
    assert "Complete a reserva com outro lote ou, para entregar dele mesmo assim, informe o motivo" in t
    d = {"acao": "entregar", "chave": "e1", "condicao": "a_vista", "forma_pagamento": "pix"}
    r = client.post(reverse("encomenda", args=[e]), d)
    t = texto(r)
    assert "informe o motivo" in t and re.search(r'<details class="cancelar" open>\s*<summary>Lote vencido', t)
    assert Venda.objects.count() == 0
    r = client.post(reverse("encomenda", args=[e]), {**d, "chave": "e2", "motivo_vencido": "reserva conferida"}, follow=True)
    assert "Encomenda entregue" in limpo(r)
    assert Movimento.objects.get(tipo="saida_venda").motivo_vencido == "reserva conferida"


# ---------- 5 e 6. conferência do vencido e contagem ----------

@pytest.fixture
def vencido(coxinha, unidade):
    v = lote(coxinha, 18, validade=dia(-1), feito=dia(-10), codigo="V1")
    rodar_rotina()
    return v


def test_caixa_mostra_os_tres_caminhos_da_conferencia(client, dono, vencido):
    r = client.get(reverse("caixa"))
    t = texto(r)
    assert "Ainda estão aí?" in t and nome_lote(vencido) in t
    assert (f'href="{reverse("vender")}?lote={vencido.id}&estado=congelado&data_venda={dia(-1):%Y-%m-%d}"') in t
    assert "Já foram vendidas" in t and "Não sei: contar" in t and "Estão aqui: dar destino" in t
    assert f'href="{reverse("contar_lote", args=[vencido.id])}?estado=congelado&next=%2Fdecisoes%2F"' in t
    assert f'action="{reverse("descartar", args=[vencido.id])}"' in t and 'value="consumo_equipe"' in t and 'value="doacao"' in t


def test_ja_foram_vendidas_abre_a_venda_com_data_e_lote(client, dono, coxinha, unidade, vencido):
    r = client.get(reverse("vender"), {"lote": vencido.id, "estado": "congelado", "data_venda": dia(-1).isoformat()})
    t = texto(r)
    assert f'name="data_venda" value="{dia(-1):%Y-%m-%d}"' in t and f'name="todo_{unidade}" value="{vencido.id}"' in t
    assert f"Venda atrasada do {nome_lote(vencido)} de Coxinha 150 g" in limpo(r) and "ainda mostra 18 un" in limpo(r)
    d = {"chave": "v1", "condicao": "a_vista", "forma_pagamento": "pix", "tabela": "varejo", f"qtd_{unidade}": "5",
         "data_venda": dia(-1).isoformat(), f"todo_{unidade}": str(vencido.id), "acao": "separar"}
    r = client.post(reverse("vender"), d)
    assert f"Pegar 5 un do {nome_lote(vencido)}" in limpo(r) and "sobram 13 un nele" in limpo(r)
    r = client.post(reverse("vender"), {**d, "acao": "confirmar", "visto": visto(r)}, follow=True)
    assert f"do dia {dia(-1):%d/%m/%Y} registrada" in limpo(r)
    assert saldo_lote(vencido, "congelado") == 13 and Movimento.objects.get(tipo="saida_venda").motivo_vencido == ""
    assert LinhaVenda.objects.get().lotes_indicados


def test_estao_aqui_registra_o_destino_com_motivo(client, dono, vencido):
    d = {"estado": "congelado", "quantidade": "3", "destino": "consumo_equipe", "motivo": "lanche da equipe",
         "chave": "p1", "next": "/decisoes/"}
    r = client.post(reverse("descartar", args=[vencido.id]), d, follow=True)
    assert "Consumo da equipe registrado: 3 un de Coxinha 150 g" in limpo(r)
    m = Movimento.objects.get(tipo="perda")
    assert (m.destino, m.motivo, saldo_lote(vencido, "congelado")) == ("consumo_equipe", "lanche da equipe", 15)
    r = client.post(reverse("descartar", args=[vencido.id]), {**d, "chave": "p2", "motivo": " "}, follow=True)
    assert "Informe o motivo da perda." in limpo(r)


def test_nao_sei_conta_o_lote_e_mostra_antes_depois_e_diferenca(client, dono, vencido):
    url = reverse("contar_lote", args=[vencido.id])
    t = limpo(client.get(url, {"estado": "congelado"}))
    assert f"Contar lote Coxinha 150 g · {nome_lote(vencido)}" in t and "O sistema diz" in t and "Congelado 18 un" in t
    d = {"estado": "congelado", "contado": "15", "motivo": "conferência do vencido", "chave": "n1", "next": "/decisoes/"}
    r = client.post(url, d, follow=True)
    assert ("o sistema dizia 18 un, você contou 15 un; diferença de -3 un (-R$ 1,80)") in limpo(r)
    assert saldo_lote(vencido, "congelado") == 15
    m = Movimento.objects.get(tipo="ajuste_contagem")
    assert (m.quantidade, m.motivo) == (D("-3"), "Contagem: conferência do vencido")
    assert client.post(url, d).status_code == 302 and Movimento.objects.filter(tipo="ajuste_contagem").count() == 1  # mesma chave


def test_contar_recusas_aparecem_na_tela(client, dono, vencido):
    url = reverse("contar_lote", args=[vencido.id])
    base = {"estado": "congelado", "chave": "n1", "motivo": "contei"}
    assert "Informe quanto há de fato" in texto(client.post(url, {**base, "contado": ""}))
    assert "Informe o motivo do ajuste" in texto(client.post(url, {**base, "contado": "4", "motivo": " ", "chave": "n2"}))
    assert "não pode ser negativa" in texto(client.post(url, {**base, "contado": "-1", "chave": "n3"}))
    assert "use vírgula" in texto(client.post(url, {**base, "contado": "1.5", "chave": "n4"}))
    assert Movimento.objects.filter(tipo="ajuste_contagem").count() == 0


def test_contar_tambem_a_partir_da_tela_do_lote_e_achar_mais(client, dono, coxinha):
    l = lote(coxinha, 18, validade=dia(5), feito=dia(-1), codigo="K1")
    t = texto(client.get(reverse("lote", args=[l.id])))
    assert f'href="{reverse("contar_lote", args=[l.id])}?estado=congelado"' in t and nome_lote(l) in t
    r = client.post(reverse("contar_lote", args=[l.id]), {"estado": "congelado", "contado": "20", "motivo": "achei mais",
                                                          "chave": "n1"}, follow=True)
    assert "o sistema dizia 18 un, você contou 20 un; diferença de +2 un" in limpo(r) and saldo_lote(l, "congelado") == 20


def test_ingrediente_ja_usado_vai_para_a_contagem(client, dono, coxinha):
    farinha = Item.objects.create(nome="Farinha", tipo="ingrediente", unidade_base="g")
    l = lote(farinha, 500, validade=dia(-1), feito=dia(-10), forma="", codigo="F1")
    rodar_rotina()
    t = texto(client.get(reverse("caixa")))
    assert "Já foram usadas" in t and f'href="{reverse("contar_lote", args=[l.id])}?estado=congelado&next=%2Fdecisoes%2F"' in t


# ---------- 7. destino na perda ----------

def test_sobras_perda_com_destino(client, dono, coxinha):
    f = lote(coxinha, 12, validade=dia(1), forma="frito", estado="fresco", custo="0.70", codigo="F1")
    assert 'name="destino"' in texto(client.get(reverse("sobras"))) and "Doação" in texto(client.get(reverse("sobras")))
    r = client.post(reverse("sobras"), {"lote": f.id, "estado": "fresco", "quantidade": "2", "motivo": "para a creche",
                                        "destino": "doacao", "chave": "s1"}, follow=True)
    assert "Doação registrada: 2 un" in limpo(r)
    assert Movimento.objects.get(tipo="perda").destino == "doacao"
    r = client.post(reverse("sobras"), {"lote": f.id, "estado": "fresco", "quantidade": "1", "motivo": "x",
                                        "destino": "lixo", "chave": "s2"}, follow=True)
    assert "Destino inválido" in limpo(r)


# ---------- 8. venda primeiro ----------

def test_venda_primeiro_na_tela_hoje_e_rotulo_na_caixa(client, dono, coxinha, unidade):
    velho = lote(coxinha, 18, validade=dia(6), feito=dia(-3), codigo="A1")
    novo = lote(coxinha, 30, validade=dia(20), feito=dia(-1), codigo="B1")
    registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 5, "lotes": [{"lote_id": novo.id, "unidades": 5}]}],
                    autor="dono", chave="v1")
    t = limpo(client.get(reverse("inicio")))
    assert "Venda primeiro" in t and f"{nome_lote(velho)} (congelado) · 18 un livres · vence {dia(6):%d/%m}" in t
    rodar_rotina()
    assert Decisao.objects.filter(origem="lotes_deixados").exists()
    assert "Lote deixado para trás" in texto(client.get(reverse("caixa")))
    vendas_novas = registrar_venda(itens=[{"apresentacao_id": unidade, "quantidade": 18}], autor="dono", chave="v2")
    assert vendas_novas and "Venda primeiro" not in limpo(client.get(reverse("inicio")))


# ---------- 9 e 10. etiqueta e nome do lote ----------

def test_etiqueta_traz_o_dia_da_producao_em_destaque(client, dono, coxinha):
    l = lote(coxinha, 12, validade=dia(5), feito=dia(-2), codigo="K1")
    r = client.get(reverse("etiquetas", args=[l.id]), {"estado": "congelado"})
    t = texto(r)
    assert f'<div class="dia" aria-label="Dia da produção">{dia(-2).day}</div>' in t and nome_lote(l) in t
    p = limpo(r)
    assert "Coxinha 150 g" in p and "Lote: K1" in p and f"Validade: {dia(5):%d/%m/%Y}" in p and "congelado" in p.lower() and "cru" in p.lower()


def test_nome_do_lote_junto_do_codigo_nas_listas(client, dono, coxinha):
    l = lote(coxinha, 12, validade=dia(-1), feito=dia(-2), codigo="K1")
    for url in (reverse("lote", args=[l.id]), reverse("inicio")):
        t = limpo(client.get(url))
        assert nome_lote(l) in t and "K1" in t, url
    f = lote(coxinha, 5, validade=dia(1), forma="frito", estado="fresco", codigo="F1")
    assert nome_lote(f) in limpo(client.get(reverse("sobras")))


def test_contar_exige_login(client):
    assert client.get(reverse("contar_lote", args=[1])).status_code == 302
    assert client.post(reverse("contar_lote", args=[1]), {}).status_code == 302
