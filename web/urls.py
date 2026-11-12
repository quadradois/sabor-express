from django.contrib.auth import views as auth
from django.urls import path

from . import views, views_compras as vc

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("receita/", views.receita, name="receita"),
    path("producao/", views.producoes, name="producoes"),
    path("producao/nova/", views.producao_nova, name="producao_nova"),
    path("producao/tamanho/", views.tamanho_novo, name="tamanho_novo"),
    path("producao/<int:id>/", views.producao, name="producao"),
    path("lotes/<int:id>/", views.lote, name="lote"),
    path("lotes/<int:id>/etiquetas/", views.etiquetas, name="etiquetas"),
    path("estoque/entrada/", views.entrada, name="entrada"),
    path("fornecedores/", vc.fornecedores, name="fornecedores"),
    path("fornecedores/novo/", vc.fornecedor_form, name="fornecedor_novo"),
    path("fornecedores/<int:id>/", vc.fornecedor_form, name="fornecedor"),
    path("compras/", vc.compras_abertas, name="compras"),
    path("compras/nova/", vc.compra_nova, name="compra_nova"),
    path("compras/falta-receber/", vc.falta_receber, name="falta_receber"),
    path("compras/bonificacao/", vc.bonificacao, name="bonificacao"),
    path("compras/<int:id>/", vc.compra, name="compra"),
    path("contas/", vc.contas, name="contas"),
    path("contas/pagar/", vc.pagar, name="pagar"),
    path("contas/estornar/", vc.estornar_pagamento, name="estornar_pagamento"),
    path("avisos/", vc.avisos, name="avisos"),
    path("consumos/", vc.consumos, name="consumos"),
    path("entrar/", auth.LoginView.as_view(), name="login"),
    path("sair/", auth.LogoutView.as_view(), name="logout"),
]
