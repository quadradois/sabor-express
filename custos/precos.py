"""Estudo de preço pelo CMV, simulação de preço, ponto de equilíbrio e indireto real (Plano 8) — só leitura.

Nada aqui grava preço nem escolhe margem: o sistema mostra quanto sobra com o preço atual e simula, com o
número que quem pergunta informar, quanto sobraria ("com preço P") ou que preço daria a sobra ("para sobrar
M%"). Definições (por apresentação, no preço da tabela escolhida):

- CMV = custo da mercadoria vendida = ingredientes pela ficha + óleo de referência (frito) + embalagem
  (o `custo` de `margem_apresentacoes`).
- indiretos = unidades × `Item.indireto_ref_un` (mão de obra, energia, gás por salgado, referência).
- taxa = preço × taxa do canal (cartão, plataforma; balcão em dinheiro/pix = 0%).
- sobra = preço − CMV − indiretos − taxa; `sobra_pct` = sobra ÷ preço.
- contribuição = preço − CMV − taxa (o que cada venda deixa para pagar as despesas do mês).
"""

import math
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from financeiro.consultas import despesas_do_mes, despesas_periodo
from nucleo.operacoes import RegraViolada
from nucleo.valores import decimal
from producao.models import Producao
from vendas.models import Apresentacao, CanalVenda

from .consultas import _pct, _rs, margem_apresentacoes

ZERO = Decimal("0")
CENT, Q4 = Decimal("0.01"), Decimal("0.0001")
TABELAS = ("varejo", "atacado")


def canais_venda(*, ativos=True) -> list[dict]:
    qs = CanalVenda.objects.all()
    if ativos:
        qs = qs.filter(ativo=True)
    return [{"canal_id": c.id, "nome": c.nome, "taxa_pct": c.taxa_pct, "ativo": c.ativo} for c in qs]


def _preco(a, tabela):
    if tabela not in TABELAS:
        raise RegraViolada("Tabela desconhecida: use varejo ou atacado.")
    return a["preco_varejo"] if tabela == "varejo" else a["preco_atacado"]


def _sobra(preco, cmv, indiretos, taxa_pct) -> dict:
    """Os números de um preço num canal; `None` onde falta dado (nunca zero)."""
    if preco is None or cmv is None or taxa_pct is None:
        taxa = contribuicao = sobra = None
    else:
        taxa = _rs(preco * taxa_pct / 100)
        contribuicao = preco - cmv - taxa
        sobra = None if indiretos is None else contribuicao - indiretos
    return {"taxa": taxa, "contribuicao": contribuicao, "contribuicao_pct": _pct(contribuicao, preco),
            "sobra": sobra, "sobra_pct": _pct(sobra, preco)}


def estudo_preco(*, produto_id=None, tabela="varejo", ativas=True, em=None) -> dict:
    """Para cada apresentação, no preço atual da `tabela`: CMV, CMV % do preço, indiretos de referência e, por
    canal ativo, a taxa, a contribuição e quanto sobra por apresentação e por unidade, em reais e em %.
    Canal sem taxa informada: números `None` e o motivo em `faltando`. Não grava nem sugere preço."""
    if tabela not in TABELAS:
        raise RegraViolada("Tabela desconhecida: use varejo ou atacado.")
    canais = canais_venda()
    saida = []
    for a in margem_apresentacoes(ativas=ativas, produto_id=produto_id, em=em):
        preco, cmv, ind = _preco(a, tabela), a["custo"], a["indiretos"]
        faltando = list(a["faltando"])
        if ind is None:
            faltando.append({"item_id": a["produto_id"], "item": a["produto"],
                             "motivo": "sem indiretos de referência por unidade"})
        por_canal = []
        for c in canais:
            s = _sobra(preco, cmv, ind, c["taxa_pct"])
            un = a["unidades"]
            por_canal.append({"canal_id": c["canal_id"], "canal": c["nome"], "taxa_pct": c["taxa_pct"], **s,
                              "sobra_un": None if s["sobra"] is None else _rs(s["sobra"] / un),
                              "faltando": "taxa do canal não informada" if c["taxa_pct"] is None else ""})
        saida.append({
            "apresentacao_id": a["apresentacao_id"], "produto_id": a["produto_id"], "produto": a["produto"],
            "nome": a["nome"], "descricao": a["descricao"], "forma": a["forma"], "unidades": a["unidades"],
            "tabela": tabela, "preco": preco, "preco_un": None if preco is None else _rs(preco / a["unidades"]),
            "cmv": cmv, "cmv_un": None if cmv is None else (cmv / a["unidades"]).quantize(Q4, ROUND_HALF_UP),
            "cmv_pct": _pct(cmv, preco), "custo_salgado": a["custo_salgado"], "custo_embalagem": a["custo_embalagem"],
            "indiretos": ind, "custo_com_indiretos": a["custo_com_indiretos"],
            "completo": cmv is not None and ind is not None, "faltando": faltando, "erro": a["erro"],
            "por_canal": por_canal})
    return {"tabela": tabela, "rotulo": "estimado", "canais": canais, "apresentacoes": saida,
            "observacao": "Estudo pelo custo atual (última compra de cada ingrediente). Não muda o preço da tabela."}


