"""Telas de despesas (Plano 8, fase 2a): o mês, lançar avulsa, despesas mensais, categorias, canais e taxas, e o
estudo de preço. Só chamam serviços e consultas do núcleo (que gravam por `executar` e dizem a regra violada).
Valor desconhecido ("sem valor", taxa não informada) aparece como tal, nunca como zero."""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from custos import precos as cp
from financeiro.models import Conta
from financeiro import consultas as fc
from financeiro import despesas as fd
from financeiro import servicos as fs
from nucleo.operacoes import RegraViolada
from vendas import servicos as vs

from .templatetags.formato import dinheiro
from .views_compras import _dec, _id, _kw, _volta

SITUACOES = {"paga": "Paga", "aberta": "A pagar", "parcial": "Paga em parte", "sem_valor": "Sem valor",
             "cancelada": "Cancelada"}


def _mes(txt):
    """`AAAA-MM` -> primeiro dia do mês; inválido não quebra (o chamador avisa)."""
    try:
        return date.fromisoformat((txt or "").strip() + "-01")
    except ValueError:
        return None


def _soma_mes(m, n):
    k = m.year * 12 + m.month - 1 + n
    return date(k // 12, k % 12 + 1, 1)


def _checado(post, campo):
    return post.get(campo) == "on"


# ---------- o mês ----------

@login_required
def despesas(request):
    hoje = timezone.localdate()
    comp = hoje.replace(day=1)
    if request.GET.get("mes"):
        m = _mes(request.GET["mes"])
        if m is None:
            messages.error(request, "Mês inválido: use o formato AAAA-MM.")
        else:
            comp = m
    fim = comp.replace(day=calendar.monthrange(comp.year, comp.month)[1])
    mes = fc.despesas_do_mes(competencia=comp, hoje=hoje)
    desp = fc.despesas_periodo(de=comp, ate=fim, hoje=hoje)
    itens = [{**d, "tipo": "mensal", "chave_id": d["despesa_do_mes_id"], "titulo": d["despesa"]}
             for d in mes["mensais"]]
    itens += [{**d, "tipo": "avulsa", "chave_id": d["conta_id"], "titulo": d["descricao"]} for d in mes["avulsas"]]
    motivos = dict(Conta.objects.filter(id__in=[d["conta_id"] for d in mes["mensais"] if d["situacao"] == "cancelada"])
                   .values_list("id", "motivo_cancelamento"))
    for d in itens:
        if d["tipo"] == "mensal" and d["situacao"] == "cancelada":
            d["motivo_cancelamento"] = motivos.get(d["conta_id"], "")
    itens.sort(key=lambda d: (d["vencimento"], d["titulo"]))
    return render(request, "web/despesas.html", {
        "comp": comp, "anterior": _soma_mes(comp, -1), "proximo": _soma_mes(comp, 1), "e_hoje": comp == hoje.replace(day=1),
        "mes": mes, "t": mes["totais"], "desp": desp, "hoje": hoje,
        "a_pagar": [d for d in itens if d["situacao"] in ("sem_valor", "aberta", "parcial")],
        "pagas": [d for d in itens if d["situacao"] == "paga"],
        "canceladas": [d for d in itens if d["situacao"] == "cancelada"]})


def _destino(request):
    return _volta(request, reverse("despesas"))


@login_required
def informar_valor(request):
    if request.method != "POST":
        return redirect("despesas")
    try:
        r = fd.informar_valor_despesa(despesa_do_mes_id=_id(request.POST.get("despesa"), "Despesa"),
                                      valor=_dec(request.POST.get("valor"), "Valor"), **_kw(request))
    except RegraViolada as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Valor anotado: {dinheiro(Decimal(r['valor']))}. Ainda não é pagamento.")
    return _destino(request)


@login_required
def pagar_despesa(request):
    """Anota o pagamento (com o valor real e a data) de uma despesa do mês ou de uma avulsa a pagar."""
    if request.method != "POST":
        return redirect("despesas")
    post = request.POST
    try:
        valor = _dec(post.get("valor"), "Valor")
        if post.get("tipo") == "avulsa":
            r = fs.registrar_pagamento(parcela_id=_id(post.get("parcela"), "Parcela"), valor=valor,
                                       data_pagamento=post.get("data_pagamento") or None, forma=post.get("forma", ""),
                                       **_kw(request))
        else:
            r = fd.pagar_despesa_do_mes(despesa_do_mes_id=_id(post.get("despesa"), "Despesa"), valor=valor,
                                        data_pagamento=post.get("data_pagamento") or None,
                                        forma=post.get("forma", ""), **_kw(request))
    except RegraViolada as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Pagamento anotado: {dinheiro(Decimal(str(r['valor_pago'])))}."
                         + (" Despesa quitada." if r["situacao"] == "paga"
                            else f" Ainda falta {dinheiro(Decimal(str(r['saldo'])))}."))
    return _destino(request)


