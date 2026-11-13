"""Plano 8, fase 2a: telas de despesas, categorias, canais e taxas, referências, resultado depois das despesas,
margem com indiretos e estudo de preço. Gravar passa pelos serviços; erro de regra vira mensagem na tela."""
import datetime as dt
import html as _html
import re
import uuid
from decimal import Decimal as D

import pytest
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Fornecedor, Item
from cadastros.servicos import salvar_referencias
from compras.servicos import registrar_compra
from financeiro.models import CategoriaDespesa, Conta, DespesaDoMes, DespesaMensal
from vendas.models import CanalVenda
from vendas.servicos import salvar_apresentacao, salvar_canal_venda

pytestmark = pytest.mark.django_db
HOJE = timezone.localdate()
MES = HOJE.strftime("%Y-%m")


def limpo(r):
    return " ".join(re.sub(r"<[^>]+>", " ", _html.unescape(r.content.decode())).split())


def enviar(client, rota, args=None, **dados):
    """POST com chave nova (como o formulário faz) e segue o redirecionamento."""
    return client.post(reverse(rota, args=args or []), {"chave": uuid.uuid4().hex, **dados}, follow=True)


def cat(nome):
    return CategoriaDespesa.objects.get(nome=nome).id


def criar_mensal(client, nome, categoria, **extra):
    return enviar(client, "despesa_mensal_nova", nome=nome, categoria=cat(categoria), dia_vencimento="10", ativa="on",
                  **extra)


@pytest.fixture
def bolinha_a_5(bolinha):
    """Bolinha: CMV R$ 0,50, indiretos R$ 0,74, a R$ 5,00; crédito com taxa 4%, débito sem taxa."""
    atacadao = Fornecedor.objects.create(nome="Atacadão")
    farinha = Item.objects.get(nome="Farinha de trigo")
    registrar_compra(fornecedor_id=atacadao.id, data_compra=HOJE, total=D("10"), condicao="a_vista",
                     linhas=[{"item_id": farinha.id, "quantidade": D("2"), "unidade": "kg", "valor": D("10")}],
                     autor="dono")
    salvar_referencias(produto_id=bolinha.id, oleo_ref_un="0.05", indireto_ref_un="0.74", autor="dono")
    credito = CanalVenda.objects.get(nome="Cartão de crédito")
    salvar_canal_venda(canal_id=credito.id, nome=credito.nome, taxa_pct="4", autor="dono")
    apr = salvar_apresentacao(produto_id=bolinha.id, nome="unidade", forma="cru", estado="congelado", unidades=1,
                              preco_varejo=D("5"), autor="dono")["apresentacao_id"]
    return {"apr": apr, "credito": credito.id}


# ---------- acesso ----------

def urls():
    return [reverse(n) for n in ("despesas", "despesa_nova", "despesas_mensais", "despesa_mensal_nova",
                                 "categorias_despesa", "canais_venda", "referencias", "estudo_preco")]


def test_telas_exigem_login(client):
    for u in urls() + [reverse("despesa_mensal", args=[1]), reverse("despesa_pagar")]:
        r = client.get(u)
        assert r.status_code == 302 and "/entrar/" in r.url, u


def test_telas_abrem_logado(client, dono, bolinha_a_5):
    criar_mensal(client, "Internet", "Internet")
    mensal = DespesaMensal.objects.get(nome="Internet")
    for u in urls() + [reverse("despesa_mensal", args=[mensal.id]), reverse("despesas") + f"?mes={MES}",
                       reverse("relatorio"), reverse("margens"), reverse("custos"), reverse("inicio")]:
        assert client.get(u).status_code == 200, u
    assert client.get(reverse("despesa_mensal", args=[9999])).status_code == 404
    for u in ("despesas/valor/", "despesas/pagar/", "despesas/cancelar/"):  # só POST: GET volta ao mês
        assert client.get("/" + u).status_code == 302


# ---------- o mês ----------

