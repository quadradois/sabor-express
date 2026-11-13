from django.db import models

from estoque.models import FORMAS


class Producao(models.Model):
    produto = models.ForeignKey("cadastros.Item", on_delete=models.PROTECT)
    versao = models.ForeignKey("fichas.FichaVersao", on_delete=models.PROTECT)
    unidades = models.PositiveIntegerField()
    peso_g = models.DecimalField(max_digits=14, decimal_places=3)
    forma = models.CharField(max_length=10, choices=FORMAS)
    status = models.CharField(max_length=10, default="andamento")  # andamento | concluida | cancelada
    etapa_atual = models.PositiveIntegerField(default=0)
    # [{"bloco", "instrucao", "tempo_seg", "ponto", "midia"}]
    etapas = models.JSONField(default=list)
    quantidade_boa = models.PositiveIntegerField(null=True, blank=True)
    perdas = models.PositiveIntegerField(null=True, blank=True)
    perda_motivo = models.CharField(max_length=200, blank=True)
    anotacao = models.TextField(blank=True)
    motivo_cancelamento = models.CharField(max_length=200, blank=True)
    lote = models.OneToOneField("estoque.Lote", null=True, blank=True, on_delete=models.PROTECT)
    custo_total = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    # consumo pendente (DEC-F2-005/033): justificativa dada ao iniciar ou concluir sem saldo;
    # o custo fica pendente até cada pendência ser conciliada com um lote
    pendente_justificativa = models.CharField(max_length=200, blank=True)
    custo_pendente = models.BooleanField(default=False)
    iniciada_em = models.DateTimeField(auto_now_add=True)
    encerrada_em = models.DateTimeField(null=True, blank=True)

    @property
    def fechamento(self):
        return len(self.etapas) + 1  # 0 é o mise en place

    def __str__(self):
        return f"{self.produto} x{self.unidades} ({self.status})"


class LinhaPreparo(models.Model):
    producao = models.ForeignKey(Producao, on_delete=models.CASCADE, related_name="linhas")
    bloco = models.CharField(max_length=120)
    item = models.ForeignKey("cadastros.Item", on_delete=models.PROTECT)
    previsto = models.DecimalField(max_digits=14, decimal_places=3)
    usado = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    lote = models.ForeignKey("estoque.Lote", null=True, blank=True, on_delete=models.PROTECT)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "id"]


class Cronometro(models.Model):
    producao = models.ForeignKey(Producao, on_delete=models.CASCADE, related_name="cronometros")
    nome = models.CharField(max_length=120)
    fim = models.DateTimeField()
    parado_em = models.DateTimeField(null=True, blank=True)


class Fritura(models.Model):
    """Registro rápido de fritura (RF-FRI-01): unidades cruas de um lote viram um lote frito novo,
    vinculado ao de origem. Custo = cru consumido + óleo de referência por unidade frita (RF-FRI-02)."""

    lote_origem = models.ForeignKey("estoque.Lote", on_delete=models.PROTECT, related_name="frituras")
    estado_origem = models.CharField(max_length=20)
    quantidade = models.PositiveIntegerField()  # unidades fritas (consumidas do cru)
    boas = models.PositiveIntegerField()
    perda_motivo = models.CharField(max_length=200, blank=True)
    lote = models.OneToOneField("estoque.Lote", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="fritura")
    estado = models.CharField(max_length=20)  # conservação do frito (em geral fresco)
    custo_total = models.DecimalField(max_digits=14, decimal_places=2)
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    operacao = models.ForeignKey("nucleo.RegistroOperacao", on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    @property
    def perdas(self):
        return self.quantidade - self.boas
