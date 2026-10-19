from django.contrib import admin

from nucleo.admin_executar import AdminViaExecutar

from .models import CriterioValidade, Lote, Movimento


class SomenteLeitura(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Lote, SomenteLeitura)
admin.site.register(Movimento, SomenteLeitura)


@admin.register(CriterioValidade)
class CriterioValidadeAdmin(AdminViaExecutar, admin.ModelAdmin):
    list_display = ("produto", "forma", "estado", "dias", "fonte")
