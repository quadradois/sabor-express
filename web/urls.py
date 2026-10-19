from django.contrib.auth import views as auth
from django.urls import path

from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("receita/", views.receita, name="receita"),
    path("estoque/entrada/", views.entrada, name="entrada"),
    path("entrar/", auth.LoginView.as_view(), name="login"),
    path("sair/", auth.LogoutView.as_view(), name="logout"),
]
