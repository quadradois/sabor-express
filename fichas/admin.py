from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse

from nucleo.operacoes import RegraViolada

from .models import ComponenteItem, ComponentePreparacao, Etapa, Ficha, Proporcao
from .validacao import validar_ficha


class _FichaInvalida(Exception):
    pass


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
            raise _FichaInvalida(str(e))

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        # a exceção sai do transaction.atomic do admin: tudo é desfeito
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except _FichaInvalida as e:
            messages.error(request, f"Ficha não salva: {e}")
            return HttpResponseRedirect(reverse("admin:fichas_ficha_changelist"))
