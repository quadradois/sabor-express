import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from cadastros.servicos import criar_tamanho
from estoque.servicos import entrada_manual
from fichas.escala import escalar
from nucleo.operacoes import RegraViolada
from producao.models import Producao
from producao.servicos import iniciar_producao

from .forms import EntradaForm, ProducaoForm, ReceitaForm, TamanhoForm


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


@login_required
def producoes(request):
    return render(request, "web/producoes.html",
                  {"producoes": Producao.objects.filter(status="andamento").select_related("produto")})


@login_required
def producao(request, id):  # ponytail: mínima; a Task 10 substitui pela tela de preparo
    return render(request, "web/producao.html", {"p": get_object_or_404(Producao, id=id)})


@login_required
def producao_nova(request):
    ctx = {"tamanho_form": TamanhoForm(initial={"chave": uuid.uuid4().hex})}
    if request.method == "POST":
        form = ProducaoForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            try:
                r = iniciar_producao(produto_id=d["produto"].id, unidades=d["unidades"], forma=d["forma"],
                                     autor=request.user.username, canal="web", chave=d["chave"])
            except RegraViolada as e:
                form.add_error(None, str(e))
            else:
                return redirect("producao", id=r["producao_id"])
    else:
        form = ProducaoForm(request.GET or None)
        del form.fields["chave"]  # a chave só vale no POST
        ctx["chave"] = uuid.uuid4().hex
        if request.GET and form.is_valid():
            d = form.cleaned_data
            ctx["r"] = escalar(d["produto"].ficha, d["unidades"], d["produto"].peso_g)
    return render(request, "web/producao_nova.html", {**ctx, "form": form})


@login_required
def tamanho_novo(request):
    if request.method != "POST":
        return redirect("producao_nova")
    form = TamanhoForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            r = criar_tamanho(ficha_id=d["ficha"].id, peso_g=d["peso"], autor=request.user.username,
                              canal="web", chave=d["chave"])
        except RegraViolada as e:
            form.add_error(None, str(e))
        else:
            messages.success(request, f"Tamanho criado: {r['nome']}.")
            return redirect(f"{reverse('producao_nova')}?produto={r['item_id']}")
    return render(request, "web/producao_nova.html", {"form": ProducaoForm(initial={"chave": uuid.uuid4().hex}),
                                                      "tamanho_form": form})