@login_required
def cancelar_despesa(request):
    if request.method != "POST":
        return redirect("despesas")
    try:
        r = fd.cancelar_despesa(conta_id=_id(request.POST.get("conta"), "Despesa"),
                                motivo=request.POST.get("motivo", ""), **_kw(request))
    except RegraViolada as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Despesa cancelada."
                         + (" O pagamento anotado nela foi estornado." if r["pagamentos_estornados"] else ""))
    return _destino(request)


# ---------- lançar despesa avulsa ----------

@login_required
def despesa_nova(request):
    cats = fc.categorias_despesa()
    dados = {"paga": "sim"}
    if request.method == "POST":
        post = request.POST
        dados = post
        try:
            paga = post.get("paga", "sim") == "sim"
            r = fd.lancar_despesa(
                descricao=post.get("descricao", ""), categoria_id=_id(post.get("categoria"), "Categoria"),
                valor=_dec(post.get("valor"), "Valor"), paga=paga,
                data_pagamento=(post.get("data_pagamento") or None) if paga else None,
                vencimento=None if paga else (post.get("vencimento") or None), forma=post.get("forma", ""),
                **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"Despesa lançada: {dinheiro(Decimal(r['valor']))}, "
                             + ("já paga." if r["paga"] else f"a pagar até {date.fromisoformat(r['vencimento']):%d/%m/%Y}."))
            for p in r["parecidas"]:
                messages.warning(request, f"Atenção: {p['despesa']} (despesa mensal da mesma categoria) ainda está em "
                                 "aberto neste mês. Se for a mesma conta, cancele este lançamento e anote o pagamento nela.")
            return redirect(f"{reverse('despesas')}?mes={r['competencia'][:7]}")
    hoje = timezone.localdate()
    return render(request, "web/despesa_nova.html", {
        "categorias": cats, "d": dados, "data_pg": dados.get("data_pagamento") or hoje.isoformat()})


# ---------- despesas mensais (cadastro) ----------

@login_required
def despesas_mensais(request):
    return render(request, "web/despesas_mensais.html", {"lista": fc.despesas_mensais()})


