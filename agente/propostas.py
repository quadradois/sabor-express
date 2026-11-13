"""Propostas: gravações que só acontecem depois do "sim" (alçada nível 2).

A confirmação está na estrutura, não no prompt: quem propõe não grava nada,
só cria uma `Proposta` pendente com validade curta. Gravar exige
`confirmar(id)`, que executa a operação real pelo núcleo com a chave da
proposta — confirmar duas vezes devolve o mesmo resultado sem duplicar.

Antes de propor, a operação é **simulada**: roda inteira pelo núcleo dentro de
uma transação desfeita no fim. Assim toda regra do núcleo (estoque, validade,
produção encerrada...) é checada antes de perguntar "confirma?", e o resumo
pode citar valores que só o núcleo calcula (validade nova, nome do tamanho).
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from django.db import transaction
from django.utils import timezone

from cadastros.servicos import criar_tamanho
from compras.servicos import (cancelar_compra, devolver_ao_fornecedor, encerrar_pendencia, estornar_recebimento,
                              receber_bonificacao, receber_compra, registrar_compra)
from decisoes.servicos import aprovar_decisao
from estoque.servicos import entrada_manual, transferir_estado
from nucleo.models import RegistroOperacao
from nucleo.operacoes import RegraViolada, _json
from financeiro.servicos import estornar_pagamento, registrar_pagamento
from producao.servicos import cancelar_producao, concluir_producao, conciliar_consumo, iniciar_producao

from .models import Proposta

VALIDADE = timedelta(minutes=5)


@dataclass(frozen=True)
class Operacao:
    func: Callable[..., dict]
    decimais: tuple = ()  # parâmetros que voltam do JSON como str e o serviço quer Decimal
    datas: tuple = ()


def registrar_e_receber_compra(*, recebimento, autor, canal, chave=None, **compra) -> dict:
    """"Comprei e já chegou": lança a compra e recebe tudo, cada passo uma operação do núcleo.

    `recebimento` = [{"validade", "lote_codigo"}] na ordem das linhas. O recebimento usa a chave
    da proposta + ":receber": confirmar de novo depois de uma falha no meio só refaz o que faltou.
    """
    r = registrar_compra(**compra, autor=autor, canal=canal, chave=chave)
    linhas = [{"linha_id": l["linha_id"], "quantidade": c["quantidade"], "unidade": c["unidade"], **extra}
              for l, c, extra in zip(r["linhas"], compra["linhas"], recebimento)]
    rec = receber_compra(compra_id=r["compra_id"], linhas=linhas, autor=autor, canal=canal,
                         chave=f"{chave}:receber" if chave else None)
    return {**r, "recebimento": rec}


OPERACOES = {
    "iniciar_producao": Operacao(iniciar_producao),
    "concluir_producao": Operacao(concluir_producao, datas=("validade_manual",)),
    "cancelar_producao": Operacao(cancelar_producao),
    "transferir_estado": Operacao(transferir_estado, datas=("validade_manual",)),
    "entrada_manual": Operacao(entrada_manual, decimais=("quantidade", "custo_total"), datas=("validade",)),
    "criar_tamanho": Operacao(criar_tamanho, decimais=("peso_g", "oleo_ref_un")),
    # compras e contas a pagar: os serviços aceitam números e datas como texto
    "registrar_compra": Operacao(registrar_compra),
    "registrar_e_receber_compra": Operacao(registrar_e_receber_compra),
    "receber_compra": Operacao(receber_compra),
    "encerrar_pendencia": Operacao(encerrar_pendencia),
    "cancelar_compra": Operacao(cancelar_compra),
    "estornar_recebimento": Operacao(estornar_recebimento),
    "devolver_ao_fornecedor": Operacao(devolver_ao_fornecedor),
    "receber_bonificacao": Operacao(receber_bonificacao),
    "registrar_pagamento": Operacao(registrar_pagamento),
    "estornar_pagamento": Operacao(estornar_pagamento),
    "conciliar_consumo": Operacao(conciliar_consumo),
    # caixa de decisões: aprovar executa a operação guardada na decisão (uma vez só, com a chave dela)
    "aprovar_decisao": Operacao(aprovar_decisao),
}


def _parametros(op: Operacao, salvos: dict) -> dict:
    p = dict(salvos)
    for k in op.decimais:
        if p.get(k) is not None:
            p[k] = Decimal(p[k])
    for k in op.datas:
        if p.get(k):
            p[k] = date.fromisoformat(p[k])
    return p


def simular(operacao: str, parametros: dict, resumir: Callable[[dict], str]) -> str:
    """Roda a operação pelo núcleo e desfaz tudo; devolve o resumo calculado lá dentro.

    Recusa do núcleo sobe como RegraViolada, sem deixar rastro (é só uma pergunta).
    """
    func = OPERACOES[operacao].func
    with transaction.atomic():
        try:
            resultado = func(**parametros, autor="simulacao", canal="simulacao")
            return resumir(resultado)
        finally:
            transaction.set_rollback(True)


def propor(operacao: str, parametros: dict, resumir: Callable[[dict], str], *, autor: str, canal: str) -> Proposta:
    resumo = simular(operacao, parametros, resumir)
    return Proposta.objects.create(
        operacao=operacao, parametros=_json(parametros), resumo=resumo, autor=autor, canal=canal,
        chave=f"proposta:{uuid.uuid4().hex}", expira_em=timezone.now() + VALIDADE)


def _pendente(proposta_id) -> Proposta:
    p = Proposta.objects.filter(id=proposta_id).first()
    if p is None:
        raise RegraViolada("Proposta não encontrada.")
    if p.estado == "pendente" and timezone.now() > p.expira_em:
        p.estado, p.resolvida_em = "expirada", timezone.now()
        p.save(update_fields=["estado", "resolvida_em"])
    if p.estado == "expirada":
        raise RegraViolada(f"A proposta expirou sem confirmação ({p.resumo}). Peça de novo.")
    if p.estado == "recusada":
        raise RegraViolada(f"Essa proposta foi recusada ({p.resumo}). Peça de novo.")
    return p


def confirmar(proposta_id, *, autor: str) -> Proposta:
    """Executa a proposta. Já confirmada: devolve-a como está (não executa de novo).

    Sem transação em volta de propósito: `executar` grava (ou registra a recusa
    na trilha) por conta própria, e a chave da proposta torna a repetição
    segura se algo falhar entre a operação e a atualização da proposta.
    """
    p = _pendente(proposta_id)
    if p.estado == "confirmada":
        return p
    op = OPERACOES[p.operacao]
    try:
        p.resultado = op.func(**_parametros(op, p.parametros), autor=p.autor, canal=p.canal, chave=p.chave)
    except RegraViolada as e:
        # fica pendente: o núcleo pode aceitar depois (ex.: entrou estoque) enquanto valer
        Proposta.objects.filter(id=p.id).update(erro=str(e))
        raise
    p.estado, p.resolvida_em, p.resolvida_por, p.erro = "confirmada", timezone.now(), autor, ""
    p.registro = RegistroOperacao.objects.get(chave=p.chave)
    p.save()
    return p


def recusar(proposta_id, *, autor: str) -> Proposta:
    p = _pendente(proposta_id)
    if p.estado == "confirmada":
        raise RegraViolada(f"Essa proposta já foi confirmada e gravada ({p.resumo}).")
    p.estado, p.resolvida_em, p.resolvida_por = "recusada", timezone.now(), autor
    p.save(update_fields=["estado", "resolvida_em", "resolvida_por"])
    return p
