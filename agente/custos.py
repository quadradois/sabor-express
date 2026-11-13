"""Custos, margens e relatórios pelo agente de voz (Plano 7, fase 2b) — só leitura (nível 0).

Mesmo padrão de `vendas.py`: produto, preparação e item chegam pelo nome falado e são resolvidos aqui
(ambíguo vira `ConsultaInvalida` com `opcoes`); o período é falado ("semana", "mês passado") e vira datas
por `custos.consultas.intervalo`. Cada ferramenta devolve os números do núcleo (Decimal como número, datas
ISO) e um `texto` curto pronto para falar, com dinheiro por extenso e porcentagens e pontos já calculados.

O modelo de voz não faz conta nenhuma (design A3): toda diferença, porcentagem e ponto vem pronto de
`custos.fichas`, `custos.consultas` e `custos.relatorios`. Toda margem é dita "estimada" e todo resultado
"estimado, antes das despesas" (RF-CUS-06, CA-33); o que ficou fora da margem é dito com o motivo; dado
faltante é dito como faltante, nunca como zero. Nenhuma ferramenta daqui grava nada.
"""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from cadastros.models import Item
from custos import consultas as cc
from custos.fichas import custo_estimado, custo_preparacao
from custos.relatorios import relatorio_periodo
from fichas.models import Ficha

from .compras import _POR, MESES, _item, _juntar, _n, qtd, quando, reais
from .consultas import ConsultaInvalida, _casa, _filtrar, _inteiro, _normal, escolher
from .vendas import _num, _un

ZERO = Decimal("0")
CENTAVO = Decimal("0.01")
MAX_FALADOS = 3  # itens lidos no `texto`; o resto fica nos dados

# --- períodos falados ----------------------------------------------------------------

# chave de `custos.consultas.intervalo` → (o período falado, "em relação ao" período de comparação, "no" período
# de comparação)
_PERIODOS = {
    "hoje": ("hoje", "a ontem", "ontem"),
    "ontem": ("ontem", "a anteontem", "anteontem"),
    "semana": ("nesta semana", "ao mesmo trecho da semana passada", "no mesmo trecho da semana passada"),
    "semana_passada": ("na semana passada", "à semana anterior", "na semana anterior"),
    "mes": ("neste mês", "ao mesmo trecho do mês passado", "no mesmo trecho do mês passado"),
    "mes_passado": ("no mês passado", "ao mês anterior", "no mês anterior"),
    "ultimos_7": ("nos últimos 7 dias", "aos 7 dias anteriores", "nos 7 dias anteriores"),
    "ultimos_30": ("nos últimos 30 dias", "aos 30 dias anteriores", "nos 30 dias anteriores"),
}
_PERIODOS_DITOS = {
    "hoje": "hoje", "dia": "hoje", "ontem": "ontem", "semana": "semana", "semana passada": "semana_passada",
    "ultima semana": "semana_passada", "mes": "mes", "mes passado": "mes_passado", "ultimo mes": "mes_passado",
    "ultimos 7 dias": "ultimos_7", "ultimos 7": "ultimos_7", "7 dias": "ultimos_7", "ultimos sete dias": "ultimos_7",
    "sete dias": "ultimos_7", "ultimos 30 dias": "ultimos_30", "ultimos 30": "ultimos_30", "30 dias": "ultimos_30",
    "ultimos trinta dias": "ultimos_30", "trinta dias": "ultimos_30",
}
_ARTIGOS = re.compile(r"^(neste|nesta|deste|desta|este|esta|essa|esse|no|na|do|da|o|a)\s+")


def _periodo(periodo) -> tuple[str, date, date]:
    """(chave, de, ate) de um período falado: hoje, ontem, semana, semana passada, mês, mês passado,
    últimos 7 dias ou últimos 30 dias."""
    p = _normal(str(periodo or "")).replace("_", " ").replace("-", " ")
    p = _ARTIGOS.sub("", " ".join(p.split()))
    chave = _PERIODOS_DITOS.get(p)
    if chave is None:
        raise ConsultaInvalida(f"Não conheço o período '{periodo}'. Diga hoje, ontem, semana, semana passada, mês, "
                               "mês passado, últimos 7 dias ou últimos 30 dias.")
    de, ate = cc.intervalo(chave)
    return chave, de, ate


