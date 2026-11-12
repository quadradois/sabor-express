from django.urls import path

from . import views

urlpatterns = [
    path("estoque/", views.estoque),
    path("validades/", views.validades),
    path("produtos/", views.produtos),
    path("receita/", views.receita),
    path("producoes/", views.producoes),
    path("producoes/<int:id>/", views.producao),
]
