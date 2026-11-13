"""Consultas da caixa de decisões, do resumo do dia e do histórico de operações (só leitura).

Devolvem dicts com Decimal, date e datetime, para a tela e para o agente (que serializa em JSON).
Nenhuma regra nova: os números vêm das consultas de estoque, compras, financeiro e produção.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

from compras.consultas import compras_em_aberto
from estoque.servicos import consumos_pendentes, itens_abaixo_do_minimo, porcoes
from financeiro.consultas import (avisos_de_ajuste, contas_a_vencer, contas_vencidas, despesas_sem_valor,
                                  parcelas_em_aberto, receber_a_vencer, receber_em_aberto, receber_vencidas)
from nucleo.models import RegistroOperacao
from producao.models import Producao
from vendas.consultas import encomendas, necessidade_producao, sobras_fritas, vendas_do_dia
from vendas.lotes import lotes_deixados

from .models import Decisao

DIAS_VALIDADE = 3  # "vence logo": de hoje até daqui a 3 dias (como a consulta de validades do agente)
DIAS_CONTAS = 7  # contas a vencer na semana (como a tela Hoje)
DIAS_RECEBIMENTO = 7  # compra com recebimento pendente há 7 dias ou mais é "atrasada"
DIAS_ENCOMENDAS = 3  # encomendas e necessidade de produção: de hoje até daqui a 3 dias


def _ultimo_erro(d):
    if d.situacao != "pendente":
        return None
    r = (RegistroOperacao.objects.filter(nome="aprovar_decisao", status="erro", parametros__decisao_id=d.id)
         .order_by("-id").first())
    return None if r is None else {"quando": r.criado_em, "erro": r.erro, "autor": r.autor}


def _decisao(d, agora) -> dict:
    expirou = d.situacao == "pendente" and d.expira_em is not None and d.expira_em <= agora
    return {
        "decisao_id": d.id, "origem": d.origem, "assunto": d.assunto, "tipo": d.tipo, "texto": d.texto,
        "detalhes": d.detalhes, "operacao": d.operacao, "parametros": d.parametros,
        "situacao": "expirada" if expirou else d.situacao, "vigente": d.vigente,
        "criada_em": d.criada_em, "criada_por": d.criada_por, "canal": d.canal, "expira_em": d.expira_em,
        "decidida_em": d.decidida_em, "decidida_por": d.decidida_por, "motivo": d.motivo,
        "resultado": d.resultado, "ultimo_erro": _ultimo_erro(d),
    }


def decisoes(*, situacao="pendente", origem=None, tipo=None, limite=None) -> list[dict]:
    """Itens da caixa. Pendentes: decisões (com operação) antes dos avisos, mais antigas primeiro;
    as que passaram do prazo saem da lista mesmo antes de a rotina marcá-las. Outras situações
    (ou `situacao=None`, todas): mais recentes primeiro."""
    agora = timezone.now()
    qs = Decisao.objects.all()
    if origem:
        qs = qs.filter(origem=origem)
    if tipo == "decisao":
        qs = qs.exclude(operacao="")
    elif tipo == "aviso":
        qs = qs.filter(operacao="")
    if situacao == "pendente":
        qs = (qs.filter(situacao="pendente").exclude(expira_em__lte=agora)
              .annotate(aviso=Case(When(operacao="", then=Value(1)), default=Value(0), output_field=IntegerField()))
              .order_by("aviso", "criada_em", "id"))
    else:
        if situacao:
            qs = qs.filter(situacao=situacao)
        qs = qs.order_by("-criada_em", "-id")
    if limite:
        qs = qs[:limite]
    return [_decisao(d, agora) for d in qs]


def detalhe_decisao(decisao_id) -> dict | None:
    d = Decisao.objects.filter(id=decisao_id).first()
    return None if d is None else _decisao(d, timezone.now())


def contar_pendentes() -> dict:
    pend = decisoes()
    por_origem = {}
    for d in pend:
        por_origem[d["origem"]] = por_origem.get(d["origem"], 0) + 1
    return {"total": len(pend), "decisoes": sum(d["tipo"] == "decisao" for d in pend),
            "avisos": sum(d["tipo"] == "aviso" for d in pend), "por_origem": por_origem}


def _soma(linhas, campo) -> Decimal:
    return sum((l[campo] for l in linhas), Decimal("0"))


def resumo_do_dia(*, hoje=None, dias_validade=DIAS_VALIDADE, dias_contas=DIAS_CONTAS,
                  dias_encomendas=DIAS_ENCOMENDAS) -> dict:
    """O retrato do dia, para a tela Hoje e para "como está o dia?". Não grava nada.

    `totais.operacoes_hoje` conta as operações feitas hoje pela cozinha (tela, agente), sem a rotina da caixa
    (canal "sistema"), que fica em `operacoes_rotina_hoje`. `contas` são as a pagar (compras e despesas: `origem`
    diz qual); `despesas.sem_valor`, as despesas mensais ainda sem valor; `receber`, as a receber. `encomendas.proximas` vai de hoje até hoje +
    `dias_encomendas` (as de hoje também estão em `encomendas.hoje`); `sem_estoque` são as próximas com
    algo ainda sem reserva, e `necessidade` diz o que falta produzir para elas.
    """
    hoje = hoje or timezone.localdate()
    validade = porcoes(ate=hoje + timedelta(days=dias_validade), hoje=hoje)
    vencidos = [p for p in validade if p["vencido"]]
    vencendo = [p for p in validade if not p["vencido"]]
    deixados = lotes_deixados(hoje=hoje, dias_validade=dias_validade)
    baixo = itens_abaixo_do_minimo(hoje=hoje)
    c_vencidas, c_a_vencer = contas_vencidas(hoje=hoje), contas_a_vencer(dias=dias_contas, hoje=hoje)
    a_chegar = compras_em_aberto()
    andamento = [{"producao_id": p.id, "produto": p.produto.nome, "unidades": p.unidades, "forma": p.forma,
                  "etapa_atual": p.etapa_atual, "etapas": len(p.etapas), "iniciada_em": p.iniciada_em}
                 for p in Producao.objects.filter(status="andamento").select_related("produto").order_by("iniciada_em")]
    custo_pendente = list(Producao.objects.filter(status="concluida", custo_pendente=True)
                          .order_by("encerrada_em").values_list("id", flat=True))
    pendentes = consumos_pendentes()
    avisos = avisos_de_ajuste()
    caixa = decisoes()
    feitas = historico_operacoes(de=hoje, ate=hoje, status="sucesso", limite=None)
    v_hoje = vendas_do_dia(hoje=hoje)["totais"]
    proximas = encomendas(de=hoje, ate=hoje + timedelta(days=dias_encomendas), hoje=hoje)
    atrasadas = encomendas(ate=hoje - timedelta(days=1), hoje=hoje)  # abertas com o dia já passado
    de_hoje = [e for e in proximas if e["entrega_data"] == hoje]
    sem_estoque = [e["encomenda_id"] for e in atrasadas + proximas if e["falta"] > 0]
    r_vencidas, r_a_vencer = receber_vencidas(hoje=hoje), receber_a_vencer(dias=dias_contas, hoje=hoje)
    sobras = sobras_fritas(hoje=hoje)
    sem_valor = despesas_sem_valor(ate=hoje + timedelta(days=dias_contas), hoje=hoje)
    return {
        "hoje": hoje,
        "validade": {"dias": dias_validade, "vencidos": vencidos, "vencendo": vencendo,
                     "valor_vencido": _soma(vencidos, "valor"), "valor_vencendo": _soma(vencendo, "valor"),
                     # Plano 9: lote que uma venda deixou para trás (vence antes do que saiu), fora de "vencendo"
                     "deixados": deixados},
        "estoque_baixo": baixo,
        "contas": {"dias": dias_contas, "vencidas": c_vencidas, "a_vencer": c_a_vencer,
                   "total_vencido": _soma(c_vencidas, "saldo"), "total_a_vencer": _soma(c_a_vencer, "saldo"),
                   "total_devido": _soma(parcelas_em_aberto(hoje=hoje), "saldo")},
        "a_chegar": {"compras": a_chegar,
                     "atrasadas": [c["compra_id"] for c in a_chegar if c["dias"] >= DIAS_RECEBIMENTO]},
        "producoes": {"em_andamento": andamento, "custo_pendente": custo_pendente},
        "consumos_pendentes": pendentes,
        "avisos_de_ajuste": avisos,
        "decisoes": caixa,
        "vendas": {"hoje": v_hoje},
        "encomendas": {"dias": dias_encomendas, "hoje": de_hoje, "proximas": proximas, "atrasadas": atrasadas,
                       "sem_estoque": sem_estoque,
                       "necessidade": necessidade_producao(dias=dias_encomendas, hoje=hoje)},
        "receber": {"dias": dias_contas, "vencidas": r_vencidas, "a_vencer": r_a_vencer,
                    "total_vencido": _soma(r_vencidas, "saldo"), "total_a_vencer": _soma(r_a_vencer, "saldo"),
                    "total_a_receber": _soma(receber_em_aberto(hoje=hoje), "saldo")},
        "sobras_fritas": sobras,
        # despesa mensal sem valor (vencida ou vencendo na semana); com valor, já está em `contas`
        "despesas": {"sem_valor": sem_valor, "sem_valor_vencidas": [d for d in sem_valor if d["vencida"]]},
        "totais": {
            "lotes_vencidos": len(vencidos), "lotes_vencendo": len(vencendo), "lotes_deixados": len(deixados),
            "itens_abaixo_do_minimo": len(baixo),
            "contas_vencidas": len(c_vencidas), "contas_a_vencer": len(c_a_vencer),
            "valor_contas_vencidas": _soma(c_vencidas, "saldo"), "valor_contas_a_vencer": _soma(c_a_vencer, "saldo"),
            "compras_a_chegar": len(a_chegar), "compras_atrasadas": sum(c["dias"] >= DIAS_RECEBIMENTO for c in a_chegar),
            "producoes_em_andamento": len(andamento), "producoes_custo_pendente": len(custo_pendente),
            "consumos_pendentes": len(pendentes), "avisos_de_ajuste": len(avisos),
            "decisoes_pendentes": sum(d["tipo"] == "decisao" for d in caixa),
            "avisos_pendentes": sum(d["tipo"] == "aviso" for d in caixa),
            # sem a rotina (canal "sistema"): cada rodada grava uma operação por gerador
            "operacoes_hoje": sum(r["canal"] != "sistema" for r in feitas),
            "operacoes_rotina_hoje": sum(r["canal"] == "sistema" for r in feitas),
            "vendas_hoje": v_hoje["vendas"], "valor_vendas_hoje": v_hoje["total"],
            "encomendas_hoje": len(de_hoje), "encomendas_proximas": len(proximas),
            "encomendas_atrasadas": len(atrasadas), "encomendas_sem_estoque": len(sem_estoque),
            "receber_vencidas": len(r_vencidas), "valor_receber_vencidas": _soma(r_vencidas, "saldo"),
            "receber_a_vencer": len(r_a_vencer), "valor_receber_a_vencer": _soma(r_a_vencer, "saldo"),
            "sobras_fritas": len(sobras),
            "despesas_sem_valor": len(sem_valor),
        },
    }


# nomes de operação em português corrente, para a tela e para "o que foi feito hoje?"
ROTULOS = {
    "registrar_compra": "Compra lançada", "receber_compra": "Mercadoria recebida",
    "encerrar_pendencia": "Pendência de recebimento encerrada", "estornar_recebimento": "Recebimento estornado",
    "devolver_ao_fornecedor": "Devolução ao fornecedor", "receber_bonificacao": "Bonificação recebida",
    "cancelar_compra": "Compra cancelada", "registrar_pagamento": "Pagamento anotado",
    "estornar_pagamento": "Pagamento estornado", "resolver_aviso": "Aviso de ajuste resolvido",
    "salvar_fornecedor": "Fornecedor salvo", "criar_tamanho": "Tamanho de salgado criado",
    "entrada_manual": "Entrada manual de estoque", "transferir_estado": "Mudança de conservação",
    "registrar_impressao": "Etiqueta impressa", "iniciar_producao": "Produção iniciada",
    "registrar_peso": "Peso registrado", "usar_previsto_restantes": "Usou o previsto",
    "ir_para_etapa": "Etapa do preparo", "iniciar_cronometro": "Cronômetro iniciado",
    "parar_cronometro": "Cronômetro parado", "cancelar_producao": "Produção cancelada",
    "concluir_producao": "Produção concluída", "conciliar_consumo": "Consumo pendente conciliado",
    "criar_decisao": "Item posto na caixa de decisões", "aprovar_decisao": "Decisão aprovada",
    "recusar_decisao": "Decisão recusada", "expirar_decisoes": "Decisões expiradas",
    "gerar_decisoes": "Rotina da caixa de decisões",
    "salvar_cliente": "Cliente salvo", "salvar_apresentacao": "Preço/apresentação salvo",
    "registrar_venda": "Venda registrada", "cancelar_venda": "Venda cancelada",
    "criar_encomenda": "Encomenda criada", "completar_reserva": "Reserva de encomenda completada",
    "cancelar_encomenda": "Encomenda cancelada", "entregar_encomenda": "Encomenda entregue",
    "registrar_fritura": "Fritura registrada", "registrar_perda": "Perda registrada",
    "registrar_recebimento": "Recebimento de cliente anotado",
    "estornar_recebimento_cliente": "Recebimento de cliente estornado",
    "salvar_categoria_despesa": "Categoria de despesa salva", "salvar_despesa_mensal": "Despesa mensal salva",
    "gerar_despesas_do_mes": "Despesas do mês geradas", "lancar_despesa": "Despesa lançada",
    "cancelar_despesa": "Despesa cancelada", "informar_valor_despesa": "Valor de despesa informado",
    "pagar_despesa_do_mes": "Despesa do mês paga", "salvar_referencias": "Referências do salgado salvas",
    "salvar_canal_venda": "Canal de venda salvo", "ajustar_contagem": "Ajuste por contagem",
}


def _inicio(d):
    return timezone.make_aware(datetime.combine(d, time.min))


def historico_operacoes(*, de=None, ate=None, autor="", canal="", nome="", status="", limite=200) -> list[dict]:
    """A trilha de operações (RegistroOperacao), mais recentes primeiro. `de`/`ate` são dias (inclusive,
    no fuso da cozinha); `autor`, `canal`, `nome` e `status` ("sucesso"/"erro") filtram por igualdade."""
    qs = RegistroOperacao.objects.all()
    if de:
        qs = qs.filter(criado_em__gte=_inicio(de))
    if ate:
        qs = qs.filter(criado_em__lt=_inicio(ate + timedelta(days=1)))
    for campo, valor in (("autor", autor), ("canal", canal), ("nome", nome), ("status", status)):
        if valor:
            qs = qs.filter(**{campo: valor})
    qs = qs.order_by("-criado_em", "-id")
    if limite:
        qs = qs[:limite]
    return [{"operacao_id": r.id, "criado_em": r.criado_em, "nome": r.nome,
             "rotulo": ROTULOS.get(r.nome, r.nome.replace("_", " ").capitalize()), "canal": r.canal,
             "autor": r.autor, "status": r.status, "parametros": r.parametros, "resultado": r.resultado,
             "erro": r.erro, "motivo_vencido": (r.parametros or {}).get("motivo_vencido", "")} for r in qs]
