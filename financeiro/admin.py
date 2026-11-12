from django.contrib import admin

from estoque.admin import SomenteLeitura

from .models import AvisoAjuste, Conta, Pagamento, Parcela


@admin.register(Conta)
class ContaAdmin(SomenteLeitura):
    """Contas, parcelas e pagamentos só se gravam pelos serviços (`financeiro.servicos`)."""
    list_display = ("id", "descricao", "total", "cancelada")


@admin.register(Parcela)
class ParcelaAdmin(SomenteLeitura):
    list_display = ("conta", "numero", "valor", "vencimento")


@admin.register(Pagamento)
class PagamentoAdmin(SomenteLeitura):
    list_display = ("parcela", "valor", "data", "forma", "diferenca", "diferenca_tipo", "estorno_operacao")


admin.site.register(AvisoAjuste, SomenteLeitura)
