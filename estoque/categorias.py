"""As três categorias de venda (Plano 10): Congelado, Frito e Assado.

Todo salgado é vendido congelado (cru) ou já finalizado, frito ou assado conforme o acabamento do tipo
(`Ficha.acabamento`). Fala e telas dizem só a categoria; forma e conservação continuam separadas no banco.
"""

from .models import ESTADOS, FORMAS

ACABAMENTOS = [("frito", "Frito"), ("assado", "Assado")]
FINALIZADAS = tuple(a for a, _ in ACABAMENTOS)  # formas que já passaram pelo óleo ou pelo forno
VERBO = {"frito": "fritar", "assado": "assar"}
PARTICIPIO = {"frito": "fritas", "assado": "assadas"}  # "40 unidades fritas"


def categoria(forma, estado) -> str:
    """cru+congelado → "congelado"; frito+fresco → "frito"; assado+fresco → "assado". O que não é de
    venda (bastidor) sai por extenso: "resfriado", "cru", "frito congelado", "assado resfriado"."""
    forma, estado = forma or "", estado or ""
    if not forma or not estado:
        return forma or estado
    if forma == "cru":
        return "cru" if estado == "fresco" else estado
    return forma if estado == "fresco" else f"{forma} {estado}"


def forma_estado(categoria_dita) -> tuple[str, str] | None:
    """O contrário, para a entrada: "congelado" → ("cru", "congelado"); "frito" → ("frito", "fresco")."""
    for f, _ in FORMAS:
        for e, _ in ESTADOS:
            if categoria(f, e) == categoria_dita:
                return f, e
    return None


def acabamento(produto) -> str:
    """Acabamento do tipo do salgado (a ficha); produto sem ficha conta como frito."""
    return produto.ficha.acabamento if produto.ficha_id else "frito"


def checar_forma(produto, forma):
    """Produto de acabamento frito não tem nada assado, e vice-versa. Cru vale para os dois."""
    from nucleo.operacoes import RegraViolada

    a = acabamento(produto)
    if forma in FINALIZADAS and forma != a:
        raise RegraViolada(f"'{produto.nome}' é {a}, não {forma}: o acabamento desse salgado é {a}. "
                           f"Use cru ou {a}.")
