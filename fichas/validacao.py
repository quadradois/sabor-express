from decimal import Decimal

from nucleo.operacoes import RegraViolada


def _fmt(d):
    return format(d.normalize(), "f")


def _checar_ciclo(ficha, caminho):
    caminho = caminho + [ficha]
    for c in ficha.subpreparacoes.select_related("preparacao"):
        sub = c.preparacao
        if sub in caminho:
            nomes = " → ".join(f.nome for f in caminho + [sub])
            raise RegraViolada(f"Referência circular: {nomes}.")
        _checar_ciclo(sub, caminho)


def validar_ficha(ficha):
    for c in [*ficha.proporcoes.select_related("preparacao"), *ficha.subpreparacoes.select_related("preparacao")]:
        if c.preparacao.tipo != "preparacao":
            raise RegraViolada(f"'{c.preparacao.nome}' não é uma preparação.")
    if ficha.tipo == "produto":
        if ficha.itens.exists() or ficha.subpreparacoes.exists():
            raise RegraViolada("Produto não pode ter itens nem subpreparações; use proporções.")
        props = list(ficha.proporcoes.all())
        if not props:
            raise RegraViolada("O produto precisa ter ao menos uma proporção.")
        soma = sum((p.percentual for p in props), Decimal(0))
        if soma != 100:
            raise RegraViolada(f"As proporções somam {_fmt(soma)}%, precisam somar 100%.")
        return
    if ficha.proporcoes.exists():
        raise RegraViolada("Preparação não pode ter proporções.")
    if ficha.rendimento_g is None or ficha.rendimento_g <= 0:
        raise RegraViolada("A preparação precisa de rendimento maior que zero.")
    _checar_ciclo(ficha, [])
