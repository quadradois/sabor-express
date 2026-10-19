import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction

from .models import RegistroOperacao


class RegraViolada(Exception):
    """Erro de regra de negócio; a mensagem (pt-BR) é mostrada ao usuário."""


def _sucesso(chave):
    return RegistroOperacao.objects.filter(chave=chave, status="sucesso").first()


def _json(v):
    # Decimal/datas viram str via DjangoJSONEncoder; chaves ordenadas para comparar
    return json.loads(json.dumps(v, cls=DjangoJSONEncoder, sort_keys=True))


def _repeticao(anterior, nome, parametros):
    if anterior.nome != nome or anterior.parametros != parametros:
        raise RegraViolada("Esta chave já foi usada para outra operação.")
    return anterior.resultado


def executar(nome, func, *, autor, canal="web", chave=None, parametros: dict | None = None):
    """Único caminho de gravação: atômico, idempotente por chave e auditado."""
    chave = chave or None
    parametros = _json(parametros)
    if chave and (anterior := _sucesso(chave)):
        return _repeticao(anterior, nome, parametros)
    try:
        with transaction.atomic():
            op = RegistroOperacao.objects.create(
                nome=nome, chave=chave, canal=canal, autor=autor, status="sucesso",
                parametros=parametros,
            )
            resultado = _json(func(op))
            op.resultado = resultado
            op.save(update_fields=["resultado"])
    except Exception as e:
        # corrida: outra chamada com a mesma chave gravou primeiro
        if isinstance(e, IntegrityError) and chave and (anterior := _sucesso(chave)):
            return _repeticao(anterior, nome, parametros)
        try:
            # chave=None mantém a chave livre para nova tentativa; fica na trilha
            RegistroOperacao.objects.create(
                nome=nome, canal=canal, autor=autor, status="erro", parametros=parametros,
                erro=f"[chave={chave}] {e}" if chave else str(e),
            )
        except Exception:
            pass  # nunca mascarar a exceção original
        raise
    return resultado
