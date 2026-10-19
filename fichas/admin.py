from django.contrib import admin, messages
from django.db import transaction

from nucleo.operacoes import RegraViolada

from .models import ComponenteItem, ComponentePreparacao, Etapa, Ficha, Proporcao
from .validacao import validar_ficha


class ComponenteItemInline(admin.TabularInline):
    model = ComponenteItem
    extra = 0


class ComponentePreparacaoInline(admin.TabularInline):
    model = ComponentePreparacao
    fk_name = "ficha"
    extra = 0


class ProporcaoInline(admin.TabularInline):
    model = Proporcao
    fk_name = "ficha"
    extra = 0


class EtapaInline(admin.TabularInline):
    model = Etapa
    extra = 0


@admin.register(Ficha)
class FichaAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "rendimento_g", "ativa")
    inlines = [ComponenteItemInline, ComponentePreparacaoInline, ProporcaoInline, EtapaInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        try:
            validar_ficha(form.instance)
        except RegraViolada as e:
            # a changeform_view do admin já roda em transaction.atomic: desfaz tudo
            transaction.set_rollback(True)
            messages.error(request, f"Ficha não salva: {e}")
