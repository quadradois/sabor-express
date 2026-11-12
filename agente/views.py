"""API REST de consulta para o agente de voz (EscofIA). Só leitura.

Todas as rotas exigem `Authorization: Bearer <SABOR_AGENTE_TOKEN>`. Sem o token
configurado no servidor a API fica desligada (503). A lógica mora em
`agente.consultas`, a mesma usada pelo servidor MCP (`manage.py mcp_agente`).
"""

import hmac
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from . import consultas
from .consultas import ConsultaInvalida


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
        try:
            return JsonResponse(view(request, *args, **kwargs))
        except ConsultaInvalida as e:
            return JsonResponse(e.como_dict(), status=e.status)
    return _view


@com_token
def estoque(request):
    return consultas.estoque(request.GET.get("busca", ""))


@com_token
def validades(request):
    return consultas.validades(request.GET.get("dias", "3"))


@com_token
def produtos(request):
    return consultas.produtos(request.GET.get("busca", ""))


@com_token
def receita(request):
    return consultas.receita(request.GET.get("produto_id"), request.GET.get("unidades"))


@com_token
def producoes(request):
    return consultas.producoes(request.GET.get("status", "andamento"))


@com_token
def producao(request, id):
    return consultas.producao(id)
