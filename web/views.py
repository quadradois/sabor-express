import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from cadastros.servicos import criar_tamanho
from estoque.etiquetas import dados_etiqueta, registrar_impressao
from estoque.models import ESTADOS, Lote, Movimento
from estoque.servicos import entrada_manual, porcoes, saldo_lote, transferir_estado
from fichas.escala import escalar
from nucleo.operacoes import RegraViolada
from producao.models import Producao
from producao.servicos import (origem, cancelar_producao, concluir_producao, iniciar_cronometro, iniciar_producao,
                               ir_para_etapa, parar_cronometro, registrar_peso, usar_previsto_restantes)

from .forms import ConclusaoForm, EntradaForm, PesoForm, ProducaoForm, ReceitaForm, TamanhoForm, TransferenciaForm


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


def _validado(form):
    if not form.is_valid():
        campo, erros = next(iter(form.errors.items()))
        raise RegraViolada(f"{form[campo].label}: {erros[0]}" if campo in form.fields else erros[0])
    return form.cleaned_data


def _acao_preparo(request, p):
    kw = {"autor": request.user.username, "canal": "web", "chave": request.POST.get("chave")}
    if not kw["chave"]:
        raise RegraViolada("Formulário sem chave: recarregue a página e tente de novo.")
    acao = request.POST.get("acao")
    if acao == "peso":
        linha = get_object_or_404(p.linhas, id=request.POST.get("linha"))
        registrar_peso(linha_id=linha.id, usado=_validado(PesoForm(request.POST))["usado"], **kw)
    elif acao == "previsto":
        registrar_peso(linha_id=get_object_or_404(p.linhas, id=request.POST.get("linha")).id, usado=None, **kw)
    elif acao == "previsto_todos":
        usar_previsto_restantes(producao_id=p.id, **kw)
    elif acao == "etapa":
        try:
            indice = int(request.POST.get("indice"))
        except (TypeError, ValueError):
            raise RegraViolada("Etapa inexistente.")
        ir_para_etapa(producao_id=p.id, indice=indice, **kw)
    elif acao == "cronometro":
        e = p.etapas[p.etapa_atual - 1] if 1 <= p.etapa_atual <= len(p.etapas) else {}
        if not e.get("tempo_seg"):
            raise RegraViolada("Esta etapa não tem tempo.")
        iniciar_cronometro(producao_id=p.id, nome=e["instrucao"][:120], segundos=e["tempo_seg"], **kw)
    elif acao == "parar":
        parar_cronometro(cronometro_id=get_object_or_404(p.cronometros, id=request.POST.get("cronometro")).id, **kw)
    elif acao == "cancelar":
        cancelar_producao(producao_id=p.id, motivo=request.POST.get("motivo", ""), **kw)
    elif acao == "concluir":
        r = concluir_producao(producao_id=p.id, **_validado(ConclusaoForm(request.POST)), **kw)
        for pend in r.get("pendentes", []):
            messages.warning(request, f"Consumo pendente de {pend['item']}: concilie quando a compra chegar.")
    else:
        raise RegraViolada("Ação desconhecida.")


@login_required
def producao(request, id):
    p = get_object_or_404(Producao.objects.select_related("produto", "lote"), id=id)
    if request.method == "POST":
        try:
            _acao_preparo(request, p)
        except RegraViolada as e:
            messages.error(request, str(e))
            if "motivo" in str(e).lower() and request.POST.get("acao") == "concluir":
                return redirect(f"{reverse('producao', args=[p.id])}?motivo=1")  # reabre com o campo do motivo
        return redirect("producao", id=p.id)
    ctx = {"p": p, "linhas": p.linhas.select_related("item"), "n": len(p.etapas),
           "cronometros": p.cronometros.filter(parado_em__isnull=True).order_by("fim")}
    if p.lote_id:
        ctx["estado_inicial"] = Movimento.objects.filter(lote_id=p.lote_id, tipo="entrada_producao").values_list("estado", flat=True).first()
    if 1 <= p.etapa_atual <= len(p.etapas):
        ctx["etapa"] = e = p.etapas[p.etapa_atual - 1]
        ctx["video"] = e["midia"].lower().endswith((".mp4", ".webm", ".mov"))
    elif p.etapa_atual == p.fechamento:
        ctx["form"] = ConclusaoForm(initial={"quantidade_boa": p.unidades})
        if not request.GET.get("motivo"):  # o motivo do vencido só aparece quando o sistema pediu
            del ctx["form"].fields["motivo_vencido"]
    return render(request, "web/producao.html", ctx)


