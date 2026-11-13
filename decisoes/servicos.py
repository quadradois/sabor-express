"""Caixa de decisões: criar, aprovar, recusar e manter em dia o que espera o "ok" do dono.

Diferente da `agente.Proposta` (confirmação imediata de uma conversa, 5 minutos), a decisão vive até o
dono decidir ou até a situação que a gerou deixar de existir. O mecanismo de execução é o mesmo: a
decisão guarda a operação e os parâmetros prontos, e aprovar chama o serviço com a `chave` da decisão,
então aprovar de novo nunca executa duas vezes.
"""

import uuid

from django.utils import timezone

from nucleo.models import RegistroOperacao
from nucleo.operacoes import RegraViolada, _json, executar
from producao.servicos import conciliar_consumo

from .models import Decisao

# operações que uma decisão pode executar ao ser aprovada; os serviços aceitam os parâmetros como
# voltam do JSON (números e datas como texto)
OPERACOES = {
    "conciliar_consumo": conciliar_consumo,
}


def _nova(op, *, origem, assunto, texto, detalhes, operacao, parametros, expira_em, autor, canal):
    return Decisao.objects.create(
        origem=origem, assunto=assunto or f"{origem}:{uuid.uuid4().hex}", texto=texto,
        detalhes=_json(detalhes or {}), operacao=operacao, parametros=_json(parametros) if operacao else None,
        chave=f"decisao:{uuid.uuid4().hex}", criada_por=autor, canal=canal, criacao=op, expira_em=expira_em)


def _checar(origem, texto, operacao, parametros):
    if not (origem or "").strip():
        raise RegraViolada("Informe a origem da decisão.")
    if not (texto or "").strip():
        raise RegraViolada("Informe o texto da decisão.")
    if operacao and operacao not in OPERACOES:
        raise RegraViolada(f"A operação '{operacao}' não pode ser decidida pela caixa.")
    if operacao and not isinstance(parametros, dict):
        raise RegraViolada("Informe os parâmetros da operação.")


def criar_decisao(*, origem, texto, assunto="", operacao="", parametros=None, detalhes=None, expira_em=None,
                  autor, canal="web", chave=None) -> dict:
    """Põe um item na caixa. Já havendo decisão vigente com o mesmo `assunto`, não cria outra."""

    def func(op):
        _checar(origem, texto, operacao, parametros)
        if assunto and (d := Decisao.objects.filter(assunto=assunto, vigente=True).first()):
            return {"decisao_id": d.id, "criada": False, "situacao": d.situacao}
        d = _nova(op, origem=origem.strip(), assunto=assunto, texto=texto.strip(), detalhes=detalhes,
                  operacao=operacao, parametros=parametros, expira_em=expira_em, autor=autor, canal=canal)
        return {"decisao_id": d.id, "criada": True, "situacao": d.situacao}

    return executar("criar_decisao", func, autor=autor, canal=canal, chave=chave,
                    parametros={"origem": origem, "assunto": assunto, "texto": texto, "operacao": operacao,
                                "parametros": parametros, "detalhes": detalhes, "expira_em": expira_em})


def _resposta(d) -> dict:
    return {"decisao_id": d.id, "situacao": d.situacao, "tipo": d.tipo, "operacao": d.operacao,
            "texto": d.texto, "resultado": d.resultado}


def _pendente(d) -> Decisao:
    if d is None:
        raise RegraViolada("Decisão não encontrada.")
    if d.situacao == "recusada":
        raise RegraViolada(f"Essa decisão já foi recusada por {d.decidida_por} ({d.motivo}).")
    if d.situacao == "aprovada":
        raise RegraViolada(f"Essa decisão já foi aprovada por {d.decidida_por}.")
    if d.situacao in ("expirada", "sem_efeito") or (d.expira_em and d.expira_em <= timezone.now()):
        raise RegraViolada("Essa decisão não vale mais: a situação mudou ou o prazo passou. "
                           "Se ainda fizer sentido, a rotina gera de novo.")
    return d


