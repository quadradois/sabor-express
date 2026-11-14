"""Consultas do agente (só leitura), independentes de transporte.

Cada função devolve um dict pronto para JSON. Erros de entrada viram
`ConsultaInvalida`, que a API REST traduz em status HTTP e o servidor MCP em
{"erro": ...}. As quantidades vão em dois formatos: número na unidade base e
texto pronto para falar ("1,2 kg"). Nenhuma conta de negócio é feita aqui:
saldo vem de `estoque.servicos.saldo`, receita de `fichas.escala.escalar`.
"""

import unicodedata
from datetime import timedelta
from decimal import Decimal

from django.db.models import Min, Sum
from django.utils import timezone

from cadastros.models import Item
from estoque.models import Lote, Movimento
from estoque.servicos import saldo
from fichas.escala import escalar
from nucleo.operacoes import RegraViolada
from producao.models import Producao
from web.templatetags.formato import quantidade as fmt_qtd

STATUS_PRODUCAO = ("andamento", "concluida", "cancelada", "todas")


class ConsultaInvalida(Exception):
    """Erro de entrada; a mensagem (pt-BR) vai para quem perguntou."""

    def __init__(self, mensagem, status=400, **extra):
        super().__init__(mensagem)
        self.mensagem, self.status, self.extra = mensagem, status, extra

    def como_dict(self):
        return {"erro": self.mensagem, **self.extra}


def _normal(s: str) -> str:
    """Minúsculas e sem acento: o nome chega por voz, transcrito."""
    s = unicodedata.normalize("NFKD", s.casefold())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def _casa(busca: str, nome: str) -> bool:
    """Cada palavra dita aparece no nome ("farinha empanamento" casa "Farinha de trigo (Empanamento)")."""
    n = _normal(nome)
    return all(p in n for p in _normal(busca).split())


def _filtrar(itens, busca, rotulo=lambda i: i.nome):
    if not busca:
        return list(itens)
    return [i for i in itens if _casa(busca, rotulo(i))]


def escolher(candidatos, busca, *, oque, rotulo=lambda i: i.nome):
    """Exatamente um candidato pelo nome falado; senão erro com as opções para perguntar.

    Nome idêntico a um rótulo ganha dos parciais ("bolinha 25 g" entre "Bolinha 25 g" e "Bolinha 250 g").
    """
    candidatos = _filtrar(candidatos, busca, rotulo)
    exatos = [c for c in candidatos if _normal(rotulo(c)) == _normal(busca)]
    if len(exatos) == 1:
        return exatos[0]
    if len(candidatos) == 1:
        return candidatos[0]
    if not candidatos:
        raise ConsultaInvalida(f"Nenhum {oque} com o nome '{busca}'.", 404)
    raise ConsultaInvalida(f"Mais de um {oque} com o nome '{busca}'; diga qual.", 409,
                           opcoes=[rotulo(c) for c in candidatos])


def _qtd(q: Decimal, unidade: str) -> dict:
    return {"valor": float(q), "unidade": unidade, "texto": fmt_qtd(q, unidade)}


def _inteiro(valor, nome):
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ConsultaInvalida(f"'{nome}' precisa ser um número inteiro.") from None


def estoque(busca=""):
    itens = _filtrar(Item.objects.filter(ativo=True).order_by("nome"), busca)
    saida = []
    for i in itens:
        s = saldo(i)
        saida.append({
            "id": i.id, "nome": i.nome, "tipo": i.tipo,
            "saldo": _qtd(s, i.unidade_base),
            "estoque_minimo": _qtd(i.estoque_minimo, i.unidade_base),
            "abaixo_do_minimo": s < i.estoque_minimo,
        })
    return {"itens": saida}


def validades(dias=3):
    dias = _inteiro(dias, "dias")
    hoje = timezone.localdate()
    limite = hoje + timedelta(days=dias)
    porcoes = (Movimento.objects.values("lote", "estado")
               .annotate(s=Sum("quantidade"), v=Min("validade"))
               .filter(s__gt=0))
    lotes = Lote.objects.select_related("item").in_bulk({p["lote"] for p in porcoes})
    saida = []
    for p in porcoes:
        l = lotes[p["lote"]]
        validade = p["v"] or l.validade
        if validade is None or validade > limite:
            continue
        saida.append({
            "lote_id": l.id, "item": l.item.nome, "codigo": l.codigo or "sem código",
            "estado": p["estado"] or "-", "validade": validade.isoformat(),
            "dias_restantes": (validade - hoje).days, "vencido": validade < hoje,
            "saldo": _qtd(p["s"], l.item.unidade_base),
        })
    saida.sort(key=lambda x: x["validade"])
    return {"hoje": hoje.isoformat(), "ate": limite.isoformat(), "lotes": saida}


