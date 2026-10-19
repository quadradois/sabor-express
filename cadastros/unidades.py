from decimal import Decimal

from nucleo.operacoes import RegraViolada

from .models import Conversao

# (unidade, unidade_base) -> fator fixo
PADROES = {("kg", "g"): Decimal("1000"), ("L", "mL"): Decimal("1000")}


def para_base(item, quantidade: Decimal, unidade: str) -> Decimal:
    if unidade == item.unidade_base:
        return quantidade
    if (unidade, item.unidade_base) in PADROES:
        return quantidade * PADROES[(unidade, item.unidade_base)]
    conversao = Conversao.objects.filter(item=item, unidade=unidade).first()
    if conversao is None:
        raise RegraViolada(f"Cadastre o fator de '{unidade}' para '{item.nome}'.")
    return quantidade * conversao.fator