def _dito(chave) -> str:
    return _PERIODOS[chave][0]


def _cap(t) -> str:
    return t[:1].upper() + t[1:]


def _faixa(de, ate) -> str:
    """"de 1 a 13 de novembro", "hoje"."""
    if de == ate:
        return quando(de).removeprefix("em ")
    if (de.year, de.month) == (ate.year, ate.month):
        return f"de {de.day} a {ate.day} de {MESES[ate.month - 1]}"
    return f"de {de.day} de {MESES[de.month - 1]} a {ate.day} de {MESES[ate.month - 1]}"


# --- fala dos números (o sistema já calculou; aqui só se escreve) ---------------------------

def _rs(v) -> str:
    """Dinheiro falado; custo por unidade abaixo de meio centavo não vira "zero real"."""
    v = Decimal(str(v))
    if ZERO < abs(v) < Decimal("0.005"):
        return "menos de 1 centavo"
    return reais(v)


def _pct(v) -> str:
    return f"{_num(Decimal(str(v)))} por cento"


def _pontos(v) -> str:
    """"caiu 6 pontos", "subiu 1 ponto", "ficou igual"."""
    v = Decimal(str(v))
    if v == 0:
        return "ficou igual"
    n = _num(abs(v))
    return f"{'subiu' if v > 0 else 'caiu'} {n} {'ponto' if abs(v) == 1 else 'pontos'}"


def _variacao(v) -> str:
    """"subiu 11,1 por cento", "caiu 5 por cento", "ficou igual"."""
    v = Decimal(str(v))
    if v == 0:
        return "ficou igual"
    return f"{'subiu' if v > 0 else 'caiu'} {_pct(abs(v))}"


def _curto(s) -> str:
    """O que não inclui, sem o parêntese e a explicação ("perdas da produção (o estimado...)" → "perdas da
    produção")."""
    return re.split(r" \(|:", s, maxsplit=1)[0].strip()


def _nao_inclui(lista) -> str:
    return _juntar([_curto(s) for s in lista])


def _faltando_txt(faltando) -> str:
    """"falta o preço de Queijo; nunca foi comprado"."""
    nomes = [f["item"] for f in faltando]
    if not nomes:
        return ""
    motivos = {f["motivo"] for f in faltando}
    if motivos == {"nunca comprado"}:
        porque = "nunca foi comprado" if len(nomes) == 1 else "nunca foram comprados"
    else:
        porque = _juntar(sorted(motivos))
    return f"falta o preço de {_juntar(nomes)}; {porque}"


