from django.db import models


class RegistroOperacao(models.Model):
    nome = models.CharField(max_length=100)
    chave = models.CharField(max_length=200, unique=True, null=True, blank=True)
    canal = models.CharField(max_length=20)  # web | telegram | agente | sistema
    autor = models.CharField(max_length=100)
    status = models.CharField(max_length=10)  # sucesso | erro
    resultado = models.JSONField(null=True)
    erro = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
