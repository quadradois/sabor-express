from django.db import models

DIFERENCAS = [("juros", "Juros"), ("multa", "Multa"), ("desconto", "Desconto")]


class Conta(models.Model):
    """Obrigação a pagar (RF-FIN-01). No Plano 3 só nasce de compra: 1 compra → 1 conta → N parcelas."""

    origem = models.CharField(max_length=20, default="compra")
    compra = models.OneToOneField("compras.Compra", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="conta")
    fornecedor = models.ForeignKey("cadastros.Fornecedor", null=True, blank=True, on_delete=models.PROTECT)
    descricao = models.CharField(max_length=200)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    cancelada = models.BooleanField(default=False)
    motivo_cancelamento = models.CharField(max_length=200, blank=True)
    operacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.descricao


class Parcela(models.Model):
    conta = models.ForeignKey(Conta, on_delete=models.PROTECT, related_name="parcelas")
    numero = models.PositiveIntegerField()
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    vencimento = models.DateField()

    class Meta:
        ordering = ["vencimento", "numero"]
        constraints = [models.UniqueConstraint(fields=["conta", "numero"], name="parcela_unica_por_conta")]

    def __str__(self):
        return f"{self.conta} — parcela {self.numero}"


class Pagamento(models.Model):
    """Anotação de que o dono pagou (o sistema nunca paga nada)."""

    parcela = models.ForeignKey(Parcela, on_delete=models.PROTECT, related_name="pagamentos")
    valor = models.DecimalField(max_digits=12, decimal_places=2)  # quanto abate da parcela
    data = models.DateField()
    forma = models.CharField(max_length=30, blank=True)
    # juros/multa: pagou valor + diferença; desconto: pagou valor − diferença (DEC-F2-025)
    diferenca = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    diferenca_tipo = models.CharField(max_length=10, choices=DIFERENCAS, blank=True)
    diferenca_motivo = models.CharField(max_length=200, blank=True)
    operacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT)
    # o estorno anula sem apagar nem editar os valores (DEC-F2-027)
    estorno_operacao = models.ForeignKey("nucleo.RegistroOperacao", null=True, blank=True,
                                         on_delete=models.PROTECT, related_name="+")
    motivo_estorno = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    @property
    def valor_pago(self):
        """Quanto saiu do bolso do dono."""
        sinal = -1 if self.diferenca_tipo == "desconto" else 1
        return self.valor + sinal * self.diferenca


class AvisoAjuste(models.Model):
    """Alerta de ajuste manual na conta (RN-09): nada é recalculado sozinho."""

    conta = models.ForeignKey(Conta, on_delete=models.PROTECT, related_name="avisos")
    texto = models.CharField(max_length=300)
    operacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT)
    resolvido_operacao = models.ForeignKey("nucleo.RegistroOperacao", null=True, blank=True,
                                           on_delete=models.PROTECT, related_name="+")
    observacao = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
