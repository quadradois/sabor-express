"""Telas de custos, margens e relatórios (Plano 7, fase 2a). Só leitura: chamam as consultas de `custos` e
mostram o que elas devolvem. Toda margem é "estimada" e diz o que não inclui; valor desconhecido aparece como
"—" com o motivo, nunca como zero."""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from cadastros.models import Item
from custos import consultas as cc
from custos import fichas as cf
from custos.relatorios import relatorio_periodo
from nucleo.operacoes import RegraViolada

from .views_vendas import _dia

PERIODOS = {"hoje": "Hoje", "ontem": "Ontem", "semana": "Esta semana", "semana_passada": "Semana passada",
            "mes": "Este mês", "mes_passado": "Mês passado", "ultimos_7": "Últimos 7 dias",
            "ultimos_30": "Últimos 30 dias"}
AGRUPAMENTOS = {"produto": "Produto", "apresentacao": "Apresentação", "cliente": "Cliente", "tabela": "Tabela",
                "dia": "Dia"}
ORDENS = {"receita": "Receita", "unidades": "Unidades", "margem": "Margem"}


def _periodo(request, padrao):
    """Lê `periodo` ou `de`/`ate` da URL. Período inválido não quebra: avisa e usa o padrão.
    Devolve de, ate, o par do período anterior (None para datas livres: a consulta escolhe) e o rótulo."""
    g, hoje = request.GET, timezone.localdate()
    if g.get("de") or g.get("ate"):
        try:
            de, ate = _dia(g.get("de"), "De"), _dia(g.get("ate"), "Até")
            de, ate = de or ate, ate or hoje
            if ate < de:
                raise RegraViolada("O fim do período vem antes do início.")
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            return {"de": de, "ate": ate, "anterior": (None, None), "periodo": "",
                    "rotulo": f"{de:%d/%m/%Y} a {ate:%d/%m/%Y}"}
    periodo = g.get("periodo") or padrao
    if periodo not in PERIODOS:
        messages.error(request, f"Período desconhecido: {periodo}.")
        periodo = padrao
    de, ate = cc.intervalo(periodo, hoje=hoje)
    return {"de": de, "ate": ate, "anterior": cc.intervalo_anterior(periodo, hoje=hoje), "periodo": periodo,
            "rotulo": f"{PERIODOS[periodo]} ({de:%d/%m} a {ate:%d/%m})"}


def _opcao(g, nome, validos, padrao):
    v = g.get(nome) or padrao
    return v if v in validos else padrao


# ---------- custos dos produtos e das preparações ----------

@login_required
def custos(request):
    itens = Item.objects.filter(ativo=True).exclude(tipo="produto").order_by("nome")
    return render(request, "web/custos.html", {"produtos": cf.custos_estimados(), "itens": itens})


@login_required
def custo_produto(request, id):
    try:
        c = cf.custo_estimado(produto_id=id)
    except RegraViolada as e:
        if str(e) == "Produto não encontrado.":
            raise Http404 from None
        return render(request, "web/custo_produto.html", {"erro": str(e), "produto": Item.objects.get(id=id)})
    return render(request, "web/custo_produto.html", {"c": c, "tabela": cc.margem_apresentacoes(produto_id=id)})


@login_required
def custo_preparacao(request, id):
    try:
        c = cf.custo_preparacao(ficha_id=id)
    except RegraViolada as e:
        if str(e) == "Preparação não encontrada.":
            raise Http404 from None
        messages.error(request, str(e))
        c = None
    return render(request, "web/custo_preparacao.html", {"c": c})


@login_required
def evolucao_preco(request, id):
    try:
        de, ate = _dia(request.GET.get("de"), "De"), _dia(request.GET.get("ate"), "Até")
    except RegraViolada as e:
        messages.error(request, str(e))
        de = ate = None
    try:
        r = cc.evolucao_preco(item_id=id, de=de, ate=ate)
    except RegraViolada:
        raise Http404 from None
    return render(request, "web/evolucao_preco.html", {"r": r, "de": de, "ate": ate})


# ---------- margens, ranking ----------

@login_required
def margens(request):
    p = _periodo(request, "semana")
    agrupar = _opcao(request.GET, "agrupar", AGRUPAMENTOS, "produto")
    de_ant, ate_ant = p["anterior"]
    comp = cc.comparar_margens(de=p["de"], ate=p["ate"], de_anterior=de_ant, ate_anterior=ate_ant, agrupar=agrupar)
    detalhe = cc.margens(de=p["de"], ate=p["ate"], agrupar=agrupar)
    pontos = {g["chave"]: g for g in comp["grupos"]}
    grupos = [{**g, "pontos": pontos[g["chave"]]["pontos"], "margem_pct_anterior": pontos[g["chave"]]["margem_pct_anterior"]}
              for g in detalhe["grupos"]]
    return render(request, "web/margens.html", {
        "p": p, "agrupar": agrupar, "comp": comp, "grupos": grupos, "periodos": PERIODOS,
        "agrupamentos": AGRUPAMENTOS, "tabela": cc.margem_apresentacoes()})


@login_required
def ranking(request):
    p = _periodo(request, "mes")
    ordem = _opcao(request.GET, "ordem", ORDENS, "receita")
    return render(request, "web/ranking.html", {
        "p": p, "ordem": ordem, "r": cc.ranking_produtos(de=p["de"], ate=p["ate"], ordem=ordem),
        "periodos": PERIODOS, "ordens": ORDENS, "incl": cc.INCLUI_MARGEM, "nao": cc.NAO_INCLUI_MARGEM})


# ---------- previsto × realizado ----------

@login_required
def previsto_realizado(request):
    p = _periodo(request, "mes")
    produto = request.GET.get("produto", "")
    produto_id = int(produto) if produto.isdigit() else None
    return render(request, "web/previsto_realizado.html", {
        "p": p, "r": cc.previsto_realizado(de=p["de"], ate=p["ate"], produto_id=produto_id), "periodos": PERIODOS,
        "produtos": Item.objects.filter(tipo="produto", ativo=True).order_by("nome"), "produto": produto_id})


@login_required
def previsto_realizado_producao(request, id):
    r = cc.previsto_realizado_producao(id)
    if r is None:
        raise Http404
    return render(request, "web/previsto_producao.html", {"r": r})


# ---------- relatório do período ----------

@login_required
def relatorio(request):
    p = _periodo(request, "mes")
    return render(request, "web/relatorio.html", {
        "p": p, "r": relatorio_periodo(de=p["de"], ate=p["ate"]), "periodos": PERIODOS})
