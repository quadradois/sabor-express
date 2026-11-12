from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse

from estoque.admin import SomenteLeitura
from nucleo.admin_executar import AdminViaExecutar
from nucleo.operacoes import RegraViolada

from .models import ComponenteItem, ComponentePreparacao, Etapa, Ficha, FichaVersao, Proporcao
from .validacao import validar_ficha
from .versoes import salvar_versao


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


class VersaoInline(admin.TabularInline):
    model = FichaVersao
    fields = readonly_fields = ("numero", "criado_em")
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        # fora do formulário de inclusão: sem versões ainda e sem management form exigido
        return obj is not None and super().has_view_permission(request, obj)


@admin.register(Ficha)
class FichaAdmin(AdminViaExecutar, admin.ModelAdmin):
    list_display = ("nome", "tipo", "rendimento_g", "ativa")
    inlines = [ComponenteItemInline, ComponentePreparacaoInline, ProporcaoInline, EtapaInline, VersaoInline]

    def depois_de_salvar(self, obj, op):
        try:
            validar_ficha(obj)
        except RegraViolada as e:
            raise _FichaInvalida(str(e))
        salvar_versao(obj, op)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        # a exceção sai do transaction.atomic do admin: tudo é desfeito
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except _FichaInvalida as e:
            messages.error(request, f"Ficha não salva: {e}")
            return HttpResponseRedirect(reverse("admin:fichas_ficha_changelist"))


admin.site.register(FichaVersao, SomenteLeitura)