def test_mensal_sem_valor_aparece_como_sem_valor_e_nunca_como_zero(client, dono):
    r = criar_mensal(client, "Internet", "Internet")
    assert "Despesa mensal salva." in limpo(r) and "Já está nas despesas deste mês." in limpo(r)
    assert DespesaMensal.objects.get(nome="Internet").valor_previsto is None
    t = limpo(client.get(reverse("despesas")))
    assert "Internet" in t and "sem valor" in t and "Valor: —" in t
    assert "1 despesa(s) ainda sem valor" in t and "Total do mês: R$ 0,00" in t
    assert "Falta pagar (1)" in t
    assert "Valor: R$ 0,00" not in t


def test_mensal_com_valor_previsto_entra_no_total(client, dono):
    criar_mensal(client, "Energia", "Energia", valor_previsto="850")
    t = limpo(client.get(reverse("despesas")))
    assert "R$ 850,00" in t and "falta pagar R$ 850,00" in t
    assert "Energia (indireta): R$ 850,00" in t


def test_informar_valor_nao_paga(client, dono):
    criar_mensal(client, "Internet", "Internet")
    dm = DespesaDoMes.objects.get()
    r = enviar(client, "despesa_valor", despesa=dm.id, valor="99,90", next=reverse("despesas"))
    assert "Valor anotado: R$ 99,90" in limpo(r)
    t = limpo(client.get(reverse("despesas")))
    assert "falta pagar R$ 99,90" in t and "sem valor" not in t.replace("0 despesa(s) ainda sem valor", "")
    r = enviar(client, "despesa_valor", despesa=dm.id, valor="abc")
    assert "número inválido" in limpo(r)
    r = enviar(client, "despesa_valor", despesa=dm.id, valor="0")
    assert "maior que zero" in limpo(r)


def test_pagar_mensal_com_valor_real_e_data(client, dono):
    criar_mensal(client, "Energia", "Energia", valor_previsto="850")
    dm = DespesaDoMes.objects.get()
    data = (HOJE - dt.timedelta(days=1)).isoformat()
    r = enviar(client, "despesa_pagar", tipo="mensal", despesa=dm.id, valor="812,40", data_pagamento=data,
               forma="pix", next=reverse("despesas"))
    assert "Pagamento anotado: R$ 812,40. Despesa quitada." in limpo(r)
    assert Conta.objects.get(origem="despesa").total == D("812.40")  # o real substitui o previsto
    t = limpo(client.get(reverse("despesas")))
    assert "falta pagar R$ 0,00" in t and "Já pagas (1)" in t
    r = enviar(client, "despesa_pagar", tipo="mensal", despesa=dm.id, valor="812,40")
    assert "já está paga" in limpo(r)


def test_pagar_mensal_sem_valor_exige_o_valor(client, dono):
    criar_mensal(client, "Internet", "Internet")
    dm = DespesaDoMes.objects.get()
    r = enviar(client, "despesa_pagar", tipo="mensal", despesa=dm.id, valor="")
    assert "ainda não tem valor" in limpo(r)
    r = enviar(client, "despesa_pagar", tipo="mensal", despesa=dm.id, valor="99,90", data_pagamento="")
    assert "Despesa quitada" in limpo(r)


def test_pagar_em_lote_percorrendo_a_lista(client, dono):
    criar_mensal(client, "Energia", "Energia", valor_previsto="850")
    criar_mensal(client, "Internet", "Internet")
    for nome, valor in (("Energia", "800"), ("Internet", "100")):
        dm = DespesaDoMes.objects.get(despesa__nome=nome)
        enviar(client, "despesa_pagar", tipo="mensal", despesa=dm.id, valor=valor, next=reverse("despesas"))
    t = limpo(client.get(reverse("despesas")))
    assert "Nada a pagar neste mês" in t and "Já pagas (2)" in t and "Total do mês: R$ 900,00" in t


def test_cancelar_exige_motivo_e_estorna(client, dono):
    criar_mensal(client, "Energia", "Energia", valor_previsto="850")
    dm = DespesaDoMes.objects.get()
    enviar(client, "despesa_pagar", tipo="mensal", despesa=dm.id, valor="850")
    conta = Conta.objects.get(origem="despesa")
    r = enviar(client, "despesa_cancelar", conta=conta.id, motivo="  ")
    assert "Informe o motivo do cancelamento." in limpo(r)
    r = enviar(client, "despesa_cancelar", conta=conta.id, motivo="não teve luz")
    assert "Despesa cancelada. O pagamento anotado nela foi estornado." in limpo(r)
    t = limpo(client.get(reverse("despesas")))
    assert "Canceladas" in t and "não teve luz" in t and "Total do mês: R$ 0,00" in t
    r = enviar(client, "despesa_cancelar", conta=conta.id, motivo="de novo")
    assert "já foi cancelada" in limpo(r)


