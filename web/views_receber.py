"""Telas de contas a receber (Plano 6, fase 2a): quem deve, anotar recebimento e estornar.
Só chamam serviços e consultas do núcleo. O sistema nunca cobra: recebimento é anotação."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from financeiro import consultas as fc
from financeiro import servicos as fs
from nucleo.operacoes import RegraViolada

from .templatetags.formato import dinheiro
from .views_compras import _dec, _id, _kw, _volta


@login_required
def receber(request):
    hoje = timezone.localdate()
    cliente = request.GET.get("cliente", "")
    ctx = {"hoje": hoje, "devedores": fc.devido_por_cliente(), "cliente": cliente}
    if cliente.isdigit():
        em_aberto = fc.receber_em_aberto(cliente_id=int(cliente))
        ctx.update(filtrado=em_aberto, nome_cliente=em_aberto[0]["cliente"] if em_aberto else "",
                   recebimentos=fc.recebimentos(de=hoje - timedelta(days=90), cliente_id=int(cliente)))
    else:
        ctx.update(vencidas=fc.receber_vencidas(), a_vencer=fc.receber_a_vencer(dias=7),
                   recebimentos=fc.recebimentos(de=hoje - timedelta(days=30)))
    return render(request, "web/receber.html", ctx)


@login_required
def anotar_recebimento(request):
    if request.method != "POST":
        return redirect("receber")
    post = request.POST
    try:
        r = fs.registrar_recebimento(
            parcela_id=_id(post.get("parcela"), "Parcela"), valor=_dec(post.get("valor"), "Valor"),
            data_pagamento=post.get("data_pagamento") or None, forma=post.get("forma", ""),
            diferenca=_dec(post.get("diferenca"), "Diferença", 0), diferenca_tipo=post.get("diferenca_tipo", ""),
            diferenca_motivo=post.get("diferenca_motivo", ""), **_kw(request))
    except RegraViolada as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Recebimento anotado: {dinheiro(r['valor_pago'])}."
                         + (" Parcela quitada." if r["situacao"] == "paga" else f" Ainda falta {dinheiro(r['saldo'])}."))
    return _volta(request, reverse("receber"))


@login_required
def estornar_recebimento(request):
    if request.method != "POST":
        return redirect("receber")
    try:
        fs.estornar_recebimento_cliente(pagamento_id=_id(request.POST.get("pagamento"), "Recebimento"),
                                        motivo=request.POST.get("motivo", ""), **_kw(request))
    except RegraViolada as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Recebimento estornado.")
    return _volta(request, reverse("receber"))