def _produtos_ativos():
    return Item.objects.filter(tipo="produto", ativo=True).select_related("ficha").order_by("nome")


def produtos(busca=""):
    return {"produtos": [{
        "id": i.id, "nome": i.nome, "ficha": i.ficha.nome, "peso_unidade_g": float(i.peso_g),
        "saldo": _qtd(saldo(i), "un"),
    } for i in _filtrar(_produtos_ativos(), busca)]}


_JEITOS = {"cru", "crua", "frito", "frita", "assado", "assada", "fresco", "fresca", "resfriado", "resfriada",
           "congelado", "congelada"}


def resolver_produto(nome):
    """Acha o produto pelo nome falado; exige exatamente uma correspondência."""
    if not (nome or "").strip():
        raise ConsultaInvalida("Diga o nome do produto.")
    try:
        return escolher(_produtos_ativos(), nome, oque="produto")
    except ConsultaInvalida as e:
        # "coxinha 100 g frito fresco": o jeito (forma e conservação) não faz parte do nome do produto
        limpo = " ".join(w for w in nome.split() if _normal(w).rstrip("s") not in _JEITOS)
        if e.status != 404 or not limpo or limpo == " ".join(nome.split()):
            raise
        return escolher(_produtos_ativos(), limpo, oque="produto")


def receita(produto_id, unidades):
    produto_id, unidades = _inteiro(produto_id, "produto_id"), _inteiro(unidades, "unidades")
    produto = Item.objects.filter(id=produto_id, tipo="produto").select_related("ficha").first()
    if produto is None:
        raise ConsultaInvalida("Produto não encontrado.", 404)
    try:
        r = escalar(produto.ficha, unidades, produto.peso_g)
    except RegraViolada as e:
        raise ConsultaInvalida(str(e), 422) from None
    total, falta, unidade = {}, {}, {}
    for b in r.blocos:
        for l in b.linhas:
            total[l.nome] = total.get(l.nome, Decimal(0)) + l.quantidade
            falta[l.nome], unidade[l.nome] = l.falta, l.unidade_base
    return {
        "produto": produto.nome, "unidades": unidades, "massa_total": _qtd(r.total_g, "g"),
        "preparacoes": [b.nome for b in r.blocos],
        "ingredientes": [{
            "nome": n, "necessario": _qtd(total[n], unidade[n]), "falta": _qtd(falta[n], unidade[n]),
        } for n in total],
        "da_para_produzir": not any(falta.values()),
    }


def _resumo(p):
    return {"id": p.id, "produto": p.produto.nome, "unidades": p.unidades, "forma": p.forma,
            "status": p.status, "iniciada_em": timezone.localtime(p.iniciada_em).isoformat(timespec="minutes")}


def producoes(status="andamento"):
    if status not in STATUS_PRODUCAO:
        raise ConsultaInvalida(f"'status' deve ser um destes: {', '.join(STATUS_PRODUCAO)}.")
    qs = Producao.objects.select_related("produto").order_by("-iniciada_em")
    if status != "todas":
        qs = qs.filter(status=status)
    return {"producoes": [_resumo(p) for p in qs[:20]]}


def producao(producao_id):
    p = Producao.objects.select_related("produto").filter(id=_inteiro(producao_id, "producao_id")).first()
    if p is None:
        raise ConsultaInvalida("Produção não encontrada.", 404)
    if p.etapa_atual == 0:
        etapa = "mise en place (pesagem dos ingredientes)"
    elif p.etapa_atual >= p.fechamento:
        etapa = "fechamento"
    else:
        e = p.etapas[p.etapa_atual - 1]
        etapa = f"{e['bloco']}: {e['instrucao']}"
    agora = timezone.now()
    return {
        **_resumo(p),
        "etapa_atual": etapa, "etapa_numero": p.etapa_atual, "total_etapas": len(p.etapas),
        "falta_pesar": [{"item": l.item.nome, "previsto": _qtd(l.previsto, l.item.unidade_base)}
                        for l in p.linhas.select_related("item") if l.usado is None],
        "cronometros": [{"nome": c.nome, "segundos_restantes": max(0, int((c.fim - agora).total_seconds()))}
                        for c in p.cronometros.filter(parado_em__isnull=True)],
        "quantidade_boa": p.quantidade_boa, "perdas": p.perdas,
        "custo_unitario": float(p.custo_unitario) if p.custo_unitario is not None else None,
    }