def _json(v):
    """Decimal vira número e data vira texto ISO, em qualquer profundidade."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k) if isinstance(k, date) else k: _json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    return v


# --- resolução pelo nome ---------------------------------------------------------------

def _produtos():
    return Item.objects.filter(tipo="produto", ativo=True, ficha__isnull=False).order_by("nome")


def _produto(nome) -> Item:
    if not (nome or "").strip():
        raise ConsultaInvalida("Diga o nome do produto.")
    return escolher(_produtos(), nome, oque="produto")


# --- ver_custo -------------------------------------------------------------------------

def _custo_produto(p: Item) -> dict:
    c = custo_estimado(produto_id=p.id)
    partes = [{"preparacao": b["nome"], "gramas": b["gramas"], "custo": b["custo"],
               "itens": [{"item": i["item"], "quantidade": i["quantidade"], "unidade": i["unidade_base"],
                          "referencia": i["referencia"], "data_compra": i["data_compra"], "fornecedor": i["fornecedor"],
                          "custo": i["custo"]} for i in b["itens"]]} for b in c["blocos"]]
    nome = c["produto"]
    if not c["completo"]:
        texto = (f"O custo estimado de {nome} está incompleto: {_faltando_txt(c['faltando'])}. "
                 "Sem esse preço não dá para dizer o custo.")
    else:
        texto = (f"Custo estimado de uma unidade de {nome}, pela última compra de cada ingrediente: "
                 f"{_rs(c['ingredientes'])} de ingredientes")
        if c["indiretos"] is not None:
            texto += f", mais {_rs(c['indiretos'])} de indiretos, o que dá {_rs(c['custo_cru'])} cru"
        else:
            texto += " cru"
        if c["custo_frito"] is not None:
            texto += f"; frito, com {_rs(c['oleo'])} de óleo, {_rs(c['custo_frito'])}"
        texto += f". Não inclui {_nao_inclui(c['nao_inclui'])}."
    return {"tipo": "produto", "produto_id": c["produto_id"], "produto": nome, "peso_g": c["peso_g"],
            "completo": c["completo"], "faltando": c["faltando"], "ingredientes": c["ingredientes"],
            "ingredientes_conhecido": c["ingredientes_conhecido"], "indiretos": c["indiretos"], "oleo": c["oleo"],
            "custo_cru": c["custo_cru"], "custo_frito": c["custo_frito"], "inclui": c["inclui"],
            "nao_inclui": c["nao_inclui"], "rotulo": "estimado", "partes": partes, "texto": texto}


def _custo_prep(f: Ficha) -> dict:
    c = custo_preparacao(ficha_id=f.id)
    if not c["completo"]:
        texto = (f"O custo estimado de {c['nome']} está incompleto: {_faltando_txt(c['faltando'])}. "
                 "Sem esse preço não dá para dizer o custo.")
    else:
        texto = (f"Custo estimado de {c['nome']}, pela última compra de cada ingrediente: {_rs(c['total'])} a "
                 f"receita de {qtd(c['gramas'], 'g')}, {_rs(c['por_kg'])} o quilo. Só ingredientes: não inclui "
                 "indiretos nem perdas.")
    return {"tipo": "preparacao", "ficha_id": c["ficha_id"], "preparacao": c["nome"], "gramas": c["gramas"],
            "completo": c["completo"], "faltando": c["faltando"], "total": c["total"], "conhecido": c["conhecido"],
            "por_kg": c["por_kg"], "rotulo": "estimado", "texto": texto}


def ver_custo(produto):
    nome = (produto or "").strip()
    if not nome:
        raise ConsultaInvalida("Diga o nome do produto ou da preparação.")
    if _filtrar(_produtos(), nome):
        return _json(_custo_produto(_produto(nome)))
    preps = Ficha.objects.filter(tipo="preparacao", ativa=True).order_by("nome")
    if _filtrar(preps, nome):
        return _json(_custo_prep(escolher(preps, nome, oque="preparação")))
    raise ConsultaInvalida(f"Nenhum produto nem preparação com o nome '{nome}'.", 404)


# --- ver_margem ------------------------------------------------------------------------

_AGRUPAR = {"produto": "produto", "apresentacao": "apresentacao", "cliente": "cliente", "tabela": "tabela",
            "dia": "dia"}


def _agrupar(valor) -> str:
    v = _normal(valor or "produto")
    for k in _AGRUPAR:
        if v.startswith(k[:5]) or k.startswith(v[:5]):
            return k
    if v.startswith(("caixa", "jeito", "embala")):
        return "apresentacao"
    raise ConsultaInvalida("'agrupar' é produto, apresentação, cliente, tabela ou dia.")


def _fora_txt(fora) -> str:
    """"2 itens de venda, somando 20 reais, ficaram fora da margem: 1 com custo zero gravado..."."""
    if not fora["linhas"]:
        return ""
    motivos = _juntar([f"{n} com {m}" if not m.startswith("custo gravado") else f"{n} com o {m}"
                       for m, n in sorted(fora["motivos"].items(), key=lambda x: -x[1])])
    return (f"{_n(fora['linhas'], 'item de venda', 'itens de venda')}, somando {reais(fora['receita'])}, "
            f"{'ficou' if fora['linhas'] == 1 else 'ficaram'} fora da margem porque o custo gravado não é "
            f"confiável: {motivos}.")


def _totais(t) -> dict:
    return {k: t[k] for k in ("vendas", "linhas", "unidades", "receita", "receita_tabela", "desconto",
                              "receita_com_custo", "custo", "margem", "margem_pct")} | {
        "fora": {"linhas": t["fora"]["linhas"], "receita": t["fora"]["receita"], "motivos": t["fora"]["motivos"]}}


def _grupo_txt(g, comparar) -> str:
    nome = quando(g["chave"]).removeprefix("em ") if isinstance(g["chave"], date) else g["nome"]
    if g.get("margem_pct") is None:
        t = f"{nome}, sem margem estimada (custo não confiável)"
    else:
        t = f"{nome}, {_pct(g['margem_pct'])}"
    if comparar and g.get("pontos") is not None:
        t += f", {_pontos(g['pontos'])}"
    return t


def ver_margem(periodo="semana", agrupar="produto", comparar=True):
    chave, de, ate = _periodo(periodo)
    agrupar = _agrupar(agrupar)
    quando_txt = _dito(chave)
    if comparar:
        da, aa = cc.intervalo_anterior(chave)
        c = cc.comparar_margens(de=de, ate=ate, de_anterior=da, ate_anterior=aa, agrupar=agrupar)
        t, antes, grupos = c["atual"], c["anterior"], c["grupos"]
    else:
        m = cc.margens(de=de, ate=ate, agrupar=agrupar)
        t, antes, grupos, c = m["totais"], None, m["grupos"], m
    estimada = "É margem estimada: não inclui " + _nao_inclui(cc.NAO_INCLUI_MARGEM) + "."
    if not t["vendas"]:
        texto = f"{_cap(quando_txt)} não há venda concluída, então não há margem estimada."
        if comparar and antes["margem_pct"] is not None:
            texto += f" {_cap(_PERIODOS[chave][2])}, a margem estimada foi de {_pct(antes['margem_pct'])}."
    elif t["margem_pct"] is None:
        texto = (f"{_cap(quando_txt)}, {_n(t['vendas'], 'venda')} somando {reais(t['receita'])}, mas nenhuma com "
                 f"custo confiável: não dá para dizer a margem estimada. {_fora_txt(t['fora'])}")
    else:
        texto = (f"Margem estimada {quando_txt}: {_pct(t['margem_pct'])}, {reais(t['margem'])} sobre "
                 f"{reais(t['receita_com_custo'])} de vendas com custo.")
        if comparar:
            pontos = c["variacao"]["pontos"]
            if pontos is not None:
                texto += (f" Em relação {_PERIODOS[chave][1]}, {_pontos(pontos)}; era "
                          f"{_pct(antes['margem_pct'])}.")
            else:
                texto += f" Não há margem estimada {_PERIODOS[chave][2]} para comparar."
        if t["desconto"] > 0:
            texto += f" Descontos sobre a tabela: {reais(t['desconto'])}."
        if t["fora"]["linhas"]:
            texto += " " + _fora_txt(t["fora"])
        if len(grupos) > 1 or agrupar != "produto":
            vistos = [g for g in grupos if (g.get("receita") or ZERO) > 0][:MAX_FALADOS]
            sobra = len([g for g in grupos if (g.get("receita") or ZERO) > 0]) - len(vistos)
            rotulo = {"apresentacao": "jeito de vender", "dia": "dia"}.get(agrupar, agrupar)
            texto += (f" Por {rotulo}: " + "; ".join(_grupo_txt(g, comparar) for g in vistos)
                      + (f"; e mais {sobra} nos dados" if sobra > 0 else "") + ".")
    if t["vendas"] or (comparar and antes["margem_pct"] is not None):
        texto += " " + estimada
    saida = {"periodo": chave, "de": de, "ate": ate, "agrupar": agrupar, "rotulo": "estimada",
             "inclui": cc.INCLUI_MARGEM, "nao_inclui": cc.NAO_INCLUI_MARGEM, "totais": _totais(t),
             "grupos": [{k: g.get(k) for k in ("chave", "nome", "receita", "receita_anterior", "margem",
                                                 "margem_pct", "margem_pct_anterior", "pontos") if k in g}
                        for g in grupos],
             "texto": texto.strip()}
    if comparar:
        saida |= {"de_anterior": c["de_anterior"], "ate_anterior": c["ate_anterior"], "anterior": _totais(antes),
                  "variacao": c["variacao"]}
    return _json(saida)


# --- ver_margem_tabela ---------------------------------------------------------------------

def _apres_txt(a) -> str:
    nome = f"{a['nome']} de {a['produto']}, {a['forma']} {a['estado']}"
    if a["erro"]:
        problema = "o produto não tem ficha técnica" if a["erro"] == "Produto não encontrado." else \
            f"a ficha tem um problema ({a['erro'].rstrip('.')})"
        return f"{nome}: sem custo estimado, {problema}"
    if not a["completo"]:
        return f"{nome}: sem custo estimado, {_faltando_txt(a['faltando'])}"
    t = f"{nome}: custo estimado {_rs(a['custo'])}; no varejo, {reais(a['preco_varejo'])}"
    if a["margem_varejo_pct"] is not None:
        t += f", margem estimada de {_pct(a['margem_varejo_pct'])}, {reais(a['margem_varejo'])}"
    if a["preco_atacado"] is not None and a["margem_atacado_pct"] is not None:
        t += f"; no atacado, {reais(a['preco_atacado'])}, {_pct(a['margem_atacado_pct'])}"
    return t


def ver_margem_tabela(produto=""):
    lista = cc.margem_apresentacoes()
    busca = (produto or "").strip()
    if busca:
        lista = [a for a in lista if _casa(busca, a["produto"])]
        if not lista:
            raise ConsultaInvalida(f"Nenhum preço de tabela para '{busca}'.", 404)
    if not lista:
        texto = "Não há preço de tabela cadastrado."
    else:
        frases = [_apres_txt(a) for a in lista]
        sobra = len(frases) - MAX_FALADOS
        texto = ("; ".join(frases[:MAX_FALADOS]) + (f"; e mais {sobra} nos dados" if sobra > 0 else "") + ". "
                 "Margem estimada pelo preço de tabela de hoje e pela última compra de cada ingrediente; "
                 "não inclui indiretos, perdas da produção, tributos nem despesas.")
    return _json({"rotulo": "estimada", "apresentacoes": [
        {k: a[k] for k in ("apresentacao_id", "produto", "nome", "forma", "estado", "unidades", "preco_varejo",
                           "preco_atacado", "custo_salgado", "custo_embalagem", "custo", "completo", "faltando",
                           "erro", "margem_varejo", "margem_varejo_pct", "margem_atacado", "margem_atacado_pct",
                           "nao_inclui")} for a in lista], "texto": texto})


# --- ver_mais_vendidos -------------------------------------------------------------------

_ORDINAIS = ("primeiro", "segundo", "terceiro", "quarto", "quinto")


def _ordem(valor) -> str:
    v = _normal(valor or "receita")
    if any(p in v for p in ("marge", "lucr", "ganh")):
        return "margem"
    if any(p in v for p in ("unidad", "quant", "volum")):
        return "unidades"
    if any(p in v for p in ("receit", "fatur", "dinheir", "valor", "vend")):
        return "receita"
    raise ConsultaInvalida("'ordem' é receita, unidades ou margem.")


def ver_mais_vendidos(periodo="mes", ordem="receita"):
    chave, de, ate = _periodo(periodo)
    ordem = _ordem(ordem)
    r = cc.ranking_produtos(de=de, ate=ate, ordem=ordem)
    produtos = r["produtos"]
    quando_txt = _dito(chave)
    com = [p for p in produtos if p["participacao_pct"] is not None]
    if not produtos:
        texto = f"{_cap(quando_txt)} não há venda concluída."
    else:
        def frase(i, p):
            if ordem == "receita":
                valor = reais(p["receita"])
            elif ordem == "unidades":
                valor = _un(p["unidades"])
            else:
                valor = f"{reais(p['margem'])} de margem estimada, {_pct(p['margem_pct'])}"
            return f"{_ORDINAIS[i - 1]}, {p['nome']}, {valor}, {_pct(p['participacao_pct'])} do total"

        criterio = {"receita": "pelo que vendeu em dinheiro", "unidades": "pelas unidades vendidas",
                    "margem": "pela margem estimada"}[ordem]
        if com:
            texto = (f"{_cap(quando_txt)}, {criterio}: " + "; ".join(frase(i + 1, p) for i, p in
                                                                     enumerate(com[:MAX_FALADOS])))
            sobra = len(com) - MAX_FALADOS
            texto += (f"; e mais {_n(sobra, 'produto')} nos dados" if sobra > 0 else "") + "."
        else:
            texto = f"{_cap(quando_txt)}, nenhum produto com margem estimada: o custo das vendas não é confiável."
        sem = len(produtos) - len(com)
        if sem and ordem == "margem":
            texto += (f" {_n(sem, 'produto ficou', 'produtos ficaram')} fora por custo não confiável.")
        if ordem == "margem":
            texto += " É margem estimada, antes das despesas."
    return _json({"periodo": chave, "de": de, "ate": ate, "ordem": ordem, "total": r["total"], "rotulo": "estimada",
                  "produtos": [{k: p[k] for k in ("chave", "nome", "unidades", "receita", "margem", "margem_pct",
                                                  "participacao_pct", "acumulado_pct")} | {"produto_id": p["chave"]}
                               for p in produtos],
                  "texto": texto})


# --- ver_previsto_realizado ---------------------------------------------------------------

def _producao_txt(d) -> str:
    perdas = d["perdas"] or 0
    t = (f"Produção {d['producao_id']} de {d['produto']}, {d['forma']}, concluída "
         f"{quando(d['data']).removeprefix('em ') if d['data'] else 'sem data'}: planejadas {_un(d['unidades'])}, "
         f"saíram {d['boas'] or 0} boas")
    if perdas:
        t += f" e {perdas} {'perdida' if perdas == 1 else 'perdidas'}" + (f" ({d['perda_motivo']})"
                                                                          if d["perda_motivo"] else "")
    if d["rendimento_pct"] is not None:
        t += f", rendimento de {_pct(d['rendimento_pct'])}"
    t += "."
    if d["custo_previsto"] is None:
        t += f" Sem custo previsto: {_faltando_txt(d['faltando'])}."
    else:
        t += f" Custo previsto {reais(d['custo_previsto'])}, real {reais(d['custo_real'])}"
        desvio = d["desvio_custo"]
        if desvio:
            t += (f": {reais(abs(desvio))} a {'mais' if desvio > 0 else 'menos'}"
                  + (f", {_pct(abs(d['desvio_custo_pct']))} {'acima' if desvio > 0 else 'abaixo'}"
                     if d["desvio_custo_pct"] is not None else ""))
        else:
            t += ", igual ao previsto"
        t += "."
        if d["custo_unitario_real"] is not None and d["custo_unitario_previsto"] is not None:
            t += (f" Por unidade boa, {_rs(d['custo_unitario_real'])}; o previsto era "
                  f"{_rs(d['custo_unitario_previsto'])}.")
    if d["custo_pendente"]:
        t += " Atenção: o custo ainda tem consumo pendente de conciliar; o real pode subir."
    passaram = sorted((i for i in d["itens"] if i["desvio_pct"]), key=lambda i: -abs(i["desvio_pct"]))
    if passaram:
        t += " Ingredientes fora do previsto: " + "; ".join(
            f"{i['item']}, usou {qtd(i['usado'], i['unidade_base'])} contra {qtd(i['previsto'], i['unidade_base'])}, "
            f"{_pct(abs(i['desvio_pct']))} a {'mais' if i['desvio_pct'] > 0 else 'menos'}"
            for i in passaram[:MAX_FALADOS]) + "."
    return t


def _por_produto_txt(g) -> str:
    t = (f"{g['produto']}: {_n(g['producoes'], 'produção', 'produções')}, {_un(g['unidades'])} planejadas, "
         f"{g['boas']} boas")
    if g["perdas"]:
        t += f" e {g['perdas']} {'perdida' if g['perdas'] == 1 else 'perdidas'}"
    if g["rendimento_pct"] is not None:
        t += f", rendimento de {_pct(g['rendimento_pct'])}"
    if g["custo_previsto"] is not None:
        desvio = g["desvio_custo"]
        t += f"; custo previsto {reais(g['custo_previsto'])}, real {reais(g['custo_real'])}"
        if desvio:
            t += f", {reais(abs(desvio))} a {'mais' if desvio > 0 else 'menos'}"
            if g["desvio_custo_pct"] is not None:
                t += f" ({_pct(abs(g['desvio_custo_pct']))})"
        if g["comparadas"] < g["producoes"]:
            t += f", comparando {_n(g['comparadas'], 'produção', 'produções')}"
    else:
        t += "; sem custo para comparar"
    return t


def ver_previsto_realizado(producao_id=None, periodo="semana", produto=""):
    if producao_id not in (None, ""):
        pid = _inteiro(producao_id, "producao_id")
        d = cc.previsto_realizado_producao(pid)
        if d is None:
            raise ConsultaInvalida(f"A produção {pid} não existe ou ainda não foi concluída.", 404)
        return _json({**d, "texto": _producao_txt(d)})
    chave, de, ate = _periodo(periodo)
    p = None
    if (produto or "").strip():
        p = escolher(Item.objects.filter(tipo="produto", ficha__isnull=False).order_by("nome"), produto,
                     oque="produto")
    r = cc.previsto_realizado(de=de, ate=ate, produto_id=p.id if p else None)
    lista, quando_txt = r["producoes"], _dito(chave)
    de_quem = f" de {p.nome}" if p else ""
    if not lista:
        texto = f"{_cap(quando_txt)}, nenhuma produção{de_quem} concluída."
    elif len(lista) == 1:
        texto = _producao_txt(lista[0])
    else:
        ultima = lista[-1]
        texto = (f"{_cap(quando_txt)}, {_n(len(lista), 'produção concluída', 'produções concluídas')}{de_quem}. "
                 + "; ".join(_por_produto_txt(g) for g in r["por_produto"][:MAX_FALADOS])
                 + (f"; e mais {len(r['por_produto']) - MAX_FALADOS} produtos nos dados"
                    if len(r["por_produto"]) > MAX_FALADOS else "") + ".")
        fora = []
        if r["fora"]["custo_pendente"]:
            fora.append(f"{_n(len(r['fora']['custo_pendente']), 'produção', 'produções')} com custo pendente")
        if r["fora"]["sem_previsto"]:
            fora.append(f"{_n(len(r['fora']['sem_previsto']), 'produção', 'produções')} sem compra de algum "
                        "ingrediente até o dia")
        if fora:
            texto += f" Ficaram fora da comparação de custo: {_juntar(fora)}."
        texto += f" A última foi a produção {ultima['producao_id']}, de {ultima['produto']}."
    return _json({"periodo": chave, "de": de, "ate": ate, "producoes": [
        {k: d[k] for k in ("producao_id", "produto", "forma", "data", "unidades", "boas", "perdas", "rendimento_pct",
                           "custo_previsto", "custo_real", "custo_pendente", "desvio_custo", "desvio_custo_pct",
                           "custo_unitario_previsto", "custo_unitario_real")} for d in lista[-20:]],
        "por_produto": r["por_produto"], "fora": r["fora"], "texto": texto})


# --- ver_relatorio ----------------------------------------------------------------------

def ver_relatorio(periodo="mes"):
    chave, de, ate = _periodo(periodo)
    r = relatorio_periodo(de=de, ate=ate)
    v, res, pr, pe, d, pos = r["vendas"], r["resultado"], r["producao"], r["perdas"], r["dinheiro"], r["posicao"]
    t = v["totais"]
    faixa = "" if de == ate else f", {_faixa(de, ate)}"
    partes = [f"{_cap(_dito(chave))}{faixa}, tudo estimado e antes das despesas."]
    if t["vendas"]:
        venda = f"Vendas: {_n(t['vendas'], 'venda')}, {reais(t['receita'])}"
        if t["margem_pct"] is not None:
            venda += f", com margem estimada de {_pct(t['margem_pct'])}"
        partes.append(venda + ".")
    else:
        partes.append("Nenhuma venda concluída.")
    if pe["valor_total"]:
        partes.append(f"Perdas com valor: {reais(pe['valor_total'])}.")
    if t["vendas"] or pe["valor_total"]:
        resultado = f"Resultado estimado, antes das despesas: {reais(res['resultado'])}"
        if res["resultado_pct"] is not None:
            resultado += f", {_pct(res['resultado_pct'])} da receita"
        partes.append(resultado + ".")
    if pr["producoes"]:
        partes.append(f"Produção: {_n(pr['producoes'], 'produção', 'produções')}, {pr['boas']} boas de "
                      f"{pr['unidades']} planejadas.")
    if r["compras"]["compras"]:
        partes.append(f"Compras: {reais(r['compras']['total'])}.")
    if d["entrou"] or d["saiu"]:
        partes.append(f"Dinheiro anotado: entrou {reais(d['entrou'])}, saiu {reais(d['saiu'])}.")
    contas = []
    if pos["a_receber"]:
        contas.append(f"a receber {reais(pos['a_receber'])}")
    if pos["a_pagar"]:
        contas.append(f"a pagar {reais(pos['a_pagar'])}")
    if contas:
        partes.append(f"Hoje, em aberto: {_juntar(contas)}.")
    partes.append(f"O resultado não desconta {_nao_inclui(res['nao_inclui'])}.")
    if r["ressalvas"]:
        partes.append("Ressalva: " + " ".join(r["ressalvas"]))
    return _json({"periodo": chave, "de": de, "ate": ate, "dias": r["dias"], "rotulo": "estimado",
                  "vendas": {"totais": _totais(t), "custo_gravado": v["custo_gravado"],
                             "recebido_na_hora": v["recebido_na_hora"], "a_prazo": v["a_prazo"],
                             "canceladas": v["canceladas"]["vendas"]},
                  "encomendas": r["encomendas"],
                  "producao": {k: pr[k] for k in ("producoes", "unidades", "boas", "perdas", "custo_real",
                                                  "custo_pendente", "perdas_por_motivo")},
                  "perdas": {k: pe[k] for k in ("valor_movimentos", "valor_total", "unidades_producao",
                                                "unidades_fritura")}
                  | {"vendas_canceladas": pe["vendas_canceladas"]["valor"]},
                  "compras": {"compras": r["compras"]["compras"], "total": r["compras"]["total"]},
                  "dinheiro": d, "posicao": pos, "resultado": res, "ressalvas": r["ressalvas"],
                  "texto": " ".join(partes)})


# --- ver_evolucao_preco ------------------------------------------------------------------

def ver_evolucao_preco(item):
    i = _item(item)
    e = cc.evolucao_preco(item_id=i.id)
    fator, por = _POR.get(i.unidade_base, (1, f"por {i.unidade_base}"))

    def preco(c):
        return (c["custo_unitario"] * fator).quantize(CENTAVO, ROUND_HALF_UP)

    compras = e["compras"]
    if not compras:
        texto = f"Ainda não há compra de {i.nome}: não há preço para comparar."
    elif len(compras) == 1:
        c = compras[0]
        texto = (f"Só há uma compra de {i.nome}: {quando(c['data'])}, do fornecedor {c['fornecedor']}, "
                 f"{reais(preco(c))} {por}. Não há preço anterior para comparar.")
    else:
        ult, ant, pri = compras[-1], compras[-2], compras[0]
        texto = (f"{i.nome}: a última compra, {quando(ult['data'])}, do fornecedor {ult['fornecedor']}, saiu a "
                 f"{reais(preco(ult))} {por}; a anterior, {quando(ant['data'])}, a {reais(preco(ant))}")
        if ult["variacao_pct"] is not None:
            texto += f": {_variacao(ult['variacao_pct'])}"
        texto += "."
        if len(compras) > 2 and e["variacao_pct"] is not None:
            texto += (f" Desde a primeira compra, {quando(pri['data'])}, a {reais(preco(pri))}, "
                      f"{_variacao(e['variacao_pct'])} em {_n(len(compras), 'compra')}.")
        texto += " Preço com frete e desconto rateados."
    return _json({"item_id": i.id, "item": i.nome, "unidade_base": i.unidade_base, "por": por,
                  "compras": [{**c, "preco": preco(c)} for c in compras[-20:]], "primeiro": e["primeiro"],
                  "ultimo": e["ultimo"], "variacao_pct": e["variacao_pct"], "texto": texto})
