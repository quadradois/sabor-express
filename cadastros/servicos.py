from decimal import Decimal

from nucleo.operacoes import RegraViolada, executar

from .models import Item


def criar_tamanho(*, ficha_id: int, peso_g: Decimal, oleo_ref_un: Decimal | None = None,
                  autor: str, canal: str = "web", chave: str | None = None) -> dict:
    """Cada tamanho de um salgado é um Item de tipo produto que compartilha a ficha."""
    from fichas.models import Ficha
    from web.templatetags.formato import quantidade

    def func(op):
        ficha = Ficha.objects.filter(id=ficha_id, tipo="produto").first()
        if not ficha:
            raise RegraViolada("Escolha uma ficha de produto.")
        if peso_g <= 0:
            raise RegraViolada("O peso de cada unidade deve ser maior que zero.")
        nome = f"{ficha.nome} {quantidade(peso_g, 'un').removesuffix(' un')} g"
        if Item.objects.filter(nome=nome).exists():
            raise RegraViolada(f"Esse tamanho já existe: {nome}.")
        i = Item.objects.create(nome=nome, tipo="produto", unidade_base="un", controla_validade=True,
                                ficha=ficha, peso_g=peso_g, oleo_ref_un=oleo_ref_un)
        return {"item_id": i.id, "nome": nome}

    return executar("criar_tamanho", func, autor=autor, canal=canal, chave=chave,
                    parametros={"ficha_id": ficha_id, "peso_g": peso_g, "oleo_ref_un": oleo_ref_un})
