from django import forms

from cadastros.models import Item
from fichas.models import Ficha

MAIOR_QUE_ZERO = "Informe um valor maior que zero."


class ReceitaForm(forms.Form):
    ficha = forms.ModelChoiceField(Ficha.objects.filter(tipo="produto", ativa=True), label="Produto")
    unidades = forms.IntegerField(min_value=1, label="Unidades",
                                  error_messages={"min_value": MAIOR_QUE_ZERO})
    peso = forms.DecimalField(min_value=0.001, localize=True, label="Peso de cada unidade (g)",
                              error_messages={"min_value": MAIOR_QUE_ZERO})


class EntradaForm(forms.Form):
    item = forms.ModelChoiceField(Item.objects.all(), label="Item")
    quantidade = forms.DecimalField(localize=True, label="Quantidade")
    unidade = forms.CharField(label="Unidade", widget=forms.TextInput(attrs={"list": "unidades"}))
    custo_total = forms.DecimalField(localize=True, min_value=0, label="Custo total (R$)")
    lote_codigo = forms.CharField(required=False, label="Lote")
    validade = forms.DateField(required=False, label="Validade", widget=forms.DateInput(attrs={"type": "date"}))
    motivo = forms.CharField(label="Motivo")
    chave = forms.CharField(widget=forms.HiddenInput)