@login_required
def producao_nova(request):
    ctx = {"tamanho_form": TamanhoForm(initial={"chave": uuid.uuid4().hex})}
    if request.method == "POST":
        form = ProducaoForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            try:
                r = iniciar_producao(produto_id=d["produto"].id, unidades=d["unidades"], forma=d["forma"],
                                     pendente_justificativa=d["pendente_justificativa"],
                                     autor=request.user.username, canal="web", chave=d["chave"])
            except RegraViolada as e:
                form.add_error(None, str(e))
            else:
                return redirect("producao", id=r["producao_id"])
    else:
        form = ProducaoForm(request.GET or None)
        del form.fields["chave"], form.fields["pendente_justificativa"]  # só valem no POST
        ctx["chave"] = uuid.uuid4().hex
        if request.GET and form.is_valid():
            d = form.cleaned_data
            ctx["r"] = escalar(d["produto"].ficha, d["unidades"], d["produto"].peso_g)
            ctx["falta"] = any(l.falta > 0 for b in ctx["r"].blocos for l in b.linhas)
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


@login_required
def lote(request, id):
    l = get_object_or_404(Lote.objects.select_related("item"), id=id)
    pede_motivo = False
    if request.method == "POST":
        form = TransferenciaForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            try:
                transferir_estado(lote_id=l.id, quantidade=d["quantidade"], de=d["de"], para=d["para"],
                                  validade_manual=d["validade_manual"], justificativa=d["justificativa"],
                                  motivo_vencido=(d["motivo_vencido"] or "").strip(),
                                  autor=request.user.username, canal="web", chave=d["chave"])
            except RegraViolada as e:
                form.add_error(None, str(e))
                pede_motivo = "motivo" in str(e).lower()
            else:
                messages.success(request, "Conservação alterada.")
                return redirect("lote", id=l.id)
    else:
        form = TransferenciaForm()
    if not (pede_motivo or form.data.get("motivo_vencido")):  # o motivo do vencido só aparece quando pedido
        del form.fields["motivo_vencido"]
    estados = [dados_etiqueta(l, e) | {"estado": e} for e, _ in ESTADOS if saldo_lote(l, e) != 0]
    vencidos = {p["estado"] for p in porcoes(item=l.item_id) if p["lote_id"] == l.id and p["vencido"]}
    return render(request, "web/lote.html", {"l": l, "estados": estados, "origem": origem(l), "form": form,
                                             "vencidos": vencidos})


COPIAS_MAX = 200  # uma página com milhares de etiquetas trava o navegador e a impressora


@login_required
def etiquetas(request, id):
    l = get_object_or_404(Lote.objects.select_related("item"), id=id)
    estado = request.GET.get("estado", "")
    if estado not in dict(ESTADOS):
        raise Http404
    dados = dados_etiqueta(l, estado)
    try:
        copias = int(request.POST.get("copias") or request.GET.get("copias") or dados["quantidade"])
    except ValueError:
        copias = 1
    copias = min(max(copias, 1), COPIAS_MAX)
    if request.method == "POST":
        try:
            r = registrar_impressao(lote_id=l.id, estado=estado, copias=copias, autor=request.user.username,
                                    canal="web", chave=request.POST.get("chave"))
        except RegraViolada as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Reimpressão registrada." if r["reimpressao"] else "Impressão registrada.")
            return redirect("lote", id=l.id)
    return render(request, "web/etiquetas.html", {"l": l, "e": dados, "estado": estado, "copias": copias,
                                                  "range": range(max(copias, 0))})
