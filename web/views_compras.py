"""Telas de compras, recebimento, contas a pagar e pendências. Só chamam serviços e consultas do núcleo."""
import re
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from cadastros.models import Conversao, Fornecedor, Item
from cadastros.servicos import salvar_fornecedor
from compras import consultas as cc
from compras import servicos as cs
from estoque.servicos import consumos_pendentes
from financeiro import consultas as fc
from financeiro import servicos as fs
from nucleo.operacoes import RegraViolada
from producao.servicos import conciliar_consumo

LINHAS_NOVA_COMPRA = 8


def _kw(request):
    chave = request.POST.get("chave")
    if not chave:
        raise RegraViolada("Formulário sem chave: recarregue a página e tente de novo.")
    return {"autor": request.user.username, "canal": "web", "chave": chave}


def _dec(txt, campo, padrao=None):
    txt = (txt or "").strip()
    if not txt:
        return padrao
    if "." in txt:
        raise RegraViolada(f"{campo}: use vírgula para decimais (ex.: 1,5).")
    try:
        return Decimal(txt.replace(",", "."))
    except InvalidOperation:
        raise RegraViolada(f"{campo}: número inválido.")


def _data(txt, campo, padrao=None):
    return (txt or "").strip() or padrao


def _id(txt, campo):
    try:
        return int(txt)
    except (TypeError, ValueError):
        raise RegraViolada(f"{campo}: escolha uma opção.")


def _volta(request, padrao):
    destino = request.POST.get("next", "")
    return redirect(destino if url_has_allowed_host_and_scheme(destino, allowed_hosts=None) and destino else padrao)


def _unidades():
    return sorted({u for u in Conversao.objects.values_list("unidade", flat=True)} | {"g", "kg", "mL", "L", "un"})


# ---------- fornecedores ----------

@login_required
def fornecedores(request):
    return render(request, "web/fornecedores.html", {"fornecedores": Fornecedor.objects.order_by("-ativo", "nome")})


@login_required
def fornecedor_form(request, id=None):
    f = None
    if id is not None:
        f = Fornecedor.objects.filter(id=id).first()
        if f is None:
            raise Http404
    if request.method == "POST":
        try:
            kw = _kw(request)
            acao = request.POST.get("acao")
            if acao in ("inativar", "reativar") and f:
                salvar_fornecedor(fornecedor_id=f.id, nome=f.nome, documento=f.documento, contato=f.contato,
                                  ativo=acao == "reativar", **kw)
                messages.success(request, "Fornecedor reativado." if acao == "reativar" else "Fornecedor inativado.")
            else:
                salvar_fornecedor(fornecedor_id=f.id if f else None, nome=request.POST.get("nome", ""),
                                  documento=request.POST.get("documento", ""), contato=request.POST.get("contato", ""),
                                  ativo=True if not f else f.ativo, **kw)
                messages.success(request, "Fornecedor salvo.")
            return redirect("fornecedores")
        except RegraViolada as e:
            messages.error(request, str(e))
        dados = request.POST
    else:
        dados = {"nome": f.nome, "documento": f.documento, "contato": f.contato} if f else {}
    return render(request, "web/fornecedor_form.html", {"f": f, "d": dados})


# ---------- compras ----------

def _linhas_post(post):
    return [{"item": post.get(f"item_{i}", ""), "quantidade": post.get(f"quantidade_{i}", ""),
             "unidade": post.get(f"unidade_{i}", ""), "valor": post.get(f"valor_{i}", "")}
            for i in range(LINHAS_NOVA_COMPRA)]


def _montar_compra(post):
    hoje = timezone.localdate()
    linhas = []
    for l in _linhas_post(post):
        if not any(l.values()):
            continue
        linhas.append({"item_id": _id(l["item"], "Item"), "quantidade": _dec(l["quantidade"], "Quantidade"),
                       "unidade": l["unidade"].strip(), "valor": _dec(l["valor"], "Valor da linha")})
    if not linhas:
        raise RegraViolada("Informe ao menos um item da compra.")
    total = _dec(post.get("total"), "Total")
    d = {"fornecedor_id": _id(post.get("fornecedor"), "Fornecedor"), "data_compra": _data(post.get("data"), "Data", hoje),
         "linhas": linhas, "total": total, "condicao": post.get("condicao", "a_vista"),
         "frete": _dec(post.get("frete"), "Frete", 0), "desconto": _dec(post.get("desconto"), "Desconto", 0),
         "acrescimo": _dec(post.get("acrescimo"), "Acréscimo", 0), "documento": post.get("documento", "").strip(),
         "justificativa": post.get("justificativa", "")}
    if d["condicao"] == "a_prazo":
        try:
            n = int(post.get("parcelas_n") or 1)
            intervalo = int(post.get("intervalo") or 30)
        except ValueError:
            raise RegraViolada("Parcelas: informe números inteiros.")
        primeiro = _data(post.get("primeiro_vencimento"), "Primeiro vencimento", hoje + timedelta(days=intervalo))
        if total is None:
            raise RegraViolada("Informe o total da compra.")
        d["parcelas"] = fs.dividir_parcelas(total, n, primeiro, intervalo)
    else:
        d["data_pagamento"] = _data(post.get("data_pagamento"), "Data do pagamento", hoje)
        d["forma_pagamento"] = post.get("forma_pagamento", "")
    return d


