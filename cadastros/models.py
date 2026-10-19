from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Item(models.Model):
    TIPOS = [("ingrediente", "Ingrediente"), ("insumo", "Insumo"), ("embalagem", "Embalagem")]
    UNIDADES = [("g", "g"), ("mL", "mL"), ("un", "un")]

    nome = models.CharField(max_length=120, unique=True)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    unidade_base = models.CharField(max_length=5, choices=UNIDADES)
    controla_validade = models.BooleanField(default=True)
    estoque_minimo = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome

    def clean(self):
        from estoque.models import Movimento  # evita import circular

        if self.pk and Movimento.objects.filter(item_id=self.pk).exists():
            antes = Item.objects.get(pk=self.pk).unidade_base
            if antes != self.unidade_base:
                raise ValidationError({"unidade_base": "Item com movimentos não pode mudar de unidade base."})


class Conversao(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="conversoes")
    unidade = models.CharField(max_length=10)
    # quantas unidades base há em 1 `unidade`
    fator = models.DecimalField(
        max_digits=14, decimal_places=6,
        validators=[MinValueValidator(Decimal("0.000001"))],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["item", "unidade"], name="conversao_unica_por_item"),
            models.CheckConstraint(condition=models.Q(fator__gt=0), name="conversao_fator_positivo"),
        ]

    def __str__(self):
        return f"1 {self.unidade} de {self.item} = {self.fator} {self.item.unidade_base}"
