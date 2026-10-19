from django.contrib import admin

from .models import Conversao, Item


class ConversaoInline(admin.TabularInline):
    model = Conversao
    extra = 0


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "unidade_base", "ativo")
    inlines = [ConversaoInline]