# ---------- lançar avulsa ----------

def test_lancar_avulsa_ja_paga(client, dono):
    r = enviar(client, "despesa_nova", descricao="Diarista", categoria=cat("Diária"), valor="120,50", paga="sim",
               data_pagamento=HOJE.isoformat())
    t = limpo(r)
    assert "Despesa lançada: R$ 120,50, já paga." in t
    assert "Diarista" in t and "Já pagas (1)" in t and "Diária (indireta): R$ 120,50" in t


def test_lancar_avulsa_a_pagar_com_vencimento(client, dono):
    venc = HOJE + dt.timedelta(days=5)
    r = enviar(client, "despesa_nova", descricao="Conserto do forno", categoria=cat("Outras"), valor="300", paga="nao",
               vencimento=venc.isoformat())
    t = limpo(r)
    assert f"a pagar até {venc:%d/%m/%Y}" in t and "Conserto do forno" in t and "Falta pagar (1)" in t
    conta = Conta.objects.get(descricao="Conserto do forno")
    t = limpo(enviar(client, "despesa_pagar", tipo="avulsa", parcela=conta.parcelas.get().id, valor="",
                     next=reverse("despesas")))
    assert "Despesa quitada" in t  # valor em branco: paga o saldo


def test_lancar_avulsa_invalida_mostra_mensagem(client, dono):
    r = client.post(reverse("despesa_nova"), {"chave": uuid.uuid4().hex, "descricao": "", "categoria": cat("Gás"),
                                              "valor": "10", "paga": "sim"})
    assert r.status_code == 200 and "Diga do que é a despesa." in limpo(r)
    r = client.post(reverse("despesa_nova"), {"chave": uuid.uuid4().hex, "descricao": "Gás", "categoria": cat("Gás"),
                                              "valor": "10", "paga": "nao", "vencimento": ""})
    assert "Informe o vencimento" in limpo(r)
    r = client.post(reverse("despesa_nova"), {"chave": uuid.uuid4().hex, "descricao": "Gás", "categoria": "",
                                              "valor": "10"})
    assert "Categoria: escolha uma opção." in limpo(r)
    r = client.post(reverse("despesa_nova"), {"descricao": "Gás", "categoria": cat("Gás"), "valor": "10"})
    assert r.status_code == 200 and "Formulário sem chave" in limpo(r)
    assert Conta.objects.filter(origem="despesa").count() == 0


def test_navegacao_de_mes_e_mes_invalido(client, dono):
    r = client.get(reverse("despesas"), {"mes": "2025-03"})
    t = limpo(r)
    assert "Despesas de 03/2025" in t and "02/2025" in t and "04/2025" in t and "Nada a pagar neste mês." in t
    r = client.get(reverse("despesas"), {"mes": "lixo"})
    assert r.status_code == 200 and "Mês inválido" in limpo(r)


# ---------- despesas mensais (cadastro) ----------

def test_criar_e_editar_despesa_mensal(client, dono):
    r = enviar(client, "despesa_mensal_nova", nome="Funcionário", categoria=cat("Mão de obra"), dia_vencimento="5",
               valor_previsto="2200", ativa="on")
    t = limpo(r)
    assert "Funcionário" in t and "Vence todo dia 5" in t and "R$ 2.200,00" in t
    d = DespesaMensal.objects.get(nome="Funcionário")
    enviar(client, "despesa_mensal", args=[d.id], nome="Funcionário", categoria=cat("Mão de obra"), dia_vencimento="",
           valor_previsto="", ativa="")
    d.refresh_from_db()
    assert (d.dia_vencimento, d.valor_previsto, d.ativa) == (10, None, False)  # dia em branco = 10
    t = limpo(client.get(reverse("despesas_mensais")))
    assert "inativa" in t and "valor previsto: não informado" in t


