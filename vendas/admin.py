from django.contrib import admin

from estoque.admin import SomenteLeitura
from nucleo.admin_executar import AdminViaExecutar

from .models import Apresentacao, CanalVenda, Encomenda, ItemEncomenda, LinhaVenda, Reserva, Venda


@admin.register(Apresentacao)
class ApresentacaoAdmin(SomenteLeitura):
    """Apresentações e preços se gravam por `vendas.servicos.salvar_apresentacao` (regras de mudança)."""
    list_display = ("produto", "nome", "forma", "estado", "unidades", "preco_varejo", "preco_atacado", "ativo")


@admin.register(CanalVenda)
class CanalVendaAdmin(AdminViaExecutar, admin.ModelAdmin):
    """Canais e taxas do estudo de preço (Plano 8); taxa vazia = não informada."""
    list_display = ("nome", "taxa_pct", "ativo", "ordem")


@admin.register(Venda)
class VendaAdmin(SomenteLeitura):
    """Vendas, encomendas e reservas só se gravam pelos serviços (`vendas.servicos`)."""
    list_display = ("id", "data", "cliente", "condicao", "total", "custo", "situacao")


@admin.register(Encomenda)
class EncomendaAdmin(SomenteLeitura):
    list_display = ("id", "cliente", "entrega_data", "entrega_hora", "total", "sinal", "situacao")


@admin.register(Reserva)
class ReservaAdmin(SomenteLeitura):
    list_display = ("item_encomenda", "lote", "estado", "quantidade", "situacao")


admin.site.register(LinhaVenda, SomenteLeitura)
admin.site.register(ItemEncomenda, SomenteLeitura)
