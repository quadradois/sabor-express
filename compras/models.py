from django.db import models

STATUS = [("aprovada", "Aprovada"), ("parcial", "Parcialmente recebida"), ("recebida", "Recebida"),
          ("encerrada", "Encerrada com pendência"), ("cancelada", "Cancelada")]


class Compra(models.Model):
    """Compra aprovada (RF-CMP-01/10): nasce aprovada; a aprovação é a operação que a criou."""

    fornecedor = models.ForeignKey("cadastros.Fornecedor", on_delete=models.PROTECT)
    data = models.DateField()
    documento = models.CharField(max_length=60, blank=True)  # número ou chave do documento
    frete = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    desconto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    acrescimo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)  # total do documento
    justificativa = models.CharField(max_length=200, blank=True)  # divergência soma × total (RF-CMP-08)
    status = models.CharField(max_length=12, choices=STATUS, default="aprovada")
    motivo_cancelamento = models.CharField(max_length=200, blank=True)
    operacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT)  # aprovação
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Compra {self.id} — {self.fornecedor} {self.data:%d/%m/%Y}"


class LinhaCompra(models.Model):
    compra = models.ForeignKey(Compra, on_delete=models.PROTECT, related_name="linhas")
    item = models.ForeignKey("cadastros.Item", on_delete=models.PROTECT)
    # como veio no documento (RN-40): quantidade × fator = quantidade_base
    quantidade = models.DecimalField(max_digits=14, decimal_places=3)
    unidade = models.CharField(max_length=10)
    fator = models.DecimalField(max_digits=14, decimal_places=6)
    quantidade_base = models.DecimalField(max_digits=14, decimal_places=3)  # documentada (RN-07)
    valor = models.DecimalField(max_digits=12, decimal_places=2)  # valor total da linha
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=4)  # por unidade base (RN-20)
    encerrado = models.DecimalField(max_digits=14, decimal_places=3, default=0)  # "não entregue" (RF-REC-04)
    motivo_encerramento = models.CharField(max_length=200, blank=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "id"]

    def __str__(self):
        return f"{self.item} ({self.compra_id})"


class Recebimento(models.Model):
    """Evento físico distinto da aprovação (RN-04): cada um gera um lote e uma entrada."""

    linha = models.ForeignKey(LinhaCompra, on_delete=models.PROTECT, related_name="recebimentos")
    lote = models.OneToOneField("estoque.Lote", on_delete=models.PROTECT)
    quantidade = models.DecimalField(max_digits=14, decimal_places=3)  # unidade base
    operacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT)
    # o estorno anula sem apagar (RF-REC-06): o movimento de estorno está no estoque
    estorno_operacao = models.ForeignKey("nucleo.RegistroOperacao", null=True, blank=True,
                                         on_delete=models.PROTECT, related_name="+")
    motivo_estorno = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