def test_despesa_mensal_invalida_mostra_mensagem(client, dono):
    for dados, esperado in (({"nome": "", "categoria": cat("Gás")}, "nome"),
                            ({"nome": "Gás", "categoria": ""}, "Categoria: escolha uma opção."),
                            ({"nome": "Gás", "categoria": cat("Gás"), "dia_vencimento": "40"}, "1 a 31"),
                            ({"nome": "Gás", "categoria": cat("Gás"), "dia_vencimento": "x"}, "1 a 31"),
                            ({"nome": "Gás", "categoria": cat("Gás"), "valor_previsto": "-3"}, "maior que zero"),
                            ({"nome": "Gás", "categoria": cat("Gás"), "valor_previsto": "1.5"}, "vírgula")):
        r = client.post(reverse("despesa_mensal_nova"), {"chave": uuid.uuid4().hex, "ativa": "on", **dados})
        assert r.status_code == 200 and esperado.lower() in limpo(r).lower(), dados
    assert DespesaMensal.objects.count() == 0
    criar_mensal(client, "Gás", "Gás")
    r = client.post(reverse("despesa_mensal_nova"), {"chave": uuid.uuid4().hex, "nome": "gás", "categoria": cat("Gás")})
    assert "Já existe a despesa mensal" in limpo(r)


# ---------- categorias, canais e taxas ----------

def test_categorias_criar_e_editar(client, dono):
    r = enviar(client, "categorias_despesa", nome="Aluguel", indireta="on")
    assert "Categoria salva." in limpo(r) and CategoriaDespesa.objects.get(nome="Aluguel").indireta
    c = CategoriaDespesa.objects.get(nome="Aluguel")
    enviar(client, "categorias_despesa", categoria_id=c.id, nome="Aluguel", ativa="on")
    c.refresh_from_db()
    assert not c.indireta and c.ativa
    assert "Já existe a categoria" in limpo(enviar(client, "categorias_despesa", nome="aluguel"))
    assert "Informe o nome" in limpo(enviar(client, "categorias_despesa", nome=" "))


def test_taxa_em_branco_aparece_como_nao_informada_e_pode_ser_preenchida(client, dono):
    t = limpo(client.get(reverse("canais_venda")))
    assert "Cartão de débito — taxa: não informada" in t and "Balcão — pix — taxa: 0,0%" in t
    debito = CanalVenda.objects.get(nome="Cartão de débito")
    r = enviar(client, "canais_venda", canal_id=debito.id, nome="Cartão de débito", taxa_pct="1,99", ativo="on")
    assert "Canal salvo." in limpo(r) and "Cartão de débito — taxa: 2,0%" in limpo(r)
    debito.refresh_from_db()
    assert debito.taxa_pct == D("1.99")
    enviar(client, "canais_venda", canal_id=debito.id, nome="Cartão de débito", taxa_pct="", ativo="on")
    debito.refresh_from_db()
    assert debito.taxa_pct is None
    assert "de 0% a menos de 100%" in limpo(enviar(client, "canais_venda", canal_id=debito.id, nome="Cartão de débito",
                                                    taxa_pct="100", ativo="on"))
    assert "Canal salvo." in limpo(enviar(client, "canais_venda", nome="iFood", taxa_pct="12"))
    assert CanalVenda.objects.get(nome="iFood").taxa_pct == D("12")


# ---------- referências do tamanho ----------

def test_referencias_do_tamanho(client, dono, bolinha):
    t = limpo(client.get(reverse("referencias")))
    assert bolinha.nome in t
    r = enviar(client, "referencias", produto=bolinha.id, oleo_ref_un="0,05", indireto_ref_un="0,7416")
    assert "Referências salvas." in limpo(r)
    bolinha.refresh_from_db()
    assert (bolinha.oleo_ref_un, bolinha.indireto_ref_un) == (D("0.05"), D("0.7416"))
    assert 'value="0,7416"' in client.get(reverse("referencias")).content.decode()
    enviar(client, "referencias", produto=bolinha.id, oleo_ref_un="0,05", indireto_ref_un="")
    bolinha.refresh_from_db()
    assert bolinha.indireto_ref_un is None
    assert "negativa" in limpo(enviar(client, "referencias", produto=bolinha.id, oleo_ref_un="-1"))
    assert "número inválido" in limpo(enviar(client, "referencias", produto=bolinha.id, oleo_ref_un="x"))
    assert "Produto: escolha" in limpo(enviar(client, "referencias", produto="", oleo_ref_un="1"))
    assert reverse("referencias") in client.get(reverse("custos")).content.decode()