def _canal(canal_id):
    qs = CanalVenda.objects.filter(ativo=True)
    c = qs.filter(id=canal_id).first() if canal_id else qs.first()
    if c is None:
        raise RegraViolada("Canal de venda não encontrado.")
    if c.taxa_pct is None:
        raise RegraViolada(f"A taxa do canal '{c.nome}' não foi informada: cadastre a taxa para simular.")
    return c


def _apresentacao(apresentacao_id, em):
    if not Apresentacao.objects.filter(id=apresentacao_id).exists():
        raise RegraViolada("Apresentação não encontrada.")
    [a] = [x for x in margem_apresentacoes(ativas=False, em=em) if x["apresentacao_id"] == apresentacao_id]
    if a["custo"] is None:
        falta = ", ".join(f"{f['item']} ({f['motivo']})" for f in a["faltando"]) or a["erro"]
        raise RegraViolada(f"O custo de {a['descricao']} está incompleto: {falta}.")
    return a


def simular_preco(*, apresentacao_id, preco=None, sobra_pct=None, canal_id=None, tabela="varejo", em=None) -> dict:
    """**Simulação** (não grava): com `preco`, quanto sobraria; com `sobra_pct` (o % que quem pergunta quer que
    sobre do preço), o preço que daria essa sobra: preço = (CMV + indiretos) ÷ (1 − taxa% − sobra%),
    arredondado ao centavo (a sobra devolvida é a do preço arredondado). Canal padrão: o primeiro ativo
    (balcão). Sem indiretos de referência, simula sem eles e diz isso (`inclui_indiretos=False`)."""
    if (preco in (None, "")) == (sobra_pct in (None, "")):
        raise RegraViolada("Informe o preço ou a sobra desejada (um dos dois).")
    a = _apresentacao(apresentacao_id, em)
    c = _canal(canal_id)
    cmv, ind = a["custo"], a["indiretos"]
    base = cmv + (ind or ZERO)
    t = c.taxa_pct
    if preco not in (None, ""):
        p = decimal(preco, "preco").quantize(CENT, ROUND_HALF_UP)
        if p <= 0:
            raise RegraViolada("O preço deve ser maior que zero.")
        alvo = None
    else:
        alvo = decimal(sobra_pct, "sobra_pct")
        if alvo < 0:
            raise RegraViolada("Informe a sobra desejada sem sinal.")
        if t + alvo >= 100:
            raise RegraViolada(f"Não existe preço que deixe sobrar {alvo}% com taxa de {t}% no canal {c.nome}.")
        p = (base / (1 - (t + alvo) / 100)).quantize(CENT, ROUND_HALF_UP)
    s = _sobra(p, cmv, ind or ZERO, t)
    atual = _preco(a, tabela)
    return {
        "rotulo": "simulação", "aviso": "Simulação: o preço da tabela não muda.",
        "apresentacao_id": a["apresentacao_id"], "descricao": a["descricao"], "unidades": a["unidades"],
        "canal_id": c.id, "canal": c.nome, "taxa_pct": t, "tabela": tabela, "preco_atual": atual,
        "sobra_pct_pedida": alvo, "preco": p, "preco_un": _rs(p / a["unidades"]),
        "cmv": cmv, "cmv_pct": _pct(cmv, p), "indiretos": ind, "inclui_indiretos": ind is not None,
        "taxa": s["taxa"], "contribuicao": s["contribuicao"], "sobra": s["sobra"], "sobra_pct": s["sobra_pct"],
        "sobra_un": _rs(s["sobra"] / a["unidades"]),
        "diferenca_preco_atual": None if atual is None else p - atual,
    }


