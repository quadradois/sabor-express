from dataclasses import dataclass
from decimal import Decimal

from cadastros.models import Item
from estoque.servicos import saldo
from fichas.models import Etapa, Ficha
from fichas.validacao import validar_ficha
from nucleo.operacoes import RegraViolada


@dataclass(frozen=True)
class Linha:
    item_id: int
    nome: str
    unidade_base: str
    quantidade: Decimal
    falta: Decimal


@dataclass(frozen=True)
class Bloco:
    nome: str
    total_g: Decimal
    linhas: list[Linha]
    etapas: list[Etapa]


@dataclass(frozen=True)
class ReceitaEscalada:
    produto: str
    unidades: int
    peso_unitario_g: Decimal
    total_g: Decimal
    blocos: list[Bloco]


def _expandir(prep, alvo_g, blocos):
    """Pós-ordem: sub-preparações entram na lista antes da preparação que as usa."""
    validar_ficha(prep)
    fator = alvo_g / prep.rendimento_g
    for c in prep.subpreparacoes.select_related("preparacao").order_by("ordem", "id"):
        _expandir(c.preparacao, c.quantidade_g * fator, blocos)
    linhas = [
        Linha(c.item_id, c.item.nome, c.item.unidade_base, c.quantidade * fator, Decimal(0))
        for c in prep.itens.select_related("item").order_by("ordem", "id")
    ]
    blocos.append(Bloco(prep.nome, alvo_g, linhas, list(prep.etapas.order_by("ordem", "id"))))


def escalar(ficha_produto: Ficha, unidades: int, peso_unitario_g: Decimal) -> ReceitaEscalada:
    if ficha_produto.tipo != "produto":
        raise RegraViolada("Só é possível escalar uma ficha de produto.")
    if unidades <= 0:
        raise RegraViolada("A quantidade de unidades deve ser maior que zero.")
    if peso_unitario_g <= 0:
        raise RegraViolada("O peso unitário deve ser maior que zero.")
    validar_ficha(ficha_produto)
    total_g = unidades * peso_unitario_g
    blocos = []
    for p in ficha_produto.proporcoes.select_related("preparacao").order_by("ordem", "id"):
        _expandir(p.preparacao, total_g * p.percentual / 100, blocos)
    etapas = list(ficha_produto.etapas.order_by("ordem", "id"))
    if etapas:
        blocos.append(Bloco("Montagem", total_g, [], etapas))

    necessidade = {}
    for b in blocos:
        for l in b.linhas:
            necessidade[l.item_id] = necessidade.get(l.item_id, Decimal(0)) + l.quantidade
    faltas = {
        i.id: max(Decimal(0), necessidade[i.id] - saldo(i))
        for i in Item.objects.filter(id__in=necessidade)
    }
    blocos = [
        Bloco(b.nome, b.total_g, [
            Linha(l.item_id, l.nome, l.unidade_base, l.quantidade, faltas[l.item_id]) for l in b.linhas
        ], b.etapas)
        for b in blocos
    ]
    return ReceitaEscalada(ficha_produto.nome, unidades, peso_unitario_g, total_g, blocos)
