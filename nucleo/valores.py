"""Leitura de valores vindos de tela, agente ou proposta reexecutada (Decimal/data como texto)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .operacoes import RegraViolada

CENTAVO = Decimal("0.01")


def decimal(v, campo: str) -> Decimal:
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        raise RegraViolada(f"Valor inválido em '{campo}'.") from None


def reais(v, campo: str) -> Decimal:
    return decimal(v, campo).quantize(CENTAVO, ROUND_HALF_UP)


def data(v, campo: str) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        raise RegraViolada(f"Data inválida em '{campo}' (use AAAA-MM-DD).") from None
