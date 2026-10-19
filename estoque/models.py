from django.db import models


class Lote(models.Model):
    item = models.ForeignKey("cadastros.Item", on_delete=models.PROTECT)
    codigo = models.CharField(max_length=60, blank=True)
    sem_lote = models.BooleanField(default=False)
    validade = models.DateField(null=True, blank=True)
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=4)  # por unidade base
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.item} {self.codigo or 'sem lote'}"


class Movimento(models.Model):
    tipo = models.CharField(max_length=30)
    item = models.ForeignKey("cadastros.Item", on_delete=models.PROTECT)
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT)
    quantidade = models.DecimalField(max_digits=14, decimal_places=3)  # positiva = entrada
    # como foi informado (RN-40): quantidade_informada × fator = quantidade
    quantidade_informada = models.DecimalField(max_digits=14, decimal_places=3)
    unidade_informada = models.CharField(max_length=10)
    fator = models.DecimalField(max_digits=14, decimal_places=6)  # unidades base por unidade informada
    motivo = models.CharField(max_length=200)
    operacao = models.ForeignKey("nucleo.RegistroOperacao", null=True, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)
