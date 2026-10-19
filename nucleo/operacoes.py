import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from .models import RegistroOperacao


class RegraViolada(Exception):
    """Erro de regra de negócio; a mensagem (pt-BR) é mostrada ao usuário."""


def executar(nome, func, *, autor, canal="web", chave=None):
    """Único caminho de gravação: atômico, idempotente por chave e auditado."""
    if chave:
        anterior = RegistroOperacao.objects.filter(chave=chave).first()
        if anterior and anterior.status == "sucesso":
            return anterior.resultado
        if anterior:
            anterior.delete()  # falhou antes: libera a chave para nova tentativa
    try:
        with transaction.atomic():
            op = RegistroOperacao.objects.create(
                nome=nome, chave=chave, canal=canal, autor=autor, status="sucesso"
            )
            # Decimal/datas viram str via DjangoJSONEncoder
            resultado = json.loads(json.dumps(func(op), cls=DjangoJSONEncoder))
            op.resultado = resultado
            op.save(update_fields=["resultado"])
    except Exception as e:
        RegistroOperacao.objects.create(
            nome=nome, chave=chave, canal=canal, autor=autor, status="erro", erro=str(e)
        )
        raise
    return resultado
