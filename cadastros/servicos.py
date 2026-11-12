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


def salvar_fornecedor(*, nome, documento="", contato="", ativo=True, fornecedor_id=None,
                      autor: str, canal: str = "web", chave: str | None = None) -> dict:
    """Cria (sem `fornecedor_id`) ou altera um fornecedor. Fornecedor com compras não é apagado: inativa-se."""
    from .models import Fornecedor

    def func(op):
        n = (nome or "").strip()
        if not n:
            raise RegraViolada("Informe o nome do fornecedor.")
        outro = Fornecedor.objects.filter(nome__iexact=n).exclude(id=fornecedor_id).first()
        if outro:
            raise RegraViolada(f"Já existe o fornecedor '{outro.nome}'.")
        if fornecedor_id is None:
            f = Fornecedor(nome=n)
        else:
            f = Fornecedor.objects.filter(id=fornecedor_id).first()
            if f is None:
                raise RegraViolada("Fornecedor não encontrado.")
        f.nome, f.documento, f.contato, f.ativo = n, (documento or "").strip(), (contato or "").strip(), bool(ativo)
        f.save()
        return {"fornecedor_id": f.id, "nome": f.nome}

    return executar("salvar_fornecedor", func, autor=autor, canal=canal, chave=chave,
                    parametros={"fornecedor_id": fornecedor_id, "nome": nome, "documento": documento,
                                "contato": contato, "ativo": ativo})
