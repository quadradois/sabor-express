from django.contrib import admin

from .models import Lote, Movimento


class SomenteLeitura(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Lote, SomenteLeitura)
admin.site.register(Movimento, SomenteLeitura)
