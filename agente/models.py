from django.db import models


class Proposta(models.Model):
    """Gravação que espera o "sim" de alguém antes de acontecer.

    Nasce pendente com a operação e os parâmetros prontos para
    `nucleo.operacoes.executar`; confirmar executa com a `chave` da proposta
    (confirmar de novo não duplica). É a base da futura caixa de decisões.
    """
    ESTADOS = [("pendente", "Pendente"), ("confirmada", "Confirmada"), ("recusada", "Recusada"),
               ("expirada", "Expirada")]

    operacao = models.CharField(max_length=100)
    parametros = models.JSONField()
    resumo = models.TextField()  # o que vai acontecer, em uma frase falável
    autor = models.CharField(max_length=100)  # quem propôs
    canal = models.CharField(max_length=20)
    estado = models.CharField(max_length=10, choices=ESTADOS, default="pendente")
    chave = models.CharField(max_length=200, unique=True)  # chave de idempotência da execução
    criada_em = models.DateTimeField(auto_now_add=True)
    expira_em = models.DateTimeField()
    resolvida_em = models.DateTimeField(null=True, blank=True)
    resolvida_por = models.CharField(max_length=100, blank=True)
    registro = models.ForeignKey("nucleo.RegistroOperacao", null=True, blank=True, on_delete=models.PROTECT)
    resultado = models.JSONField(null=True, blank=True)
    erro = models.TextField(blank=True)  # última recusa do núcleo ao confirmar

    class Meta:
        indexes = [models.Index(fields=["estado", "expira_em"])]

    def __str__(self):
        return f"#{self.id} {self.operacao} ({self.estado})"
