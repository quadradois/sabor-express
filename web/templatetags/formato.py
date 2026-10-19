from decimal import Decimal, ROUND_HALF_UP

from django import template

register = template.Library()
_GRANDE = {"g": ("kg", "g"), "mL": ("L", "mL")}


@register.filter
def quantidade(q, unidade_base):
    q = Decimal(q)
    un = unidade_base
    if unidade_base in _GRANDE and q >= 1000:
        q, un = q / 1000, _GRANDE[unidade_base][0]
    q = q.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    txt = f"{q:f}".rstrip("0").rstrip(".") if "." in f"{q:f}" else f"{q:f}"
    return f"{txt.replace('.', ',')} {un}"


@register.filter
def minutos(seg):
    return quantidade(Decimal(seg) / 60, "un").removesuffix(" un")