# ---------- relatório: depois das despesas ----------

def test_relatorio_mostra_antes_e_depois_das_despesas_e_o_que_falta(client, dono):
    criar_mensal(client, "Energia", "Energia", valor_previsto="850")
    criar_mensal(client, "Internet", "Internet")
    t = limpo(client.get(reverse("relatorio"), {"periodo": "mes"}))
    assert "antes das despesas" in t and "Resultado depois das despesas" in t
    assert f"falta o valor de Internet de {HOJE:%m/%Y}" in t
    assert "Resultado incompleto" in t and "estimado, faltando despesa sem valor" in t
    assert "Energia (indireta)" in t and "Despesas por categoria" in t
    assert "Ainda sem pagamento anotado" in t  # entrou pelo valor previsto


def test_relatorio_completo_depois_de_informar_o_valor(client, dono):
    criar_mensal(client, "Internet", "Internet")
    dm = DespesaDoMes.objects.get()
    enviar(client, "despesa_pagar", tipo="mensal", despesa=dm.id, valor="100")
    t = limpo(client.get(reverse("relatorio"), {"periodo": "mes"}))
    assert "Resultado incompleto" not in t and "R$ 100,00" in t
    assert "-R$ 100,00" in t  # sem vendas: antes 0, depois −100


# ---------- margem com indiretos ----------

def test_margens_mostra_com_indiretos_sem_esconder_a_atual(client, dono, bolinha_a_5):
    t = limpo(client.get(reverse("margens")))
    assert "Margem estimada dos preços de hoje" in t
    assert "Varejo R$ 5,00: margem R$ 4,50 (90,0%)" in t  # a margem atual continua
    assert "Com indiretos" in t and "varejo R$ 3,76 (75,2%)" in t
    assert "mão de obra, energia e gás" in t


def test_margens_sem_indireto_cadastrado_diz_que_nao_da_para_calcular(client, dono, bolinha):
    comprar = Fornecedor.objects.create(nome="X")
    farinha = Item.objects.get(nome="Farinha de trigo")
    registrar_compra(fornecedor_id=comprar.id, data_compra=HOJE, total=D("10"), condicao="a_vista",
                     linhas=[{"item_id": farinha.id, "quantidade": D("2"), "unidade": "kg", "valor": D("10")}],
                     autor="dono")
    salvar_apresentacao(produto_id=bolinha.id, nome="unidade", forma="cru", estado="congelado", unidades=1,
                        preco_varejo=D("5"), autor="dono")
    t = limpo(client.get(reverse("margens")))
    assert "não cadastrados" in t and "sem como calcular" in t


# ---------- estudo de preço ----------

def test_estudo_de_preco_por_canal(client, dono, bolinha_a_5):
    t = limpo(client.get(reverse("estudo_preco")))
    assert "Estudo de preço" in t and "CMV R$ 0,50 = 10,0% do preço" in t
    assert "Indiretos de referência: R$ 0,74" in t
    assert "Sobra: R$ 3,76 (75,2% do preço)" in t  # balcão em dinheiro, taxa 0%
    c = bolinha_a_5["credito"]
    t = limpo(client.get(reverse("estudo_preco"), {"canal": c}))
    assert "Taxa de Cartão de crédito: R$ 0,20 (4,0%)" in t and "Sobra: R$ 3,56 (71,2% do preço)" in t


def test_estudo_com_taxa_nao_informada_nao_inventa_sobra(client, dono, bolinha_a_5):
    debito = CanalVenda.objects.get(nome="Cartão de débito").id
    t = limpo(client.get(reverse("estudo_preco"), {"canal": debito}))
    assert "A taxa de Cartão de débito não foi informada" in t
    assert "Taxa de Cartão de débito: não informada" in t and "Sobra: — (— do preço)" in t
    assert "taxa do canal não informada" in t
    assert "Sobra: R$ 0,00" not in t


def test_estudo_tabela_atacado_e_invalida(client, dono, bolinha_a_5):
    assert client.get(reverse("estudo_preco"), {"tabela": "atacado"}).status_code == 200
    assert client.get(reverse("estudo_preco"), {"tabela": "feira", "canal": "x"}).status_code == 200