def _receber_tudo(compra_id, validade, kw):
    det = cc.detalhe_compra(compra_id)
    linhas = [{"linha_id": l["linha_id"], "quantidade": l["quantidade"], "unidade": l["unidade"],
               "validade": validade or None} for l in det["linhas"]]
    return cs.receber_compra(compra_id=compra_id, linhas=linhas, autor=kw["autor"], canal=kw["canal"],
                             chave=f"{kw['chave']}-recebi")


@login_required
def compra_nova(request):
    ctx = {"fornecedores": Fornecedor.objects.filter(ativo=True).order_by("nome"),
           "itens": Item.objects.filter(ativo=True).exclude(tipo="produto").order_by("nome"),
           "unidades": _unidades(), "hoje": timezone.localdate()}
    if request.method == "POST":
        post = request.POST
        try:
            kw = _kw(request)
            d = _montar_compra(post)
            if not post.get("ciente") and d["total"] is not None:
                dup = cc.possiveis_duplicatas(fornecedor_id=d["fornecedor_id"], data_compra=d["data_compra"],
                                              total=d["total"], documento=d["documento"])
                if dup:
                    ctx["duplicatas"] = dup
                    raise RegraViolada("Já existe compra parecida. Confira abaixo e marque \"lançar mesmo assim\" se for outra.")
            r = cs.registrar_compra(**d, **kw)
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            for a in r["alertas"]:
                messages.warning(request, a)
            messages.success(request, "Compra lançada.")
            if post.get("recebi_tudo"):
                try:
                    _receber_tudo(r["compra_id"], post.get("validade_tudo"), kw)
                    messages.success(request, "Tudo recebido no estoque.")
                except RegraViolada as e:
                    messages.error(request, f"A compra foi lançada, mas o recebimento foi recusado: {e}")
            return redirect("compra", id=r["compra_id"])
        ctx.update(p=post, linhas=_linhas_post(post), chave=uuid.uuid4().hex)
    else:
        ctx.update(p={}, linhas=_linhas_post({}), chave=uuid.uuid4().hex)
    return render(request, "web/compra_nova.html", ctx)


def _acao_compra(request, c):
    kw = _kw(request)
    acao = request.POST.get("acao")
    post = request.POST
    if acao == "receber":
        linhas = []
        for l in c["linhas"]:
            q = _dec(post.get(f"quantidade_{l['linha_id']}"), f"Quantidade de {l['item']}")
            if q is None or q == 0:
                continue
            linhas.append({"linha_id": l["linha_id"], "quantidade": q, "unidade": l["unidade"],
                           "lote_codigo": post.get(f"lote_{l['linha_id']}", ""),
                           "validade": post.get(f"validade_{l['linha_id']}") or None})
        if not linhas:
            raise RegraViolada("Informe a quantidade recebida de ao menos um item.")
        r = cs.receber_compra(compra_id=c["compra_id"], linhas=linhas, **kw)
        messages.success(request, "Recebimento registrado.")
        for p in r["conciliaveis"]:
            messages.warning(request, f"Havia consumo pendente de {p['item']}: concilie em Consumos pendentes.")
    elif acao == "encerrar":
        ids = [int(i) for i in post.getlist("linha_ids")] or None
        cs.encerrar_pendencia(compra_id=c["compra_id"], motivo=post.get("motivo", ""), linha_ids=ids, **kw)
        messages.success(request, "Pendência encerrada. Um aviso de ajuste foi criado sobre a conta.")
    elif acao == "reabrir":
        cs.reabrir_pendencia(compra_id=c["compra_id"], motivo=post.get("motivo", ""), **kw)
        messages.success(request, "Pendência reaberta. Agora registre o recebimento do que chegou.")
    elif acao == "estornar_recebimento":
        cs.estornar_recebimento(recebimento_id=_id(post.get("recebimento_id"), "Recebimento"),
                                motivo=post.get("motivo", ""), **kw)
        messages.success(request, "Recebimento estornado.")
    elif acao == "devolver":
        r = cs.devolver_ao_fornecedor(lote_id=_id(post.get("lote_id"), "Lote"),
                                      quantidade=_dec(post.get("quantidade"), "Quantidade"),
                                      unidade=post.get("unidade") or None, motivo=post.get("motivo", ""), **kw)
        messages.success(request, "Devolução registrada. Um aviso de ajuste foi criado sobre a conta.")
    elif acao == "cancelar":
        cs.cancelar_compra(compra_id=c["compra_id"], motivo=post.get("motivo", ""), **kw)
        messages.success(request, "Compra cancelada.")
    else:
        raise RegraViolada("Ação desconhecida.")


