"""API de consulta para o agente de voz (EscofIA). Só leitura.

Todas as rotas exigem `Authorization: Bearer <SABOR_AGENTE_TOKEN>`. Sem o token
configurado no servidor a API fica desligada (503). As quantidades vão em dois
formatos: número na unidade base e texto pronto para falar ("1,2 kg").
"""

import hmac
import unicodedata
from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.db.models import Min, Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from cadastros.models import Item
from estoque.models import Lote, Movimento
from estoque.servicos import saldo
from fichas.escala import escalar
from nucleo.operacoes import RegraViolada
from producao.models import Producao
from web.templatetags.formato import quantidade as fmt_qtd


def _erro(msg, status):
    return JsonResponse({"erro": msg}, status=status)


def com_token(view):
    @require_GET
    @wraps(view)
    def _view(request, *args, **kwargs):
        esperado = settings.AGENTE_TOKEN
        if not esperado:
            return _erro("API do agente desligada: defina SABOR_AGENTE_TOKEN.", 503)
        recebido = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(recebido.encode(), esperado.encode()):
            return _erro("Token inválido.", 401)
        return view(request, *args, **kwargs)
    return _view


def _normal(s: str) -> str:
    """Minúsculas e sem acento: o nome chega por voz, transcrito."""
    s = unicodedata.normalize("NFKD", s.casefold())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def _filtrar(itens, busca):
    if not busca:
        return list(itens)
    b = _normal(busca)
    return [i for i in itens if b in _normal(i.nome)]


def _qtd(q: Decimal, unidade: str) -> dict:
    return {"valor": float(q), "unidade": unidade, "texto": fmt_qtd(q, unidade)}


@com_token
def estoque(request):
    itens = _filtrar(Item.objects.filter(ativo=True).order_by("nome"), request.GET.get("busca", ""))
    saida = []
    for i in itens:
        s = saldo(i)
        saida.append({
            "id": i.id, "nome": i.nome, "tipo": i.tipo,
            "saldo": _qtd(s, i.unidade_base),
            "estoque_minimo": _qtd(i.estoque_minimo, i.unidade_base),
            "abaixo_do_minimo": s < i.estoque_minimo,
        })
    return JsonResponse({"itens": saida})


@com_token
def validades(request):
    try:
        dias = int(request.GET.get("dias", "3"))
    except ValueError:
        return _erro("'dias' precisa ser um número inteiro.", 400)
    hoje = timezone.localdate()
    limite = hoje + timedelta(days=dias)
    porcoes = (Movimento.objects.values("lote", "estado")
               .annotate(s=Sum("quantidade"), v=Min("validade"))
               .filter(s__gt=0))
    lotes = Lote.objects.select_related("item").in_bulk({p["lote"] for p in porcoes})
    saida = []
    for p in porcoes:
        l = lotes[p["lote"]]
        validade = p["v"] or l.validade
        if validade is None or validade > limite:
            continue
        saida.append({
            "lote_id": l.id, "item": l.item.nome, "codigo": l.codigo or "sem código",
            "estado": p["estado"] or "-", "validade": validade.isoformat(),
            "dias_restantes": (validade - hoje).days, "vencido": validade < hoje,
            "saldo": _qtd(p["s"], l.item.unidade_base),
        })
    saida.sort(key=lambda x: x["validade"])
    return JsonResponse({"hoje": hoje.isoformat(), "ate": limite.isoformat(), "lotes": saida})


@com_token
def produtos(request):
    itens = _filtrar(Item.objects.filter(tipo="produto", ativo=True).select_related("ficha").order_by("nome"),
                     request.GET.get("busca", ""))
    return JsonResponse({"produtos": [{
        "id": i.id, "nome": i.nome, "ficha": i.ficha.nome, "peso_unidade_g": float(i.peso_g),
        "saldo": _qtd(saldo(i), "un"),
    } for i in itens]})


@com_token
def receita(request):
    try:
        produto_id, unidades = int(request.GET["produto_id"]), int(request.GET["unidades"])
    except (KeyError, ValueError):
        return _erro("Informe 'produto_id' e 'unidades' (inteiros).", 400)
    produto = Item.objects.filter(id=produto_id, tipo="produto").select_related("ficha").first()
    if produto is None:
        return _erro("Produto não encontrado.", 404)
    try:
        r = escalar(produto.ficha, unidades, produto.peso_g)
    except RegraViolada as e:
        return _erro(str(e), 422)
    total, falta, unidade = {}, {}, {}
    for b in r.blocos:
        for l in b.linhas:
            total[l.nome] = total.get(l.nome, Decimal(0)) + l.quantidade
            falta[l.nome], unidade[l.nome] = l.falta, l.unidade_base
    return JsonResponse({
        "produto": produto.nome, "unidades": unidades, "massa_total": _qtd(r.total_g, "g"),
        "preparacoes": [b.nome for b in r.blocos],
        "ingredientes": [{
            "nome": n, "necessario": _qtd(total[n], unidade[n]), "falta": _qtd(falta[n], unidade[n]),
        } for n in total],
        "da_para_produzir": not any(falta.values()),
    })


def _resumo(p):
    return {"id": p.id, "produto": p.produto.nome, "unidades": p.unidades, "forma": p.forma,
            "status": p.status, "iniciada_em": timezone.localtime(p.iniciada_em).isoformat(timespec="minutes")}


@com_token
def producoes(request):
    status = request.GET.get("status", "andamento")
    qs = Producao.objects.select_related("produto").order_by("-iniciada_em")
    if status != "todas":
        qs = qs.filter(status=status)
    return JsonResponse({"producoes": [_resumo(p) for p in qs[:20]]})


@com_token
def producao(request, id):
    p = Producao.objects.select_related("produto").filter(id=id).first()
    if p is None:
        return _erro("Produção não encontrada.", 404)
    if p.etapa_atual == 0:
        etapa = "mise en place (pesagem dos ingredientes)"
    elif p.etapa_atual >= p.fechamento:
        etapa = "fechamento"
    else:
        e = p.etapas[p.etapa_atual - 1]
        etapa = f"{e['bloco']}: {e['instrucao']}"
    agora = timezone.now()
    return JsonResponse({
        **_resumo(p),
        "etapa_atual": etapa, "etapa_numero": p.etapa_atual, "total_etapas": len(p.etapas),
        "falta_pesar": [{"item": l.item.nome, "previsto": _qtd(l.previsto, l.item.unidade_base)}
                        for l in p.linhas.select_related("item") if l.usado is None],
        "cronometros": [{"nome": c.nome, "segundos_restantes": max(0, int((c.fim - agora).total_seconds()))}
                        for c in p.cronometros.filter(parado_em__isnull=True)],
        "quantidade_boa": p.quantidade_boa, "perdas": p.perdas,
        "custo_unitario": float(p.custo_unitario) if p.custo_unitario is not None else None,
    })
