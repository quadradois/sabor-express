import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from estoque.servicos import entrada_manual
from fichas.escala import escalar
from nucleo.operacoes import RegraViolada

from .forms import EntradaForm, ReceitaForm


@login_required
def inicio(request):
    return render(request, "web/inicio.html")


@login_required
def receita(request):
    form = ReceitaForm(request.GET or None)
    ctx = {"form": form}
    if request.GET and form.is_valid():
        d = form.cleaned_data
        try:
            ctx["r"] = escalar(d["ficha"], d["unidades"], d["peso"])
        except RegraViolada as e:
            form.add_error(None, str(e))
    return render(request, "web/receita.html", ctx)


@login_required
def entrada(request):
    if request.method == "POST":
        form = EntradaForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            try:
                entrada_manual(item_id=d["item"].id, quantidade=d["quantidade"], unidade=d["unidade"].strip(),
                               custo_total=d["custo_total"], motivo=d["motivo"], lote_codigo=d["lote_codigo"],
                               validade=d["validade"], autor=request.user.username, canal="web",
                               chave=d["chave"])
            except RegraViolada as e:
                form.add_error(None, str(e))
            else:
                messages.success(request, "Entrada registrada.")
                return redirect("entrada")
    else:
        form = EntradaForm(initial={"chave": uuid.uuid4().hex})
    return render(request, "web/entrada.html", {"form": form})
