from django.db import models


ESTADOS = [("fresco", "Fresco"), ("resfriado", "Resfriado"), ("congelado", "Congelado")]
FORMAS = [("cru", "Cru"), ("frito", "Frito")]
# para onde foi o que saiu sem venda (Plano 9: "estão aqui" na conferência do vencido); todas são baixa com valor
DESTINOS_PERDA = [("perda", "Perda"), ("descarte", "Descarte"), ("consumo_equipe", "Consumo da equipe"),
                  ("doacao", "Doação")]


class Lote(models.Model):
    item = models.ForeignKey("cadastros.Item", on_delete=models.PROTECT)
    codigo = models.CharField(max_length=60, blank=True)
    sem_lote = models.BooleanField(default=False)
    validade = models.DateField(null=True, blank=True)
    forma = models.CharField(max_length=10, choices=FORMAS, blank=True, default="")
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
    estado = models.CharField(max_length=20, choices=ESTADOS, blank=True, default="")
    validade = models.DateField(null=True, blank=True)
    validade_manual = models.BooleanField(default=False)
    operacao = models.ForeignKey("nucleo.RegistroOperacao", null=True, on_delete=models.PROTECT)
    # Plano 9: porção vencida só sai com motivo (aviso com motivo, não trava); vazio = não estava vencida
    motivo_vencido = models.CharField(max_length=200, blank=True, default="")
    destino = models.CharField(max_length=20, choices=DESTINOS_PERDA, blank=True, default="")  # só em perda
    criado_em = models.DateTimeField(auto_now_add=True)


class CriterioValidade(models.Model):
    produto = models.ForeignKey("cadastros.Item", on_delete=models.CASCADE, limit_choices_to={"tipo": "produto"})
    forma = models.CharField(max_length=10, choices=FORMAS)
    estado = models.CharField(max_length=20, choices=ESTADOS)
    dias = models.PositiveIntegerField()
    fonte = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["produto", "forma", "estado"], name="criterio_unico")]

    def __str__(self):
        return f"{self.produto} {self.forma} {self.estado}: {self.dias} dias"


class EtiquetaImpressa(models.Model):
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT)
    estado = models.CharField(max_length=20, choices=ESTADOS)
    copias = models.PositiveIntegerField()
    reimpressao = models.BooleanField(default=False)
    operacao = models.ForeignKey("nucleo.RegistroOperacao", null=True, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)


class ConsumoPendente(models.Model):
    """Consumo sem saldo registrado (DEC-F2-005): não gera movimento até ser conciliado com um lote."""

    item = models.ForeignKey("cadastros.Item", on_delete=models.PROTECT)
    quantidade = models.DecimalField(max_digits=14, decimal_places=3)  # unidade base
    justificativa = models.CharField(max_length=200)
    producao = models.ForeignKey("producao.Producao", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="consumos_pendentes")
    operacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT)
    # conciliação única (DEC-F2-033): lote e custo definidos uma vez
    lote = models.ForeignKey(Lote, null=True, blank=True, on_delete=models.PROTECT)
    custo = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    conciliacao_operacao = models.ForeignKey("nucleo.RegistroOperacao", null=True, blank=True,
                                             on_delete=models.PROTECT, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)

    @property
    def aberto(self):
        return self.lote_id is None
