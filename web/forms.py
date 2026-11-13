from django import forms
from django.core.exceptions import ValidationError

from cadastros.models import Item
from estoque.models import ESTADOS
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


class ProducaoForm(forms.Form):
    produto = forms.ModelChoiceField(Item.objects.filter(tipo="produto", ativo=True), label="Produto")
    unidades = forms.IntegerField(min_value=1, label="Unidades",
                                  error_messages={"min_value": MAIOR_QUE_ZERO})
    forma = forms.ChoiceField(choices=[("cru", "Cru (guardar ou congelar)"), ("frito", "Frito")],
                              widget=forms.RadioSelect, initial="cru", label="Forma")
    pendente_justificativa = forms.CharField(required=False, widget=forms.HiddenInput)
    chave = forms.CharField(widget=forms.HiddenInput)


class TamanhoForm(forms.Form):
    ficha = forms.ModelChoiceField(Ficha.objects.filter(tipo="produto", ativa=True), label="Receita")
    peso = DecimalBR(min_value=0.001, label="Peso de cada unidade (g)",
                     error_messages={"min_value": MAIOR_QUE_ZERO})
    chave = forms.CharField(widget=forms.HiddenInput)


class EntradaForm(forms.Form):
    item = forms.ModelChoiceField(Item.objects.filter(ativo=True).exclude(tipo="produto"), label="Item")
    quantidade = DecimalBR(label="Quantidade")
    unidade = forms.CharField(label="Unidade", widget=forms.TextInput(
        attrs={"list": "unidades", "autocapitalize": "off"}))
    custo_total = DecimalBR(decimal_places=2, min_value=0, label="Custo total (R$)")
    lote_codigo = forms.CharField(required=False, label="Lote")
    validade = forms.DateField(required=False, label="Validade", widget=forms.DateInput(attrs={"type": "date"}))
    motivo = forms.CharField(required=False, label="Motivo")  # regra validada (e auditada) no serviço
    chave = forms.CharField(widget=forms.HiddenInput)


class PesoForm(forms.Form):
    usado = DecimalBR(label="Peso")


class ConclusaoForm(forms.Form):
    quantidade_boa = forms.IntegerField(min_value=0, label="Quantidade boa")
    perdas = forms.IntegerField(min_value=0, initial=0, label="Perdas")
    perda_motivo = forms.CharField(required=False, label="Motivo das perdas")
    estado = forms.ChoiceField(choices=ESTADOS, widget=forms.RadioSelect, label="Estado inicial")
    validade_manual = forms.DateField(required=False, label="Validade manual",
                                      help_text="Só se não houver critério de validade",
                                      widget=forms.DateInput(attrs={"type": "date"}))
    justificativa = forms.CharField(required=False, label="Justificativa da validade")
    anotacao = forms.CharField(required=False, label="Como foi? (inclui sobras)", widget=forms.Textarea(attrs={"rows": 3}))
    confirmar_perda_total = forms.BooleanField(required=False, label="Confirmo a perda total")
    motivo_vencido = forms.CharField(required=False, label="Motivo do vencido (só se o sistema pedir)",
                                     help_text="Lote vencido só entra na produção com um motivo, que fica registrado.")


class TransferenciaForm(forms.Form):
    quantidade = DecimalBR(min_value=0.001, label="Quantidade", error_messages={"min_value": MAIOR_QUE_ZERO})
    de = forms.ChoiceField(choices=ESTADOS, label="De")
    para = forms.ChoiceField(choices=ESTADOS, label="Para")
    validade_manual = forms.DateField(required=False, label="Validade manual (opcional)",
                                      widget=forms.DateInput(attrs={"type": "date"}))
    justificativa = forms.CharField(required=False, label="Justificativa (opcional)")
    motivo_vencido = forms.CharField(required=False, label="Motivo do vencido (só se o sistema pedir)",
                                     help_text="Lote vencido só muda de conservação com um motivo, que fica registrado.")
    chave = forms.CharField(widget=forms.HiddenInput)
