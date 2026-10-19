from django.contrib import admin

from estoque.models import Movimento

from .models import Conversao, Item


class ConversaoInline(admin.TabularInline):
    model = Conversao
    extra = 0


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "unidade_base", "ativo")
    inlines = [ConversaoInline]

    def get_readonly_fields(self, request, obj=None):
        if obj and Movimento.objects.filter(item=obj).exists():
            return ("unidade_base",)
        return ()