@login_required
def compra(request, id):
    c = cc.detalhe_compra(id)
    if c is None:
        raise Http404
    if request.method == "POST":
        try:
            _acao_compra(request, c)
        except RegraViolada as e:
            messages.error(request, str(e))
        return redirect("compra", id=id)
    return render(request, "web/compra.html", {"c": c, "aberta": c["status"] in cc.ABERTAS,
                                               "encerrado": c["status"] != "cancelada"
                                               and any(l["encerrado"] > 0 for l in c["linhas"])})


@login_required
def compras_abertas(request):
    return render(request, "web/compras.html", {"compras": cc.compras_em_aberto()})


@login_required
def falta_receber(request):
    return render(request, "web/falta_receber.html", {"linhas": cc.falta_receber()})


@login_required
def bonificacao(request):
    ctx = {"itens": Item.objects.filter(ativo=True).exclude(tipo="produto").order_by("nome"), "unidades": _unidades()}
    if request.method == "POST":
        post = request.POST
        try:
            r = cs.receber_bonificacao(
                item_id=_id(post.get("item"), "Item"), quantidade=_dec(post.get("quantidade"), "Quantidade"),
                unidade=post.get("unidade", "").strip(), motivo=post.get("motivo", ""),
                lote_codigo=post.get("lote_codigo", ""), validade=post.get("validade") or None,
                compra_id=int(post["compra_id"]) if post.get("compra_id", "").isdigit() else None, **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Bonificação recebida no estoque.")
            for p in r["conciliaveis"]:
                messages.warning(request, f"Havia consumo pendente de {p['item']}: concilie em Consumos pendentes.")
            return redirect("bonificacao")
    return render(request, "web/bonificacao.html", ctx)


# ---------- contas a pagar ----------

@login_required
def contas(request):
    hoje = timezone.localdate()
    return render(request, "web/contas.html", {
        "vencidas": fc.contas_vencidas(), "a_vencer": fc.contas_a_vencer(dias=7),
        "fornecedores": fc.devido_por_fornecedor(),
        "pagamentos": fc.pagamentos(de=hoje - timedelta(days=30)), "hoje": hoje})


@login_required
def pagar(request):
    if request.method != "POST":
        return redirect("contas")
    post = request.POST
    try:
        valor = _dec(post.get("valor"), "Valor")
        r = fs.registrar_pagamento(
            parcela_id=_id(post.get("parcela"), "Parcela"), valor=valor,
            data_pagamento=post.get("data_pagamento") or None, forma=post.get("forma", ""),
            diferenca=_dec(post.get("diferenca"), "Diferença", 0), diferenca_tipo=post.get("diferenca_tipo", ""),
            diferenca_motivo=post.get("diferenca_motivo", ""), **_kw(request))
    except RegraViolada as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Pagamento registrado." + (" Parcela quitada." if r["situacao"] == "paga" else ""))
    return _volta(request, reverse("contas"))


@login_required
def estornar_pagamento(request):
    if request.method != "POST":
        return redirect("contas")
    try:
        fs.estornar_pagamento(pagamento_id=_id(request.POST.get("pagamento"), "Pagamento"),
                              motivo=request.POST.get("motivo", ""), **_kw(request))
    except RegraViolada as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Pagamento estornado.")
    return _volta(request, reverse("contas"))


@login_required
def avisos(request):
    if request.method == "POST":
        try:
            fs.resolver_aviso(aviso_id=_id(request.POST.get("aviso"), "Aviso"),
                              observacao=request.POST.get("observacao", ""), **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Aviso resolvido.")
        return redirect("avisos")
    return render(request, "web/avisos.html", {"avisos": fc.avisos_de_ajuste()})


@login_required
def consumos(request):
    if request.method == "POST":
        try:
            r = conciliar_consumo(pendente_id=_id(request.POST.get("pendente"), "Consumo"),
                                  lote_id=_id(request.POST.get("lote"), "Lote"), **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Consumo conciliado com o lote.")
        return redirect("consumos")
    return render(request, "web/consumos.html", {"pendentes": consumos_pendentes()})
