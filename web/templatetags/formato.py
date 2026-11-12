import uuid
from decimal import Decimal, ROUND_HALF_UP

from django import template
from django.utils.html import format_html

register = template.Library()
_GRANDE = {"g": ("kg", "g"), "mL": ("L", "mL")}


@register.filter
def quantidade(q, unidade_base):
    q = Decimal(q).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    un = unidade_base
    if unidade_base in _GRANDE and q >= 1000:
        q, un = (q / 1000).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP), _GRANDE[unidade_base][0]
    txt = f"{q:f}".rstrip("0").rstrip(".") if "." in f"{q:f}" else f"{q:f}"
    return f"{txt.replace('.', ',')} {un}"


@register.filter
def dinheiro(v):
    """R$ com vírgula decimal e ponto de milhar: 1234.5 -> "R$ 1.234,50"."""
    v = Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    txt = f"{abs(v):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{'-' if v < 0 else ''}R$ {txt}"


@register.filter
def minutos(seg):
    return quantidade(Decimal(seg) / 60, "un").removesuffix(" un")


@register.simple_tag
def chave():
    """Chave de idempotência nova a cada render: cada formulário do POST leva a sua."""
    return format_html('<input type="hidden" name="chave" value="{}">', uuid.uuid4().hex)
