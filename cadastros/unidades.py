from decimal import Decimal

from nucleo.operacoes import RegraViolada

from .models import Conversao

# (unidade, unidade_base) -> fator fixo
PADROES = {("kg", "g"): Decimal("1000"), ("L", "mL"): Decimal("1000")}
_CANONICAS = {u.casefold(): u for u in ("g", "kg", "mL", "L", "un")}


def fator(item, unidade: str) -> tuple[str, Decimal]:
    """(unidade normalizada, quantas unidades base há em 1 unidade informada)."""
    unidade = unidade.strip()
    unidade = _CANONICAS.get(unidade.casefold(), unidade)
    if unidade == item.unidade_base:
        return unidade, Decimal(1)
    if (unidade, item.unidade_base) in PADROES:
        return unidade, PADROES[(unidade, item.unidade_base)]
    conversao = Conversao.objects.filter(item=item, unidade__iexact=unidade).first()
    if conversao is None:
        raise RegraViolada(f"Cadastre o fator de '{unidade}' para '{item.nome}'.")
    return conversao.unidade, conversao.fator


def para_base(item, quantidade: Decimal, unidade: str) -> Decimal:
    return quantidade * fator(item, unidade)[1]
