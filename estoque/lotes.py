"""Como o lote é chamado na cozinha e o "aviso com motivo" do vencido (Plano 9).

Na cozinha ninguém fala "lote 251108-12": fala "lote do dia 8", o dia em que foi feito (a etiqueta traz esse
dia em destaque). `nome_lote` dá esse nome, igual para telas e agente. `checar_vencido` é a regra única do
vencido: sem motivo, recusa dizendo o lote, o dia em que venceu e que dá para seguir informando o motivo;
com motivo, deixa seguir (o motivo fica gravado na operação e no movimento).
"""

from datetime import date, datetime, time, timedelta

from django.utils import timezone

from nucleo.operacoes import RegraViolada

from .models import Lote

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]
ORDINAIS = {2: "segundo", 3: "terceiro", 4: "quarto", 5: "quinto", 6: "sexto", 7: "sétimo", 8: "oitavo",
            9: "nono", 10: "décimo"}


def dia_producao(lote) -> date:
    """O dia em que o lote foi feito (produção, fritura) ou entrou (compra, entrada manual), no fuso da cozinha."""
    return timezone.localdate(lote.criado_em)


def _ordem_no_dia(lote, dia) -> int:
    """1 para o primeiro lote do mesmo item e forma feito naquele dia, 2 para o segundo..."""
    inicio = timezone.make_aware(datetime.combine(dia, time.min))
    fim = inicio + timedelta(days=1)
    mesmos = (Lote.objects.filter(item_id=lote.item_id, forma=lote.forma, criado_em__gte=inicio, criado_em__lt=fim)
              .order_by("criado_em", "id").values_list("id", flat=True))
    ids = list(mesmos)
    return ids.index(lote.id) + 1 if lote.id in ids else 1


def nome_lote(lote, *, hoje=None) -> str:
    """"lote do dia 8"; de outro mês, "lote do dia 28 de outubro"; o segundo do mesmo item e forma feito no
    mesmo dia, "segundo lote do dia 8". O dia é o da produção (`dia_producao`), não a validade."""
    hoje = hoje or timezone.localdate()
    dia = dia_producao(lote)
    texto = f"dia {dia.day}"
    if (dia.year, dia.month) != (hoje.year, hoje.month):
        texto += f" de {MESES[dia.month - 1]}"
        if dia.year != hoje.year:
            texto += f" de {dia.year}"
    n = _ordem_no_dia(lote, dia)
    return f"lote do {texto}" if n == 1 else f"{ORDINAIS.get(n, f'{n}º')} lote do {texto}"


def dados_lote(lote, *, hoje=None) -> dict:
    """O que telas e agente mostram/falam de um lote: código, dia da produção e o nome falável."""
    return {"lote_id": lote.id, "codigo": lote.codigo or "sem lote", "dia_producao": dia_producao(lote),
            "nome": nome_lote(lote, hoje=hoje)}


def vencida(validade, quando) -> bool:
    return validade is not None and validade < quando


def checar_vencido(lote, estado, validade, *, quando, motivo_vencido="", acao="usar", regra="") -> str:
    """Regra única do vencido (decisão do dono: aviso com motivo, nada de trava).

    Porção válida em `quando`: devolve "". Vencida sem motivo: recusa dizendo o lote, o dia em que venceu e
    que dá para seguir informando o motivo (`regra`, texto ou função que o devolve, troca a mensagem inteira; quem passa diz o lote, o dia e o
    motivo). Vencida com motivo: devolve o motivo (limpo) para gravar."""
    if not vencida(validade, quando):
        return ""
    motivo = (motivo_vencido or "").strip()
    if motivo:
        return motivo
    if callable(regra):
        regra = regra()
    raise RegraViolada(regra or f"{texto_vencido(lote, estado, validade)} Lote vencido só sai com um motivo: para "
                                f"{acao} mesmo assim, informe o motivo.")


def texto_vencido(lote, estado, validade) -> str:
    conservacao = f", {estado}," if estado else ""
    return f"O {nome_lote(lote)} de '{lote.item.nome}'{conservacao} venceu em {validade:%d/%m}."
