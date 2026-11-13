from django.contrib import admin

from estoque.models import Movimento
from nucleo.admin_executar import AdminViaExecutar

from .models import Cliente, Conversao, Fornecedor, Item


class ConversaoInline(admin.TabularInline):
    model = Conversao
    extra = 0


@admin.register(Item)
class ItemAdmin(AdminViaExecutar, admin.ModelAdmin):
    list_display = ("nome", "tipo", "unidade_base", "ficha", "peso_g", "ativo")
    inlines = [ConversaoInline]

    def get_readonly_fields(self, request, obj=None):
        if obj and Movimento.objects.filter(item=obj).exists():
            return ("unidade_base",)
        return ()


@admin.register(Fornecedor)
class FornecedorAdmin(AdminViaExecutar, admin.ModelAdmin):
    list_display = ("nome", "documento", "contato", "ativo")


@admin.register(Cliente)
class ClienteAdmin(AdminViaExecutar, admin.ModelAdmin):
    list_display = ("nome", "contato", "ativo")
