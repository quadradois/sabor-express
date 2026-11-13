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
def numero(q):
    """Número para preencher campo de formulário: vírgula decimal, sem milhar e sem zeros à toa (12,000 -> 12)."""
    return quantidade(q, "un").removesuffix(" un")


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


@register.filter
def bonito(valor):
    """JSON legível (parâmetros e resultados da trilha), com acentos."""
    import json
    return json.dumps(valor, ensure_ascii=False, indent=2, default=str)


@register.filter
def idade(quando):
    """Há quanto tempo: "agora", "há 5 min", "há 3 h", "há 2 dia(s)"."""
    from django.utils import timezone
    seg = max(0, int((timezone.now() - quando).total_seconds()))
    if seg < 60:
        return "agora"
    if seg < 3600:
        return f"há {seg // 60} min"
    if seg < 86400:
        return f"há {seg // 3600} h"
    return f"há {seg // 86400} dia(s)"


@register.filter
def conservacao(estado):
    """"congelado" -> "Congelado" (o rótulo do estoque); desconhecido volta como veio."""
    from estoque.models import ESTADOS
    return dict(ESTADOS).get(estado, estado)


@register.filter
def forma_nome(forma):
    from estoque.models import FORMAS
    return dict(FORMAS).get(forma, forma)


# ---------- custos e margens (Plano 7): None nunca vira zero ----------

def _virgula(v, casas, sinal=False):
    v = Decimal(v).quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    txt = f"{abs(v):,.{casas}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{'-' if v < 0 else '+' if sinal and v > 0 else ''}{txt}"


@register.filter
def din(v):
    """Dinheiro; valor desconhecido (None) aparece como "—", nunca como R$ 0,00."""
    return "—" if v is None else dinheiro(v)


@register.filter
def custo4(v):
    """Custo por unidade (4 casas): R$ 0,1500."""
    return "—" if v is None else f"R$ {_virgula(v, 4)}"


@register.filter
def pct(v):
    """Porcentagem com uma casa: 12,3%."""
    return "—" if v is None else f"{_virgula(v, 1)}%"


@register.filter
def pctsinal(v):
    """Variação com sinal: +5,0% / -2,5%."""
    return "—" if v is None else f"{_virgula(v, 1, sinal=True)}%"


@register.filter
def pontos(v):
    """Diferença entre duas porcentagens, em pontos: +2,1 pontos / -6,0 pontos."""
    return "—" if v is None else f"{_virgula(v, 1, sinal=True)} pontos"


@register.filter
def get_item(dicionario, chave):
    return dicionario.get(chave, chave)


@register.filter
def reais(v):
    """Valor para preencher campo de formulário em reais: vírgula e duas casas (812,40); desconhecido -> vazio."""
    if v is None or isinstance(v, str):  # texto já digitado volta como veio
        return v or ""
    return _virgula(v, 2).replace(".", "")


@register.filter
def ref4(v):
    """Referência por unidade para campo de formulário (até 4 casas, sem zeros à toa): 0,7416 / 0,05; vazio se None."""
    if v is None or isinstance(v, str):
        return v or ""
    txt = _virgula(v, 4).replace(".", "")
    return txt.rstrip("0").rstrip(",") if "," in txt else txt
