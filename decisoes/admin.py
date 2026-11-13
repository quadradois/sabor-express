from django.contrib import admin

from estoque.admin import SomenteLeitura

from .models import Decisao


@admin.register(Decisao)
class DecisaoAdmin(SomenteLeitura):
    # decide-se pela caixa (tela ou agente), que passa pelo núcleo
    list_display = ("criada_em", "origem", "texto", "operacao", "situacao", "decidida_por")
    list_filter = ("situacao", "origem", "vigente")
