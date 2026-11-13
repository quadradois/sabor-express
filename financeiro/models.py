from django.db import models

DIFERENCAS = [("juros", "Juros"), ("multa", "Multa"), ("desconto", "Desconto")]
TIPOS = [("pagar", "A pagar"), ("receber", "A receber")]


class CategoriaDespesa(models.Model):
    """Categoria de despesa (Plano 8): mão de obra, energia, gás, internet... `indireta` = gasto da produção
    (entra na comparação com o indireto de referência por salgado, `Item.indireto_ref_un`)."""

    nome = models.CharField(max_length=60, unique=True)
    indireta = models.BooleanField(default=False)
    ativa = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "nome"]
        verbose_name = "categoria de despesa"
        verbose_name_plural = "categorias de despesa"

    def __str__(self):
        return self.nome


class DespesaMensal(models.Model):
    """Despesa que se repete todo mês (luz, internet, DAS...). A rotina gera a conta do mês uma única vez
    (`DespesaDoMes`); `valor_previsto` vazio = a conta do mês nasce sem valor e o dono informa depois."""

    nome = models.CharField(max_length=100, unique=True)
    categoria = models.ForeignKey(CategoriaDespesa, on_delete=models.PROTECT, related_name="mensais")
    dia_vencimento = models.PositiveSmallIntegerField(default=10)
    valor_previsto = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    ativa = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "despesa mensal"
        verbose_name_plural = "despesas mensais"

    def __str__(self):
        return self.nome


class Conta(models.Model):
    """Obrigação a pagar (RF-FIN-01) ou a receber (RF-FIN-06). A pagar nasce de compra (1 compra → 1 conta)
    ou de despesa (`origem="despesa"`, com `categoria` e `competencia`, Plano 8); a receber, de venda a prazo
    ou do saldo de encomenda entregue a prazo (1 venda → 1 conta). N parcelas."""

    tipo = models.CharField(max_length=10, choices=TIPOS, default="pagar")
    origem = models.CharField(max_length=20, default="compra")
    compra = models.OneToOneField("compras.Compra", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="conta")
    fornecedor = models.ForeignKey("cadastros.Fornecedor", null=True, blank=True, on_delete=models.PROTECT)
    venda = models.OneToOneField("vendas.Venda", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="conta")
    cliente = models.ForeignKey("cadastros.Cliente", null=True, blank=True, on_delete=models.PROTECT)
    descricao = models.CharField(max_length=200)
    # despesa (Plano 8): categoria e o dia a que o gasto pertence (avulsa: o dia da despesa; mensal: dia 1 do mês)
    categoria = models.ForeignKey(CategoriaDespesa, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="contas")
    competencia = models.DateField(null=True, blank=True)
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
    """Anotação de que o dono pagou ou recebeu (o sistema nunca movimenta dinheiro).
    Em conta a receber, `valor_pago` é quanto entrou (desconto = o cliente pagou menos)."""

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


class DespesaDoMes(models.Model):
    """A despesa mensal num mês (competência = dia 1). Nasce pela rotina, uma por mês. `conta` vazia = ainda sem
    valor (o dono informa ao anotar o pagamento); com valor, a conta a pagar segue o fluxo normal."""

    despesa = models.ForeignKey(DespesaMensal, on_delete=models.PROTECT, related_name="meses")
    competencia = models.DateField()
    vencimento = models.DateField()
    conta = models.OneToOneField(Conta, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="despesa_do_mes")
    operacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["competencia", "vencimento", "id"]
        verbose_name = "despesa do mês"
        verbose_name_plural = "despesas do mês"
        constraints = [models.UniqueConstraint(fields=["despesa", "competencia"], name="despesa_uma_vez_por_mes")]

    def __str__(self):
        return f"{self.despesa} — {self.competencia:%m/%Y}"