def test_simulador_com_preco(client, dono, bolinha_a_5):
    r = client.get(reverse("estudo_preco"), {"acao": "preco", "apresentacao": bolinha_a_5["apr"], "preco": "4",
                                              "canal": bolinha_a_5["credito"]})
    t = limpo(r)
    assert "simulação" in t and "o preço da tabela não muda" in t
    assert "Preço: R$ 4,00" in t and "Sobra: R$ 2,60 (65,0% do preço)" in t
    assert reverse("precos") in r.content.decode()


def test_simulador_para_sobrar_percentual(client, dono, bolinha_a_5):
    t = limpo(client.get(reverse("estudo_preco"), {"acao": "sobra", "apresentacao": bolinha_a_5["apr"],
                                                    "sobra_pct": "50", "canal": bolinha_a_5["credito"]}))
    assert "para sobrar 50,0%" in t and "Preço que daria essa sobra: R$ 2,70" in t
    assert "Sobra: R$ 1,35 (50,0% do preço)" in t
    t = limpo(client.get(reverse("estudo_preco"), {"acao": "sobra", "apresentacao": bolinha_a_5["apr"],
                                                    "sobra_pct": "50"}))
    assert "Preço que daria essa sobra: R$ 2,48" in t  # balcão: 1,24 ÷ 0,5


def test_simulador_pedido_invalido_nao_quebra(client, dono, bolinha_a_5):
    apr = bolinha_a_5["apr"]
    for params, esperado in (
            ({"acao": "preco", "apresentacao": apr, "preco": ""}, "Informe o preço ou a sobra"),
            ({"acao": "preco", "apresentacao": apr, "preco": "abc"}, "número inválido"),
            ({"acao": "preco", "apresentacao": apr, "preco": "1.5"}, "vírgula"),
            ({"acao": "preco", "apresentacao": apr, "preco": "-3"}, "maior que zero"),
            ({"acao": "sobra", "apresentacao": apr, "sobra_pct": "100"}, "Não existe preço"),
            ({"acao": "preco", "apresentacao": "", "preco": "4"}, "Apresentação: escolha"),
            ({"acao": "preco", "apresentacao": "999", "preco": "4"}, "Apresentação não encontrada"),
            ({"acao": "lixo", "apresentacao": apr}, "Pedido desconhecido"),
            ({"acao": "preco", "apresentacao": apr, "preco": "4",
              "canal": CanalVenda.objects.get(nome="Cartão de débito").id}, "não foi informada")):
        r = client.get(reverse("estudo_preco"), params)
        assert r.status_code == 200 and esperado in limpo(r), params


def test_ponto_de_equilibrio_e_indireto_real(client, dono, bolinha_a_5):
    criar_mensal(client, "Energia", "Energia", valor_previsto="900")
    t = limpo(client.get(reverse("estudo_preco"), {"acao": "equilibrio", "apresentacao": bolinha_a_5["apr"]}))
    # contribuição no balcão: 5,00 − 0,50 = 4,50; 900 ÷ 4,50 = 200 vendas
    assert "cada venda deixa R$ 4,50" in t and "200 venda(s)" in t
    assert "Os indiretos por salgado estão certos?" in t and "Nenhuma produção concluída no mês" in t
    criar_mensal(client, "Internet", "Internet")
    t = limpo(client.get(reverse("estudo_preco"), {"acao": "equilibrio", "apresentacao": bolinha_a_5["apr"]}))
    assert "Internet sem valor neste mês" in t


# ---------- Hoje e menu ----------

def test_hoje_avisa_despesa_sem_valor_e_menu_nao_cresce(client, dono):
    criar_mensal(client, "Internet", "Internet")
    r = client.get(reverse("inicio"))
    t = limpo(r)
    assert "1 despesa(s) do mês sem valor" in t and "Internet" in t and "Informar o valor" in t
    assert t.count("Custos e relatórios") == 1
    assert 'href="/despesas/"' in r.content.decode()
    t = limpo(client.get(reverse("custos")))
    assert "Estudo de preço" in t and "Despesas" in t and "Óleo e indiretos de cada tamanho" in t
