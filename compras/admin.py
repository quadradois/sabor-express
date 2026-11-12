from django.contrib import admin

from estoque.admin import SomenteLeitura

from .models import Compra, LinhaCompra, Recebimento


class LinhaInline(admin.TabularInline):
    model = LinhaCompra
    extra = 0
    can_delete = False
    fields = ("item", "quantidade", "unidade", "quantidade_base", "valor", "custo_unitario", "encerrado")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Compra)
class CompraAdmin(SomenteLeitura):
    """Compras só se gravam pelos serviços (`compras.servicos`); o admin só mostra."""
    list_display = ("id", "fornecedor", "data", "total", "status")
    list_filter = ("status",)
    inlines = [LinhaInline]


admin.site.register(Recebimento, SomenteLeitura)