def aprovar_decisao(*, decisao_id, autor, canal="web", chave=None) -> dict:
    """Aprova (decisão) ou dá ciência (aviso). A operação roda pelo núcleo junto com a aprovação:
    as duas gravam ou nenhuma. Já aprovada: devolve o resultado guardado, sem executar de novo.

    Recusa do núcleo (ex.: o lote foi usado desde então) sobe como RegraViolada; a decisão continua
    pendente e a tentativa fica na trilha (`aprovar_decisao` com status "erro").
    """
    d = Decisao.objects.filter(id=decisao_id).first()
    if d is not None and d.situacao == "aprovada":
        return _resposta(d)

    def func(op):
        d = _pendente(Decisao.objects.select_for_update().filter(id=decisao_id).first())
        if d.operacao:
            d.resultado = OPERACOES[d.operacao](**d.parametros, autor=autor, canal=canal, chave=d.chave)
            d.registro = RegistroOperacao.objects.get(chave=d.chave)
        d.situacao, d.decidida_em, d.decidida_por, d.decisao_operacao = "aprovada", timezone.now(), autor, op
        d.save()
        return _resposta(d)

    return executar("aprovar_decisao", func, autor=autor, canal=canal, chave=chave,
                    parametros={"decisao_id": decisao_id})


def recusar_decisao(*, decisao_id, motivo, autor, canal="web", chave=None) -> dict:
    """Recusa com motivo. Aviso não se recusa: dá-se ciência (`aprovar_decisao`)."""

    def func(op):
        d = _pendente(Decisao.objects.select_for_update().filter(id=decisao_id).first())
        if not d.operacao:
            raise RegraViolada("Aviso não se recusa: dê ciência.")
        if not (motivo or "").strip():
            raise RegraViolada("Informe o motivo da recusa.")
        d.situacao, d.decidida_em, d.decidida_por = "recusada", timezone.now(), autor
        d.motivo, d.decisao_operacao = motivo.strip(), op
        d.save()
        return _resposta(d)

    return executar("recusar_decisao", func, autor=autor, canal=canal, chave=chave,
                    parametros={"decisao_id": decisao_id, "motivo": motivo})


def expirar_decisoes(*, agora=None, autor="rotina", canal="sistema", chave=None) -> dict:
    """Marca como expiradas as pendentes cujo prazo passou (deixam de ser vigentes: a rotina pode gerar de novo)."""

    def func(op):
        n = 0
        for d in Decisao.objects.filter(situacao="pendente", expira_em__lte=agora or timezone.now()):
            d.situacao, d.vigente, d.decidida_em, d.decidida_por = "expirada", False, timezone.now(), autor
            d.motivo, d.decisao_operacao = "O prazo passou sem decisão.", op
            d.save()
            n += 1
        return {"expiradas": n}

    return executar("expirar_decisoes", func, autor=autor, canal=canal, chave=chave)


def sincronizar(*, origem, itens, autor="rotina", canal="sistema", chave=None) -> dict:
    """Deixa a caixa igual ao retrato atual de um gerador (idempotente: rodar de novo não duplica).

    `itens` = [{assunto, texto, detalhes?, operacao?, parametros?, expira_em?}], o que o gerador vê agora.
    - assunto novo → decisão nova;
    - assunto já vigente → nada muda, exceto texto e números de uma pendente (o saldo mudou, por exemplo);
      operação e parâmetros nunca mudam (fazem parte do assunto);
    - vigente que sumiu do retrato → deixa de ser vigente e, se estava pendente, fica "sem efeito".
    """

    def func(op):
        atuais = {i["assunto"]: i for i in itens}
        contagem = {"criadas": 0, "atualizadas": 0, "sem_efeito": 0}
        for d in Decisao.objects.filter(origem=origem, vigente=True):
            i = atuais.pop(d.assunto, None)
            if i is None:
                d.vigente = False
                if d.situacao == "pendente":
                    d.situacao, d.decidida_em, d.decidida_por = "sem_efeito", timezone.now(), autor
                    d.motivo, d.decisao_operacao = "A situação deixou de existir.", op
                    contagem["sem_efeito"] += 1
                d.save()
            elif d.situacao == "pendente":
                texto, detalhes = i["texto"], _json(i.get("detalhes") or {})
                if (texto, detalhes) != (d.texto, d.detalhes):
                    d.texto, d.detalhes = texto, detalhes
                    d.save(update_fields=["texto", "detalhes"])
                    contagem["atualizadas"] += 1
        for i in atuais.values():
            _checar(origem, i["texto"], i.get("operacao", ""), i.get("parametros"))
            _nova(op, origem=origem, assunto=i["assunto"], texto=i["texto"], detalhes=i.get("detalhes"),
                  operacao=i.get("operacao", ""), parametros=i.get("parametros"), expira_em=i.get("expira_em"),
                  autor=autor, canal=canal)
            contagem["criadas"] += 1
        return {"origem": origem, **contagem,
                "pendentes": Decisao.objects.filter(origem=origem, vigente=True, situacao="pendente").count()}

    return executar("gerar_decisoes", func, autor=autor, canal=canal, chave=chave, parametros={"origem": origem})
