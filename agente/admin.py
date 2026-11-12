from django.contrib import admin

from .models import Proposta


@admin.register(Proposta)
class PropostaAdmin(admin.ModelAdmin):
    list_display = ("criada_em", "operacao", "resumo", "estado", "canal", "autor", "resolvida_por")
    list_filter = ("estado", "operacao", "canal")

    # trilha de auditoria: decide-se pelo agente (e, no Plano 4, pela caixa de decisões)
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
