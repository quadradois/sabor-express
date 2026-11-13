"""Telas de vendas: balcão, encomendas, necessidade de produção, clientes e preços (Plano 6, fase 2a).
Só chamam serviços e consultas do núcleo: totais, parcelas e "falta" vêm de lá."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Item
from cadastros.servicos import salvar_cliente
from estoque.models import ESTADOS, FORMAS
from financeiro import servicos as fs
from nucleo.operacoes import RegraViolada
from vendas import consultas as vc
from vendas import servicos as vs
from vendas.models import MODOS, TABELAS

from .templatetags.formato import dinheiro, quantidade
from .views_compras import _dec, _id, _kw, _volta

SITUACOES_ENCOMENDA = {"abertas": "Em aberto", "aberta": "Falta separar", "pronta": "Prontas", "entregue": "Entregues",
                       "cancelada": "Canceladas", "todas": "Todas"}


def _dia(txt, campo):
    txt = (txt or "").strip()
    if not txt:
        return None
    try:
        return date.fromisoformat(txt)
    except ValueError:
        raise RegraViolada(f"{campo}: data inválida.") from None


def _grade(apres, post):
    """As apresentações com o que foi digitado (quantidade e preço) para a grade de itens."""
    return [{**a, "qtd": post.get(f"qtd_{a['apresentacao_id']}", ""), "preco_digitado": post.get(f"preco_{a['apresentacao_id']}", "")}
            for a in apres]


def _itens_post(post, apres):
    itens = []
    for a in apres:
        i = a["apresentacao_id"]
        q = (post.get(f"qtd_{i}") or "").strip()
        if not q or q == "0":
            continue
        if not q.isdigit():
            raise RegraViolada(f"Quantidade de {a['produto']} ({a['nome']}): use um número inteiro.")
        item = {"apresentacao_id": i, "quantidade": int(q)}
        preco = _dec(post.get(f"preco_{i}"), f"Preço de {a['produto']} ({a['nome']})")
        if preco is not None:
            item["preco"] = preco
        itens.append(item)
    return itens


def _parcelas(post, total):
    try:
        n = int(post.get("parcelas_n") or 1)
        intervalo = int(post.get("intervalo") or 30)
    except ValueError:
        raise RegraViolada("Parcelas: informe números inteiros.") from None
    primeiro = _dia(post.get("primeiro_vencimento"), "Primeiro vencimento") or (
        timezone.localdate() + timedelta(days=intervalo))
    return fs.dividir_parcelas(total, n, primeiro, intervalo)


def _cliente_id(post):
    return _id(post["cliente"], "Cliente") if post.get("cliente") else None


# ---------- vender (balcão) ----------

@login_required
def vender(request):
    apres = vc.apresentacoes()
    post = request.POST if request.method == "POST" else {}
    if request.method == "POST":
        try:
            kw = _kw(request)
            itens = _itens_post(post, apres)
            tabela, condicao = post.get("tabela", "varejo"), post.get("condicao", "a_vista")
            parcelas = _parcelas(post, vc.total_dos_itens(itens=itens, tabela=tabela)) if condicao == "a_prazo" else None
            r = vs.registrar_venda(itens=itens, tabela=tabela, cliente_id=_cliente_id(post), condicao=condicao,
                                   forma_pagamento=post.get("forma_pagamento", ""), parcelas=parcelas, **kw)
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            a_prazo = " (a prazo, virou conta a receber)" if r["condicao"] == "a_prazo" else ""
            messages.success(request, f"Venda {r['venda_id']} registrada: {dinheiro(r['total'])}{a_prazo}.")
            return redirect("vendas")
    return render(request, "web/vender.html", {
        "grade": _grade(apres, post), "clientes": vc.clientes(), "p": post, "tabelas": TABELAS,
        "vendas_hoje": vc.vendas_do_dia()["totais"]})


@login_required
def vendas(request):
    hoje = timezone.localdate()
    g = request.GET
    try:
        de, ate = _dia(g.get("de"), "De"), _dia(g.get("ate"), "Até")
    except RegraViolada as e:
        messages.error(request, str(e))
        de = ate = hoje
    else:
        if "de" not in g and "ate" not in g:
            de = ate = hoje
    r = vc.vendas(de=de, ate=ate, incluir_canceladas=True)
    return render(request, "web/vendas.html", {"v": r["vendas"], "t": r["totais"], "de": de, "ate": ate,
                                               "next": request.get_full_path()})


@login_required
def cancelar_venda(request, id):
    if request.method != "POST":
        return redirect("vendas")
    try:
        r = vs.cancelar_venda(venda_id=id, motivo=request.POST.get("motivo", ""),
                              destino=request.POST.get("destino", "perda"), **_kw(request))
    except RegraViolada as e:
        messages.error(request, str(e))
    else:
        txt = f"Venda {id} cancelada."
        if r["destino"] == "estoque":
            txt += f" {quantidade(r['unidades_devolvidas'], 'un')} voltaram ao estoque."
        if Decimal(r["valor_devolvido"]):
            txt += f" Valor já pago, anotado como devolvido: {dinheiro(r['valor_devolvido'])}."
        messages.success(request, txt)
    return _volta(request, reverse("vendas"))


# ---------- encomendas ----------

@login_required
def encomendas(request):
    g = request.GET
    situacao = g.get("situacao", "abertas")
    if situacao not in SITUACOES_ENCOMENDA:
        situacao = "abertas"
    hoje = timezone.localdate()
    try:
        de, ate = _dia(g.get("de"), "De"), _dia(g.get("ate"), "Até")
    except RegraViolada as e:
        messages.error(request, str(e))
        de = ate = None
    if g.get("periodo") == "hoje":
        de = ate = hoje
    lista = (vc.encomendas_do_dia() if (situacao, de, ate) == ("abertas", hoje, hoje)
             else vc.encomendas(situacao=None if situacao == "todas" else situacao, de=de, ate=ate))
    return render(request, "web/encomendas.html", {
        "lista": lista, "situacao": situacao, "situacoes": SITUACOES_ENCOMENDA, "de": de, "ate": ate,
        "hoje": hoje, "periodo": g.get("periodo", "")})


@login_required
def encomenda_nova(request):
    apres = vc.apresentacoes()
    post = request.POST if request.method == "POST" else {}
    if request.method == "POST":
        try:
            kw = _kw(request)
            itens = _itens_post(post, apres)
            r = vs.criar_encomenda(
                cliente_id=_cliente_id(post), entrega_data=_dia(post.get("entrega_data"), "Dia"), itens=itens,
                entrega_hora=(post.get("entrega_hora") or "").strip() or None, tabela=post.get("tabela", "varejo"),
                modo=post.get("modo", "retirada"), observacao=post.get("observacao", ""),
                sinal=_dec(post.get("sinal"), "Sinal", 0), sinal_forma=post.get("sinal_forma", ""), **kw)
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            if Decimal(r["falta"]):
                messages.warning(request, f"Encomenda criada, mas faltam {quantidade(r['falta'], 'un')} para reservar. "
                                          "Veja o que falta produzir.")
            else:
                messages.success(request, "Encomenda criada e tudo já está reservado.")
            return redirect("encomenda", id=r["encomenda_id"])
    return render(request, "web/encomenda_nova.html", {
        "grade": _grade(apres, post), "clientes": vc.clientes(), "p": post, "tabelas": TABELAS, "modos": MODOS,
        "hoje": timezone.localdate()})


def _acao_encomenda(request, e):
    kw = _kw(request)
    post, acao = request.POST, request.POST.get("acao")
    if acao == "completar":
        r = vs.completar_reserva(encomenda_id=e["encomenda_id"], **kw)
        if Decimal(r["falta"]):
            messages.warning(request, f"Reserva completada até onde há estoque. Ainda faltam {quantidade(r['falta'], 'un')}.")
        else:
            messages.success(request, "Tudo reservado: a encomenda está pronta.")
    elif acao == "entregar":
        condicao = post.get("condicao", "a_vista")
        parcelas = _parcelas(post, e["saldo"]) if condicao == "a_prazo" and e["saldo"] > 0 else None
        r = vs.entregar_encomenda(encomenda_id=e["encomenda_id"], condicao=condicao,
                                  forma_pagamento=post.get("forma_pagamento", ""), parcelas=parcelas, **kw)
        messages.success(request, f"Encomenda entregue (venda {r['venda_id']}). Saldo: {dinheiro(r['saldo'])}.")
    elif acao == "cancelar":
        r = vs.cancelar_encomenda(encomenda_id=e["encomenda_id"], motivo=post.get("motivo", ""),
                                  devolver_sinal=bool(post.get("devolver_sinal")), **kw)
        messages.success(request, "Encomenda cancelada. As reservas foram liberadas."
                         + (f" Sinal devolvido: {dinheiro(r['sinal_devolvido'])}." if Decimal(r["sinal_devolvido"]) else ""))
    else:
        raise RegraViolada("Ação desconhecida.")


@login_required
def encomenda(request, id):
    e = vc.detalhe_encomenda(id)
    if e is None:
        raise Http404
    post = {}
    if request.method == "POST":
        try:
            _acao_encomenda(request, e)
        except RegraViolada as erro:
            messages.error(request, str(erro))
            post = request.POST
        else:
            return redirect("encomenda", id=id)
        e = vc.detalhe_encomenda(id)
    return render(request, "web/encomenda.html", {"e": e, "p": post})


# ---------- necessidade de produção ----------

@login_required
def necessidade(request):
    return render(request, "web/necessidade.html", {"linhas": vc.necessidade_producao()})


# ---------- clientes ----------

@login_required
def clientes(request):
    from financeiro.consultas import devido_por_cliente

    devido = {d["cliente_id"]: d for d in devido_por_cliente()}
    lista = [{**c, "divida": devido.get(c["cliente_id"])} for c in vc.clientes(ativos=False)]
    return render(request, "web/clientes.html", {"clientes": lista})


@login_required
def cliente_form(request, id=None):
    c = None
    if id is not None:
        c = next((x for x in vc.clientes(ativos=False) if x["cliente_id"] == id), None)
        if c is None:
            raise Http404
    if request.method == "POST":
        try:
            kw = _kw(request)
            acao = request.POST.get("acao")
            if acao in ("inativar", "reativar") and c:
                salvar_cliente(cliente_id=id, nome=c["nome"], contato=c["contato"], ativo=acao == "reativar", **kw)
                messages.success(request, "Cliente reativado." if acao == "reativar" else "Cliente inativado.")
            else:
                salvar_cliente(cliente_id=id, nome=request.POST.get("nome", ""),
                               contato=request.POST.get("contato", ""), ativo=c["ativo"] if c else True, **kw)
                messages.success(request, "Cliente salvo.")
            return redirect("clientes")
        except RegraViolada as e:
            messages.error(request, str(e))
        dados = request.POST
    else:
        dados = {"nome": c["nome"], "contato": c["contato"]} if c else {}
    return render(request, "web/cliente_form.html", {"c": c, "d": dados})


# ---------- preços (apresentações) ----------

@login_required
def precos(request):
    return render(request, "web/precos.html", {"lista": vc.apresentacoes(ativas=False)})


@login_required
def preco_form(request, id=None):
    a = None
    if id is not None:
        a = next((x for x in vc.apresentacoes(ativas=False) if x["apresentacao_id"] == id), None)
        if a is None:
            raise Http404
    if request.method == "POST":
        post = request.POST
        try:
            r = vs.salvar_apresentacao(
                apresentacao_id=id, produto_id=_id(post.get("produto"), "Produto"), nome=post.get("nome", ""),
                forma=post.get("forma", ""), estado=post.get("estado", ""),
                unidades=_id(post.get("unidades"), "Unidades"), preco_varejo=_dec(post.get("preco_varejo"), "Preço de varejo"),
                preco_atacado=_dec(post.get("preco_atacado"), "Preço de atacado"),
                embalagem_id=_id(post["embalagem"], "Embalagem") if post.get("embalagem") else None,
                embalagens=_dec(post.get("embalagens"), "Embalagens por apresentação", 0),
                ativo=bool(post.get("ativo")), **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"Preço salvo: {r['nome']}.")
            return redirect("precos")
        dados = post
    elif a:
        dados = {"produto": str(a["produto_id"]), "nome": a["nome"], "forma": a["forma"], "estado": a["estado"],
                 "unidades": a["unidades"], "preco_varejo": str(a["preco_varejo"]).replace(".", ","),
                 "preco_atacado": "" if a["preco_atacado"] is None else str(a["preco_atacado"]).replace(".", ","),
                 "embalagem": str(a["embalagem_id"] or ""), "embalagens": str(a["embalagens"]).replace(".", ","),
                 "ativo": "1" if a["ativo"] else ""}
    else:
        dados = {"ativo": "1", "unidades": 1, "forma": "cru", "estado": "congelado"}
    return render(request, "web/preco_form.html", {
        "a": a, "d": dados, "formas": FORMAS, "estados": ESTADOS,
        "produtos": Item.objects.filter(tipo="produto", ativo=True).order_by("nome"),
        "embalagens": Item.objects.filter(tipo="embalagem", ativo=True).order_by("nome")})
