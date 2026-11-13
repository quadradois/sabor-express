from django.utils import timezone

from nucleo.operacoes import RegraViolada, executar

from .lotes import nome_lote
from .models import ESTADOS, FORMAS, EtiquetaImpressa, Lote, Movimento
from .servicos import saldo_lote, validade_porcao


def dados_etiqueta(lote, estado: str) -> dict:
    """Dados da etiqueta. `dia_producao` (o número do dia, para imprimir em destaque) e `nome_lote` ("lote do dia
    8") são o jeito como a cozinha chama o lote (Plano 9); `lote` continua sendo o código."""
    entrada = (Movimento.objects.filter(lote=lote, estado=estado, quantidade__gt=0)
               .order_by("-criado_em", "-id").first())
    fabricacao = timezone.localdate(lote.criado_em)
    return {"produto": lote.item.nome, "lote": lote.codigo, "fabricacao": fabricacao,
            "dia_producao": fabricacao.day, "nome_lote": nome_lote(lote),
            "validade": validade_porcao(lote, estado), "validade_manual": bool(entrada and entrada.validade_manual),
            "conservacao": dict(ESTADOS).get(estado, estado), "forma": dict(FORMAS).get(lote.forma, lote.forma),
            "quantidade": saldo_lote(lote, estado)}


def registrar_impressao(*, lote_id: int, estado: str, copias: int, autor: str, canal: str = "web",
                        chave: str | None = None) -> dict:
    parametros = {"lote_id": lote_id, "estado": estado, "copias": copias}

    def func(op):
        if copias < 1:
            raise RegraViolada("Informe ao menos 1 cópia.")
        if estado not in dict(ESTADOS):
            raise RegraViolada("Estado inválido.")
        try:
            lote = Lote.objects.get(id=lote_id)
        except Lote.DoesNotExist:
            raise RegraViolada("Lote não encontrado.")
        reimp = EtiquetaImpressa.objects.filter(lote=lote, estado=estado).exists()
        e = EtiquetaImpressa.objects.create(lote=lote, estado=estado, copias=copias, reimpressao=reimp, operacao=op)
        return {"etiqueta_id": e.id, "reimpressao": reimp}

    return executar("registrar_impressao", func, autor=autor, canal=canal, chave=chave, parametros=parametros)
