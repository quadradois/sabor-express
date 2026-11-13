"""Telas de lote do Plano 9: contar o lote ("o sistema diz 18, mas só tinha 15"). A conferência do vencido
mora na caixa de decisões (`views_decisoes`) e usa estas mesmas telas e serviços."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from estoque.models import ESTADOS, Lote
from estoque.servicos import ajustar_contagem, livre_porcao, porcoes, saldo_lote, validade_porcao
from nucleo.operacoes import RegraViolada

from .templatetags.formato import dinheiro, quantidade
from .views_compras import _dec, _kw


def _porcoes_do_lote(lote):
    """O que o sistema diz que há no lote, por conservação. Lote zerado: todas as conservações com zero
    (dá para contar e achar o que o sistema não sabia)."""
    rotulos = dict(ESTADOS)
    achadas = [p for p in porcoes(item=lote.item_id) if p["lote_id"] == lote.id]
    if achadas:
        return [{**p, "conservacao": rotulos.get(p["estado"], p["estado"]), "reservado": p["saldo"] - livre_porcao(lote, p["estado"])}
                for p in achadas]
    return [{"estado": e, "conservacao": nome, "saldo": saldo_lote(lote, e), "validade": validade_porcao(lote, e),
             "vencido": False, "reservado": Decimal("0")} for e, nome in ESTADOS]


def _next(valor, padrao):
    return valor if valor and url_has_allowed_host_and_scheme(valor, allowed_hosts=None) else padrao


@login_required
def contar(request, id):
    lote = get_object_or_404(Lote.objects.select_related("item"), id=id)
    voltar = reverse("lote", args=[lote.id])
    fonte = request.POST if request.method == "POST" else request.GET
    proximo = _next(fonte.get("next", ""), "")
    if request.method == "POST":
        try:
            contado = _dec(request.POST.get("contado"), "Quanto há de fato")
            if contado is None:
                raise RegraViolada("Informe quanto há de fato no lote (pode ser zero).")
            r = ajustar_contagem(lote_id=lote.id, estado=request.POST.get("estado", ""), contado=contado,
                                 motivo=request.POST.get("motivo", ""), **_kw(request))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            un, dif = r["unidade_base"], Decimal(r["diferenca"])
            if dif == 0:
                messages.success(request, f"Contagem de {r['item']}: o sistema já dizia {quantidade(r['antes'], un)}. "
                                          "Nada a ajustar (a contagem ficou registrada).")
            else:
                sinal = "+" if dif > 0 else "-"
                messages.success(request, (
                    f"Contagem de {r['item']}: o sistema dizia {quantidade(r['antes'], un)}, você contou "
                    f"{quantidade(r['contado'], un)}; diferença de {sinal}{quantidade(abs(dif), un)} "
                    f"({'+' if dif > 0 else '-'}{dinheiro(abs(Decimal(r['valor'])))})."))
            if r["reservas_liberadas"]:
                messages.warning(request, "Havia reserva de encomenda além do que foi contado: ela foi liberada. "
                                          "Complete a reserva com outro lote.")
            return redirect(proximo or voltar)
    return render(request, "web/contar.html", {
        "l": lote, "porcoes": _porcoes_do_lote(lote), "estado": fonte.get("estado", ""), "next": proximo,
        "p": request.POST if request.method == "POST" else {}, "voltar": voltar})
