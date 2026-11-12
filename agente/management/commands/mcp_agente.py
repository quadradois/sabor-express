"""Servidor MCP do agente por stdio: `uv run python manage.py mcp_agente`.

O stdout é o canal do protocolo; qualquer print quebra o cliente. Logs vão
para o stderr.
"""

from django.core.management.base import BaseCommand

from agente.ferramentas import criar_servidor


class Command(BaseCommand):
    help = "Inicia o servidor MCP do agente (stdio)."
    requires_system_checks = []

    def handle(self, *args, **options):
        criar_servidor().run("stdio")
