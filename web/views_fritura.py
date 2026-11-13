"""Telas de fritura, sobras e descarte (Plano 6, fase 2a). Só chamam serviços e consultas do núcleo."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from estoque.models import ESTADOS, Lote
from estoque.servicos import registrar_perda
from nucleo.operacoes import RegraViolada
from producao.fritura import registrar_fritura
from vendas import consultas as vc

from .templatetags.formato import dinheiro, quantidade
from .views_compras import _id, _kw, _volta


def _produtos_com_cru():
    vistos = {}
    for e in vc.estoque_para_venda():
        if e["forma"] == "cru" and e["livre"] > 0:
            vistos.setdefault(e["produto_id"], e["produto"])
    return sorted(vistos.items(), key=lambda kv: kv[1])


@login_required
def fritura(request):
    post = request.POST if request.method == "POST" else {}
    produto = request.GET.get("produto") or post.get("produto") or ""
    if request.method == "POST":
        try:
            kw = _kw(request)
            try:
                lote_id, estado = post.get("porcao", "").split("|")
            except ValueError:
                raise RegraViolada("Escolha o lote que vai para a fritura.") from None
            r = registrar_fritura(
                lote_id=_id(lote_id, "Lote"), estado=estado, quantidade=post.get("quantidade"),
                boas=post.get("boas"), estado_destino=post.get("estado_destino", "fresco"),
                perda_motivo=post.get("perda_motivo", ""), validade_manual=post.get("validade_manual") or None,
                justificativa=post.get("justificativa", ""),
                confirmar_perda_total=bool(post.get("confirmar_perda_total")), **kw)
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            txt = f"Fritura registrada: {r['boas']} boas e {r['perdas']} perdas de {r['produto']}."
            if int(r["boas"]):
                txt += f" Custo: {dinheiro(r['custo_unitario'])} por unidade."
            messages.success(request, txt)
            return redirect(f"{reverse('fritura')}?produto={produto}" if produto else "fritura")
    porcoes = vc.lotes_para_fritar(produto_id=int(produto)) if produto.isdigit() else []
    return render(request, "web/fritura.html", {
        "produtos": _produtos_com_cru(), "produto": produto, "porcoes": porcoes, "p": post,
        "estados": ESTADOS, "frituras": vc.frituras(de=timezone.localdate())})


@login_required
def sobras(request):
    if request.method == "POST":
        try:
            r = registrar_perda(lote_id=_id(request.POST.get("lote"), "Lote"), estado=request.POST.get("estado", ""),
                                quantidade=request.POST.get("quantidade"), motivo=request.POST.get("motivo", ""),
                                **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"Perda registrada: {quantidade(r['quantidade'], r['unidade_base'])} "
                                      f"de {r['item']} ({dinheiro(r['valor'])}).")
        return redirect("sobras")
    return render(request, "web/sobras.html", {"sobras": vc.sobras_fritas()})


@login_required
def descartar(request, id):
    """Descarte de porção (vencida, em geral): uma perda com motivo, na unidade base do item."""
    lote = get_object_or_404(Lote, id=id)
    if request.method == "POST":
        try:
            r = registrar_perda(lote_id=lote.id, estado=request.POST.get("estado", ""),
                                quantidade=request.POST.get("quantidade"), motivo=request.POST.get("motivo", ""),
                                **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"Descartado: {quantidade(r['quantidade'], r['unidade_base'])} de {r['item']} "
                                      f"({dinheiro(r['valor'])}).")
            if r["reservas_liberadas"]:
                messages.warning(request, "Havia reserva de encomenda nesse lote: complete a reserva com outro lote.")
    return _volta(request, reverse("lote", args=[lote.id]))
