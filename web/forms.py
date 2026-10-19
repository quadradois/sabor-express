from django import forms
from django.core.exceptions import ValidationError

from cadastros.models import Item
from fichas.models import Ficha

MAIOR_QUE_ZERO = "Informe um valor maior que zero."


class DecimalBR(forms.DecimalField):
    """Decimal com vírgula; ponto é recusado (sem separador de milhar, "1.500" viraria 1,5)."""

    def __init__(self, *, decimal_places=3, **kwargs):
        super().__init__(max_digits=14, decimal_places=decimal_places, localize=True, **kwargs)

    def to_python(self, value):
        if isinstance(value, str) and "." in value:
            raise ValidationError("Use vírgula para decimais (ex.: 1,5).")
        return super().to_python(value)


class ReceitaForm(forms.Form):
    ficha = forms.ModelChoiceField(Ficha.objects.filter(tipo="produto", ativa=True), label="Produto")
    unidades = forms.IntegerField(min_value=1, label="Unidades",
                                  error_messages={"min_value": MAIOR_QUE_ZERO})
    peso = DecimalBR(min_value=0.001, label="Peso de cada unidade (g)",
                              error_messages={"min_value": MAIOR_QUE_ZERO})


class EntradaForm(forms.Form):
    item = forms.ModelChoiceField(Item.objects.filter(ativo=True), label="Item")
    quantidade = DecimalBR(label="Quantidade")
    unidade = forms.CharField(label="Unidade", widget=forms.TextInput(
        attrs={"list": "unidades", "autocapitalize": "off"}))
    custo_total = DecimalBR(decimal_places=2, min_value=0, label="Custo total (R$)")
    lote_codigo = forms.CharField(required=False, label="Lote")
    validade = forms.DateField(required=False, label="Validade", widget=forms.DateInput(attrs={"type": "date"}))
    motivo = forms.CharField(required=False, label="Motivo")  # regra validada (e auditada) no serviço
    chave = forms.CharField(widget=forms.HiddenInput)
