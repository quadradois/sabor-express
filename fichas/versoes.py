from .models import FichaVersao


def foto(ficha):
    s = str
    return {
        "tipo": ficha.tipo,
        "rendimento_g": None if ficha.rendimento_g is None else s(ficha.rendimento_g),
        "itens": [[c.item_id, c.item.nome, s(c.quantidade)]
                  for c in ficha.itens.select_related("item").order_by("ordem", "id")],
        "subpreparacoes": [[c.preparacao_id, c.preparacao.nome, s(c.quantidade_g)]
                           for c in ficha.subpreparacoes.select_related("preparacao").order_by("ordem", "id")],
        "proporcoes": [[p.preparacao_id, p.preparacao.nome, s(p.percentual)]
                       for p in ficha.proporcoes.select_related("preparacao").order_by("ordem", "id")],
        "etapas": [[e.instrucao, e.tempo_seg, e.ponto] for e in ficha.etapas.order_by("ordem", "id")],
    }


def salvar_versao(ficha, op=None):
    ultima = ficha.versoes.last()
    conteudo = foto(ficha)
    if ultima and ultima.conteudo == conteudo:
        return ultima
    return FichaVersao.objects.create(
        ficha=ficha, numero=ultima.numero + 1 if ultima else 1, conteudo=conteudo, operacao=op
    )


def versao_vigente(ficha):
    return ficha.versoes.last() or salvar_versao(ficha)
