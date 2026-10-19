from django.db import models

from cadastros.models import Item


class Ficha(models.Model):
    TIPOS = [("preparacao", "Preparação"), ("produto", "Produto")]

    nome = models.CharField(max_length=120, unique=True)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    # obrigatório e > 0 para preparação; vazio para produto (validar_ficha)
    rendimento_g = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    ativa = models.BooleanField(default=True)

    def __str__(self):
        return self.nome


class ComponenteItem(models.Model):
    """Só em fichas de preparação. Quantidade na unidade base do item."""
    ficha = models.ForeignKey(Ficha, on_delete=models.CASCADE, related_name="itens")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    quantidade = models.DecimalField(max_digits=14, decimal_places=3)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem"]


class ComponentePreparacao(models.Model):
    """Só em fichas de preparação."""
    ficha = models.ForeignKey(Ficha, on_delete=models.CASCADE, related_name="subpreparacoes")
    preparacao = models.ForeignKey(Ficha, on_delete=models.PROTECT, related_name="+")
    quantidade_g = models.DecimalField(max_digits=14, decimal_places=3)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem"]


class Proporcao(models.Model):
    """Só em fichas de produto."""
    ficha = models.ForeignKey(Ficha, on_delete=models.CASCADE, related_name="proporcoes")
    preparacao = models.ForeignKey(Ficha, on_delete=models.PROTECT, related_name="+")
    percentual = models.DecimalField(max_digits=6, decimal_places=3)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem"]


class Etapa(models.Model):
    ficha = models.ForeignKey(Ficha, on_delete=models.CASCADE, related_name="etapas")
    ordem = models.PositiveIntegerField(default=0)
    instrucao = models.CharField(max_length=300)
    tempo_seg = models.PositiveIntegerField(null=True, blank=True)
    ponto = models.CharField(max_length=200, blank=True)
    midia = models.FileField(upload_to="etapas/", blank=True)

    class Meta:
        ordering = ["ordem"]
