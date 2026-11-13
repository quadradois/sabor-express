"""Telas de fritura, sobras e descarte (Plano 6, fase 2a). Só chamam serviços e consultas do núcleo."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from estoque.models import DESTINOS_PERDA, ESTADOS, Lote
from estoque.servicos import livre_porcao, porcoes, registrar_perda
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


_FEITO = {"perda": "Perda registrada", "descarte": "Descarte registrado",
          "consumo_equipe": "Consumo da equipe registrado", "doacao": "Doação registrada"}


def _vencidas_cruas(produto_id):
    """Porções cruas vencidas com saldo livre: só vão para o óleo com um motivo (Plano 9)."""
    crus = Lote.objects.filter(item_id=produto_id, forma="cru").in_bulk()
    saida = []
    for p in porcoes(item=produto_id):
        lote = crus.get(p["lote_id"])
        if lote is not None and p["vencido"] and livre_porcao(lote, p["estado"]) > 0:
            saida.append({**p, "livre": livre_porcao(lote, p["estado"]), "custo_unitario": lote.custo_unitario})
    return saida


@login_required
def fritura(request):
    post = request.POST if request.method == "POST" else {}
    produto = request.GET.get("produto") or post.get("produto") or ""
    pede_motivo = False
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
                motivo_vencido=(post.get("motivo_vencido") or "").strip(),
                confirmar_perda_total=bool(post.get("confirmar_perda_total")), **kw)
        except RegraViolada as e:
            messages.error(request, str(e))
            pede_motivo = "motivo" in str(e).lower()
        else:
            txt = f"Fritura registrada: {r['boas']} boas e {r['perdas']} perdas de {r['produto']}."
            if int(r["boas"]):
                txt += f" Custo: {dinheiro(r['custo_unitario'])} por unidade."
            messages.success(request, txt)
            return redirect(f"{reverse('fritura')}?produto={produto}" if produto else "fritura")
    lista = vc.lotes_para_fritar(produto_id=int(produto)) if produto.isdigit() else []
    vencidas = _vencidas_cruas(int(produto)) if produto.isdigit() else []
    return render(request, "web/fritura.html", {
        "produtos": _produtos_com_cru(), "produto": produto, "porcoes": lista, "vencidas": vencidas,
        "pede_motivo": pede_motivo, "p": post,
        "estados": ESTADOS, "frituras": vc.frituras(de=timezone.localdate())})


@login_required
def sobras(request):
    if request.method == "POST":
        try:
            r = registrar_perda(lote_id=_id(request.POST.get("lote"), "Lote"), estado=request.POST.get("estado", ""),
                                quantidade=request.POST.get("quantidade"), motivo=request.POST.get("motivo", ""),
                                destino=request.POST.get("destino", "perda"), **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"{_FEITO[r['destino']]}: "
                                      f"{quantidade(r['quantidade'], r['unidade_base'])} de {r['item']} "
                                      f"({dinheiro(r['valor'])}).")
        return redirect("sobras")
    return render(request, "web/sobras.html", {"sobras": vc.sobras_fritas(), "destinos": DESTINOS_PERDA})


@login_required
def descartar(request, id):
    """Descarte de porção (vencida, em geral): uma perda com motivo, na unidade base do item."""
    lote = get_object_or_404(Lote, id=id)
    if request.method == "POST":
        try:
            r = registrar_perda(lote_id=lote.id, estado=request.POST.get("estado", ""),
                                quantidade=request.POST.get("quantidade"), motivo=request.POST.get("motivo", ""),
                                destino=request.POST.get("destino", "perda"), **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"{'Descartado' if r['destino'] == 'perda' else _FEITO[r['destino']]}: "
                                      f"{quantidade(r['quantidade'], r['unidade_base'])} de {r['item']} "
                                      f"({dinheiro(r['valor'])}).")
            if r["reservas_liberadas"]:
                messages.warning(request, "Havia reserva de encomenda nesse lote: complete a reserva com outro lote.")
    return _volta(request, reverse("lote", args=[lote.id]))