@login_required
def despesa_mensal_form(request, id=None):
    atual = None
    if id is not None:
        atual = next((d for d in fc.despesas_mensais() if d["despesa_id"] == id), None)
        if atual is None:
            raise Http404
    if request.method == "POST":
        post = request.POST
        try:
            dia = post.get("dia_vencimento", "").strip() or "10"
            if not dia.isdigit():
                raise RegraViolada("O dia de vencimento vai de 1 a 31.")
            r = fd.salvar_despesa_mensal(
                nome=post.get("nome", ""), categoria_id=_id(post.get("categoria"), "Categoria"),
                dia_vencimento=int(dia), valor_previsto=_dec(post.get("valor_previsto"), "Valor previsto"),
                ativa=_checado(post, "ativa"), despesa_id=id, **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
            dados = post
        else:
            messages.success(request, "Despesa mensal salva."
                             + (" Já está nas despesas deste mês." if r.get("despesa_do_mes_gerada") else ""))
            return redirect("despesas_mensais")
    else:
        dados = ({"nome": atual["nome"], "categoria": str(atual["categoria_id"]), "dia_vencimento": atual["dia_vencimento"],
                  "valor_previsto": atual["valor_previsto"], "ativa": "on" if atual["ativa"] else ""}
                 if atual else {"dia_vencimento": 10, "ativa": "on"})
    return render(request, "web/despesa_mensal_form.html", {
        "d": dados, "atual": atual, "categorias": fc.categorias_despesa(ativas=False if atual else True)})


# ---------- categorias, canais e taxas ----------

@login_required
def categorias(request):
    if request.method == "POST":
        post = request.POST
        try:
            cid = post.get("categoria_id")
            fd.salvar_categoria_despesa(nome=post.get("nome", ""), indireta=_checado(post, "indireta"),
                                        ativa=_checado(post, "ativa") if cid else True,
                                        categoria_id=_id(cid, "Categoria") if cid else None, **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Categoria salva.")
        return redirect("categorias_despesa")
    return render(request, "web/categorias_despesa.html", {"lista": fc.categorias_despesa(ativas=False)})


@login_required
def canais(request):
    if request.method == "POST":
        post = request.POST
        try:
            cid = post.get("canal_id")
            vs.salvar_canal_venda(nome=post.get("nome", ""), taxa_pct=_dec(post.get("taxa_pct"), "Taxa"),
                                  ativo=_checado(post, "ativo") if cid else True,
                                  canal_id=_id(cid, "Canal") if cid else None, **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Canal salvo.")
        return redirect("canais_venda")
    return render(request, "web/canais_venda.html", {"lista": cp.canais_venda(ativos=False)})


# ---------- estudo de preço ----------

@login_required
def estudo_de_preco(request):
    g = request.GET
    tabela = g.get("tabela") if g.get("tabela") in cp.TABELAS else "varejo"
    estudo = cp.estudo_preco(tabela=tabela)
    canais = estudo["canais"]
    canal_id = int(g["canal"]) if (g.get("canal") or "").isdigit() else None
    canal = next((c for c in canais if c["canal_id"] == canal_id), canais[0] if canais else None)
    canal_id = canal["canal_id"] if canal else None
    linhas = []
    for a in estudo["apresentacoes"]:
        pc = next((x for x in a["por_canal"] if x["canal_id"] == canal_id), None)
        linhas.append({**a, "pc": pc})
    ctx = {"tabela": tabela, "estudo": estudo, "canais": canais, "canal": canal, "linhas": linhas,
           "tabelas": {"varejo": "Varejo", "atacado": "Atacado"}, "g": g}
    acao = g.get("acao", "")
    if acao:
        ctx.update(_simulacao(request, acao, tabela, canal_id))
    hoje = timezone.localdate()
    try:
        ctx["real"] = cp.indireto_real(hoje=hoje)
    except RegraViolada as e:
        messages.error(request, str(e))
    return render(request, "web/estudo_preco.html", ctx)


def _simulacao(request, acao, tabela, canal_id):
    """Roda a simulação (ou o ponto de equilíbrio) pedida na URL. Erro de regra vira mensagem, não 500."""
    g = request.GET
    saida = {"acao": acao}
    try:
        apr = _id(g.get("apresentacao"), "Apresentação")
        if acao == "preco":
            saida["sim"] = cp.simular_preco(apresentacao_id=apr, preco=_dec(g.get("preco"), "Preço"), canal_id=canal_id,
                                            tabela=tabela)
        elif acao == "sobra":
            saida["sim"] = cp.simular_preco(apresentacao_id=apr, sobra_pct=_dec(g.get("sobra_pct"), "Sobra"),
                                            canal_id=canal_id, tabela=tabela)
        elif acao == "equilibrio":
            saida["eq"] = cp.ponto_equilibrio(apresentacao_id=apr, canal_id=canal_id, tabela=tabela)
        else:
            raise RegraViolada("Pedido desconhecido.")
    except RegraViolada as e:
        messages.error(request, str(e))
    return saida
