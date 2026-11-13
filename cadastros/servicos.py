import unicodedata
from decimal import Decimal

from nucleo.operacoes import RegraViolada, executar

from .models import Item


def criar_tamanho(*, ficha_id: int, peso_g: Decimal, oleo_ref_un: Decimal | None = None,
                  indireto_ref_un: Decimal | None = None,
                  autor: str, canal: str = "web", chave: str | None = None) -> dict:
    """Cada tamanho de um salgado é um Item de tipo produto que compartilha a ficha.

    Sem `indireto_ref_un`, herda o do tamanho cadastrado mais recentemente que tenha valor (de qualquer
    salgado: mão de obra, energia e gás por unidade não dependem do recheio — Plano 8); `indireto_herdado_de`
    no retorno diz de qual. Sem nenhum, fica vazio ("não inclui indiretos")."""
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
        indireto, herdado = indireto_ref_un, None
        if indireto is None:
            modelo = (Item.objects.filter(tipo="produto", indireto_ref_un__isnull=False).order_by("-id").first())
            if modelo:
                indireto, herdado = modelo.indireto_ref_un, {"item_id": modelo.id, "nome": modelo.nome}
        i = Item.objects.create(nome=nome, tipo="produto", unidade_base="un", controla_validade=True,
                                ficha=ficha, peso_g=peso_g, oleo_ref_un=oleo_ref_un, indireto_ref_un=indireto)
        return {"item_id": i.id, "nome": nome, "indireto_ref_un": indireto, "indireto_herdado_de": herdado}

    return executar("criar_tamanho", func, autor=autor, canal=canal, chave=chave,
                    parametros={"ficha_id": ficha_id, "peso_g": peso_g, "oleo_ref_un": oleo_ref_un,
                                "indireto_ref_un": indireto_ref_un})


def salvar_referencias(*, produto_id, oleo_ref_un=None, indireto_ref_un=None, autor, canal="web",
                       chave=None) -> dict:
    """Muda o óleo e os indiretos de referência por unidade de um tamanho (R$; vazio = sem referência).
    Só pela tela (como o preço): o agente de voz não chama este serviço."""
    from nucleo.valores import decimal

    def ler(v, campo):
        if v in (None, ""):
            return None
        d = decimal(v, campo).quantize(Decimal("0.0001"))
        if d < 0:
            raise RegraViolada("A referência não pode ser negativa.")
        return d

    def func(op):
        p = Item.objects.filter(id=produto_id, tipo="produto").first()
        if p is None:
            raise RegraViolada("Produto não encontrado.")
        antes = {"oleo_ref_un": p.oleo_ref_un, "indireto_ref_un": p.indireto_ref_un}
        p.oleo_ref_un, p.indireto_ref_un = ler(oleo_ref_un, "oleo_ref_un"), ler(indireto_ref_un, "indireto_ref_un")
        p.save(update_fields=["oleo_ref_un", "indireto_ref_un"])
        return {"produto_id": p.id, "antes": antes,
                "depois": {"oleo_ref_un": p.oleo_ref_un, "indireto_ref_un": p.indireto_ref_un}}

    return executar("salvar_referencias", func, autor=autor, canal=canal, chave=chave,
                    parametros={"produto_id": produto_id, "oleo_ref_un": oleo_ref_un,
                                "indireto_ref_un": indireto_ref_un})


def _normal(s: str) -> str:
    """Minúsculas e sem acento: "ATACADÃO" e "Atacadao" são o mesmo nome (o iexact do SQLite só cobre ASCII)."""
    s = unicodedata.normalize("NFKD", s.casefold())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def _repetido(modelo, nome, excluir_id):
    alvo = _normal(nome)
    return next((x for x in modelo.objects.exclude(id=excluir_id).order_by("id") if _normal(x.nome) == alvo), None)


def salvar_fornecedor(*, nome, documento="", contato="", ativo=True, fornecedor_id=None,
                      autor: str, canal: str = "web", chave: str | None = None) -> dict:
    """Cria (sem `fornecedor_id`) ou altera um fornecedor. Fornecedor com compras não é apagado: inativa-se."""
    from .models import Fornecedor

    def func(op):
        n = (nome or "").strip()
        if not n:
            raise RegraViolada("Informe o nome do fornecedor.")
        if outro := _repetido(Fornecedor, n, fornecedor_id):
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


def salvar_cliente(*, nome, contato="", ativo=True, cliente_id=None,
                   autor: str, canal: str = "web", chave: str | None = None) -> dict:
    """Cria (sem `cliente_id`) ou altera um cliente. Nome não se repete, ignorando acento e caixa.
    Cliente com vendas não é apagado: inativa-se."""
    from .models import Cliente

    def func(op):
        n = (nome or "").strip()
        if not n:
            raise RegraViolada("Informe o nome do cliente.")
        if outro := _repetido(Cliente, n, cliente_id):
            raise RegraViolada(f"Já existe o cliente '{outro.nome}'.")
        if cliente_id is None:
            c = Cliente(nome=n)
        else:
            c = Cliente.objects.filter(id=cliente_id).first()
            if c is None:
                raise RegraViolada("Cliente não encontrado.")
        c.nome, c.contato, c.ativo = n, (contato or "").strip(), bool(ativo)
        c.save()
        return {"cliente_id": c.id, "nome": c.nome}

    return executar("salvar_cliente", func, autor=autor, canal=canal, chave=chave,
                    parametros={"cliente_id": cliente_id, "nome": nome, "contato": contato, "ativo": ativo})