def ponto_equilibrio(*, apresentacao_id, competencia=None, canal_id=None, tabela="varejo", hoje=None,
                     em=None) -> dict:
    """Quantas apresentações (e que receita) cobrem as despesas do mês, se todas as vendas fossem desta
    apresentação, neste canal, no preço atual: despesas do mês ÷ contribuição (preço − CMV − taxa). Os
    indiretos de referência **não** entram na contribuição: mão de obra, energia e gás já estão nas despesas
    (contar duas vezes inflaria o ponto). Despesa do mês sem valor fica fora e `completo=False`."""
    hoje = hoje or timezone.localdate()
    a = _apresentacao(apresentacao_id, em)
    c = _canal(canal_id)
    preco = _preco(a, tabela)
    if preco is None:
        raise RegraViolada(f"{a['descricao']} não tem preço de {tabela}.")
    s = _sobra(preco, a["custo"], ZERO, c.taxa_pct)
    if s["contribuicao"] <= 0:
        raise RegraViolada(f"Com o preço de {preco} cada venda não cobre nem o CMV e a taxa: não há ponto de "
                           f"equilíbrio.")
    mes = despesas_do_mes(competencia=competencia or hoje, hoje=hoje)
    despesas = mes["totais"]["valor"]
    n = math.ceil(despesas / s["contribuicao"]) if despesas > 0 else 0
    sem_valor = [d["despesa"] for d in mes["mensais"] if d["situacao"] == "sem_valor"]
    ressalvas = [f"{d} sem valor neste mês: não entrou nas despesas." for d in sem_valor]
    if not mes["mensais"] and not mes["avulsas"]:
        ressalvas.append("Nenhuma despesa lançada ou gerada neste mês.")
    return {"rotulo": "estimado", "competencia": mes["competencia"], "apresentacao_id": a["apresentacao_id"],
            "descricao": a["descricao"], "unidades_por": a["unidades"], "canal": c.nome, "taxa_pct": c.taxa_pct,
            "preco": preco, "cmv": a["custo"], "taxa": s["taxa"], "contribuicao": s["contribuicao"],
            "despesas": despesas, "completo": not sem_valor, "faltando": sem_valor,
            "apresentacoes": n, "unidades": n * a["unidades"], "receita": preco * n, "ressalvas": ressalvas}


def _inicio(d):
    return timezone.make_aware(datetime.combine(d, time.min))


def indireto_real(*, competencia=None, hoje=None) -> dict:
    """Confere a referência de indiretos com a realidade do mês: despesas das categorias indiretas (mão de obra,
    energia, gás, diária) ÷ unidades boas produzidas no mês = indireto real por unidade; e o mesmo com todas
    as despesas. No mês em andamento, vai do dia 1 até hoje e as despesas mensais entram rateadas pelos dias
    (como no relatório). `referencia_un` = média de `indireto_ref_un` ponderada pelas unidades produzidas."""
    hoje = hoje or timezone.localdate()
    de = (competencia or hoje).replace(day=1)
    fim = (de.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    ate = min(fim, hoje) if de <= hoje else fim
    if de > hoje:
        raise RegraViolada("Esse mês ainda não começou.")
    desp = despesas_periodo(de=de, ate=ate, hoje=hoje)
    prods = (Producao.objects.filter(status="concluida", encerrada_em__gte=_inicio(de),
                                     encerrada_em__lt=_inicio(ate + timedelta(days=1))).select_related("produto"))
    por = {}
    for p in prods:
        g = por.setdefault(p.produto_id, {"produto_id": p.produto_id, "produto": p.produto.nome,
                                          "indireto_ref_un": p.produto.indireto_ref_un, "unidades": 0})
        g["unidades"] += p.quantidade_boa or 0
    unidades = sum(g["unidades"] for g in por.values())
    com_ref = [g for g in por.values() if g["indireto_ref_un"] is not None]
    un_ref = sum(g["unidades"] for g in com_ref)
    referencia = ((sum(g["indireto_ref_un"] * g["unidades"] for g in com_ref) / un_ref).quantize(Q4, ROUND_HALF_UP)
                  if un_ref else None)

    def por_un(v):
        return (v / unidades).quantize(Q4, ROUND_HALF_UP) if unidades else None

    real = por_un(desp["indiretas"])
    ressalvas = list(desp["ressalvas"])
    if ate < fim:
        ressalvas.append("Mês em andamento: conta do dia 1 até hoje.")
    if not unidades:
        ressalvas.append("Nenhuma produção concluída no mês: sem unidades para dividir.")
    if len(com_ref) < len(por):
        ressalvas.append("Produtos sem indireto de referência: " +
                         ", ".join(g["produto"] for g in por.values() if g["indireto_ref_un"] is None) + ".")
    return {"rotulo": "estimado", "competencia": de, "de": de, "ate": ate, "unidades_produzidas": unidades,
            "por_produto": sorted(por.values(), key=lambda g: g["produto"]),
            "despesas_indiretas": desp["indiretas"], "despesas_total": desp["total"],
            "por_categoria": desp["por_categoria"], "completo": desp["completo"], "faltando": desp["faltando"],
            "indireto_real_un": real, "despesa_total_un": por_un(desp["total"]), "referencia_un": referencia,
            "diferenca_un": None if real is None or referencia is None else real - referencia,
            "diferenca_pct": None if real is None or not referencia else _pct(real - referencia, referencia),
            "ressalvas": ressalvas}
