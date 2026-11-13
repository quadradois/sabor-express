from django.contrib import admin

from estoque.admin import SomenteLeitura
from nucleo.admin_executar import AdminViaExecutar

from .models import AvisoAjuste, CategoriaDespesa, Conta, DespesaDoMes, DespesaMensal, Pagamento, Parcela


@admin.register(Conta)
class ContaAdmin(SomenteLeitura):
    """Contas, parcelas e pagamentos só se gravam pelos serviços (`financeiro.servicos`)."""
    list_display = ("id", "descricao", "origem", "categoria", "competencia", "total", "cancelada")


@admin.register(Parcela)
class ParcelaAdmin(SomenteLeitura):
    list_display = ("conta", "numero", "valor", "vencimento")


@admin.register(Pagamento)
class PagamentoAdmin(SomenteLeitura):
    list_display = ("parcela", "valor", "data", "forma", "diferenca", "diferenca_tipo", "estorno_operacao")


admin.site.register(AvisoAjuste, SomenteLeitura)


@admin.register(CategoriaDespesa)
class CategoriaDespesaAdmin(AdminViaExecutar, admin.ModelAdmin):
    """Categorias de despesa: editáveis (gravam pelo núcleo); em uso, inativa-se em vez de apagar."""
    list_display = ("nome", "indireta", "ativa", "ordem")


@admin.register(DespesaMensal)
class DespesaMensalAdmin(AdminViaExecutar, admin.ModelAdmin):
    """A despesa do mês é gerada pela rotina (ou ao salvar pela tela, `financeiro.despesas`)."""
    list_display = ("nome", "categoria", "dia_vencimento", "valor_previsto", "ativa")


@admin.register(DespesaDoMes)
class DespesaDoMesAdmin(SomenteLeitura):
    list_display = ("despesa", "competencia", "vencimento", "conta")
