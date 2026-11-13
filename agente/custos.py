"""Custos, margens, relatórios e estudo de preço pelo agente de voz (Planos 7 e 8, fase 2b) — só leitura (nível 0).

Mesmo padrão de `vendas.py`: produto, preparação e item chegam pelo nome falado e são resolvidos aqui
(ambíguo vira `ConsultaInvalida` com `opcoes`); o período é falado ("semana", "mês passado") e vira datas
por `custos.consultas.intervalo`. Cada ferramenta devolve os números do núcleo (Decimal como número, datas
ISO) e um `texto` curto pronto para falar, com dinheiro por extenso e porcentagens e pontos já calculados.

O modelo de voz não faz conta nenhuma (design A3): toda diferença, porcentagem e ponto vem pronto de
`custos.fichas`, `custos.consultas`, `custos.relatorios` e `custos.precos`. Toda margem é dita "estimada" e o
resultado "estimado", antes e depois das despesas (RF-CUS-06, CA-33); a margem com indiretos é dita como tal,
separada da margem só de ingredientes; o que ficou fora é dito com o motivo; dado faltante (despesa sem valor,
taxa não informada) é dito como faltante, nunca como zero. Estudo e simulação de preço (Plano 8) não escolhem
margem nem gravam preço: a simulação é sempre dita "simulação" e o preço só muda pela tela. Nenhuma ferramenta
daqui grava nada.
"""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from cadastros.models import Item
from custos import consultas as cc
from custos import precos
from custos.fichas import custo_estimado, custo_preparacao
from custos.relatorios import relatorio_periodo
from fichas.models import Ficha

from .compras import _POR, MESES, _item, _juntar, _n, mes_falado, qtd, quando, reais
from .consultas import ConsultaInvalida, _casa, _filtrar, _inteiro, _normal, escolher
from .acoes import _decimal
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
                              "receita_com_custo", "custo", "margem", "margem_pct", "indiretos",
                              "margem_com_indiretos", "margem_com_indiretos_pct", "linhas_sem_indireto")} | {
        "fora": {"linhas": t["fora"]["linhas"], "receita": t["fora"]["receita"], "motivos": t["fora"]["motivos"]}}


def _com_indiretos_txt(t) -> str:
    """A margem com indiretos (Plano 8): é outra margem, e o texto diz qual é."""
    if t.get("margem_com_indiretos_pct") is not None:
        return (f" Com os indiretos de referência por salgado (mão de obra, energia e gás), a margem estimada fica "
                f"em {_pct(t['margem_com_indiretos_pct'])}, {reais(t['margem_com_indiretos'])}.")
    if t.get("linhas_sem_indireto"):
        return (f" A margem com indiretos não dá para dizer: {_n(t['linhas_sem_indireto'], 'item de venda')} de "
                "produto sem indireto de referência cadastrado.")
    return ""


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
    if t["vendas"] and t["margem_pct"] is not None:
        texto += _com_indiretos_txt(t)
    saida = {"periodo": chave, "de": de, "ate": ate, "agrupar": agrupar, "rotulo": "estimada",
             "rotulo_com_indiretos": cc.ROTULO_INDIRETOS,
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
    if a.get("margem_varejo_com_indiretos_pct") is not None:
        t += (f"; com os indiretos de referência, {_rs(a['indiretos'])}, a margem estimada no varejo fica em "
              f"{_pct(a['margem_varejo_com_indiretos_pct'])}")
        if a["preco_atacado"] is not None and a.get("margem_atacado_com_indiretos_pct") is not None:
            t += f" e no atacado em {_pct(a['margem_atacado_com_indiretos_pct'])}"
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
        if any(a.get("margem_varejo_com_indiretos_pct") is not None for a in lista):
            texto += (" A margem com indiretos é outra: desconta também os indiretos de referência por salgado "
                      "(mão de obra, energia e gás).")
    return _json({"rotulo": "estimada", "apresentacoes": [
        {k: a[k] for k in ("apresentacao_id", "produto", "nome", "forma", "estado", "unidades", "preco_varejo",
                           "preco_atacado", "custo_salgado", "custo_embalagem", "custo", "completo", "faltando",
                           "erro", "margem_varejo", "margem_varejo_pct", "margem_atacado", "margem_atacado_pct",
                           "indiretos", "custo_com_indiretos", "margem_varejo_com_indiretos",
                           "margem_varejo_com_indiretos_pct", "margem_atacado_com_indiretos",
                           "margem_atacado_com_indiretos_pct", "nao_inclui")} for a in lista], "texto": texto})


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


# --- ver_relatorio e ver_resultado: antes e depois das despesas ---------------------------

def _faltando_despesa_txt(faltando) -> str:
    """"falta o valor de Internet de novembro"."""
    return "falta o valor de " + _juntar([f"{f['despesa']} de {mes_falado(f['competencia'])}" for f in faltando])


def _sem_despesa(r) -> bool:
    desp = r["despesas"]
    return not desp["por_categoria"] and not desp["faltando"]


def _depois_txt(r) -> str:
    """O resultado depois das despesas (Plano 8), com o que falta e o que ainda é previsto. Nunca "lucro"."""
    desp, dd = r["despesas"], r["depois_das_despesas"]
    if _sem_despesa(r):
        return ("Nenhuma despesa lançada no período: sem as despesas, não dá para dizer o resultado depois "
                "delas.")
    t = f"Despesas do período: {reais(desp['total'])}"
    if desp["rateado"]:
        t += ", com as mensais pela parte dos dias do período"
    t += ". Resultado estimado depois das despesas: "
    t += (f"negativo em {reais(abs(dd['resultado']))}" if dd["resultado"] < 0 else reais(dd["resultado"]))
    if dd["resultado_pct"] is not None:
        t += f", {_pct(dd['resultado_pct'])} da receita"
    t += "."
    if not dd["completo"]:
        t += f" Ainda incompleto: {_faltando_despesa_txt(dd['faltando'])}; o resultado de verdade é menor que este."
    previstas = [m["despesa"] for m in desp["mensais"] if m["situacao"] in ("aberta", "parcial")]
    if previstas:
        t += f" Ainda sem pagamento anotado, pelo valor lançado: {_juntar(previstas)}."
    return t


def _despesas_dados(desp) -> dict:
    return {"total": desp["total"], "indiretas": desp["indiretas"], "completo": desp["completo"],
            "rateado": desp["rateado"], "faltando": desp["faltando"], "ressalvas": desp["ressalvas"],
            "por_categoria": [{k: g[k] for k in ("categoria", "indireta", "valor", "lancamentos", "completo")}
                              for g in desp["por_categoria"]]}


def ver_resultado(periodo="mes"):
    chave, de, ate = _periodo(periodo)
    r = relatorio_periodo(de=de, ate=ate)
    res, dd, t = r["resultado"], r["depois_das_despesas"], r["vendas"]["totais"]
    faixa = "" if de == ate else f", {_faixa(de, ate)}"
    partes = [f"{_cap(_dito(chave))}{faixa}, tudo estimado."]
    if t["vendas"]:
        partes.append(f"Vendas: {reais(t['receita'])}. Resultado antes das despesas: {reais(res['resultado'])}.")
    else:
        partes.append("Nenhuma venda concluída no período.")
    partes.append(_depois_txt(r))
    if not _sem_despesa(r):
        partes.append("Por categoria: " + "; ".join(f"{g['categoria']}, {reais(g['valor'])}"
                                                    for g in r["despesas"]["por_categoria"][:MAX_FALADOS])
                      + (f"; e mais {len(r['despesas']['por_categoria']) - MAX_FALADOS}"
                         if len(r["despesas"]["por_categoria"]) > MAX_FALADOS else "") + ".")
    return _json({"periodo": chave, "de": de, "ate": ate, "rotulo": dd["rotulo"], "receita": res["receita"],
                  "resultado_antes": res["resultado"], "despesas": _despesas_dados(r["despesas"]),
                  "depois_das_despesas": dd, "texto": " ".join(partes)})


# --- ver_relatorio ----------------------------------------------------------------------

def ver_relatorio(periodo="mes"):
    chave, de, ate = _periodo(periodo)
    r = relatorio_periodo(de=de, ate=ate)
    v, res, pr, pe, d, pos = r["vendas"], r["resultado"], r["producao"], r["perdas"], r["dinheiro"], r["posicao"]
    t = v["totais"]
    faixa = "" if de == ate else f", {_faixa(de, ate)}"
    partes = [f"{_cap(_dito(chave))}{faixa}, tudo estimado."]
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
    partes.append(_depois_txt(r))
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
                  "dinheiro": d, "posicao": pos, "resultado": res, "despesas": _despesas_dados(r["despesas"]),
                  "depois_das_despesas": r["depois_das_despesas"], "ressalvas": r["ressalvas"],
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


# --- estudo de preço, simulação, ponto de equilíbrio e indireto real (Plano 8) ---------------------
# Só leitura. O sistema não escolhe margem e não grava preço: a simulação usa o preço ou a sobra que o dono
# disser e é sempre dita "simulação"; o preço só muda pela tela.

def _canal_dito(nome) -> str:
    """"Balcão — dinheiro" → "balcão, dinheiro" (o travessão não se fala)."""
    nome = nome.replace(" — ", ", ")
    return nome[:1].lower() + nome[1:]


def _canais(canal) -> list[dict]:
    """Os canais ativos que casam com o nome falado ("balcão" casa dinheiro e pix; "crédito", o cartão)."""
    lista = precos.canais_venda()
    if not (canal or "").strip():
        return lista
    achados = [c for c in lista if _casa(canal, c["nome"])]
    if not achados:
        raise ConsultaInvalida(f"Nenhum canal de venda com o nome '{canal}'.", 404,
                               opcoes=[c["nome"] for c in lista])
    return achados


def _canal_unico(canal):
    """Um canal para simular: vários com a mesma taxa (balcão dinheiro e pix) dão no mesmo, vale o primeiro."""
    if not (canal or "").strip():
        return None
    achados = _canais(canal)
    if len({c["taxa_pct"] for c in achados}) > 1:
        raise ConsultaInvalida(f"Mais de um canal com '{canal}'; pergunte qual.", 409,
                               opcoes=[c["nome"] for c in achados])
    return achados[0]["canal_id"]


def _sobra_txt(c, unidades) -> str:
    if c["taxa_pct"] is None:
        return "taxa não informada, sem conta"
    if c["sobra"] is None:
        if c["contribuicao"] is None:
            return "sem conta"
        return f"sem indiretos de referência; antes deles ficam {reais(c['contribuicao'])}"
    if c["sobra"] < 0:
        t = f"não sobra: fica negativo em {reais(abs(c['sobra']))}"
    else:
        t = f"sobram {reais(c['sobra'])}, {_pct(c['sobra_pct'])} do preço"
        if unidades > 1 and c["sobra_un"] is not None:
            t += f", {_rs(c['sobra_un'])} por salgado"
    if c["taxa"]:
        t += f", já descontada a taxa de {_rs(c['taxa'])}"
    return t


def _estudo_txt(a, canais) -> str:
    nome = f"{a['nome']} de {a['produto']}, {a['forma']}"
    if a["preco"] is None:
        return f"{nome}: sem preço de {a['tabela']}"
    if a["cmv"] is None:
        motivo = (_faltando_txt([f for f in a["faltando"] if f["motivo"] != "sem indiretos de referência por unidade"])
                  or a["erro"].rstrip(".") or "custo incompleto")
        return f"{nome}, a {reais(a['preco'])}: sem CMV, {motivo}"
    t = f"{nome}, a {reais(a['preco'])}: CMV de {_rs(a['cmv'])}, {_pct(a['cmv_pct'])} do preço"
    t += (f"; indiretos de referência, {_rs(a['indiretos'])}" if a["indiretos"] is not None
          else "; sem indiretos de referência")
    grupos = {}
    for c in a["por_canal"]:
        if c["canal_id"] in canais:
            grupos.setdefault(c["taxa_pct"] if c["taxa_pct"] is not None else "sem", []).append(c)
    t += ". " + _cap("; ".join(f"no {_juntar([_canal_dito(c['canal']) for c in cs])}, "
                               f"{_sobra_txt(cs[0], a['unidades'])}" for cs in grupos.values()))
    return t


def ver_estudo_preco(produto="", canal="", tabela="varejo"):
    from .vendas import _filtrar_por_produto, _tabela

    tabela = _tabela(tabela)
    e = precos.estudo_preco(tabela=tabela)
    lista = _filtrar_por_produto(e["apresentacoes"], produto, lambda a: f"{a['produto']} {a['nome']} {a['forma']}")
    canais = {c["canal_id"] for c in _canais(canal)}
    if (produto or "").strip() and not lista:
        raise ConsultaInvalida(f"Nenhum preço de tabela para '{produto}'.", 404)
    if not lista:
        texto = "Não há preço de tabela cadastrado."
    else:
        frases = [_estudo_txt(a, canais) for a in lista]
        sobra = len(frases) - MAX_FALADOS
        texto = (". ".join(frases[:MAX_FALADOS]) + (f". E mais {sobra} nos dados" if sobra > 0 else "")
                 + ". Estudo estimado pelo custo de hoje, pela última compra de cada ingrediente; o preço da tabela "
                   "não muda.")
    return _json({"tabela": tabela, "rotulo": "estimado", "observacao": e["observacao"],
                  "apresentacoes": [{**a, "por_canal": [c for c in a["por_canal"] if c["canal_id"] in canais]}
                                    for a in lista], "texto": texto})


def _apresentacao_dita(produto, apresentacao="", forma="", conservacao=""):
    from .vendas import _apresentacao

    if not (produto or "").strip():
        raise ConsultaInvalida("Diga o produto (ex.: coxinha, caixa com 25 de coxinha).")
    return _apresentacao({"produto": produto, "apresentacao": apresentacao, "forma": forma,
                          "conservacao": conservacao})


def _pct_dito(v):
    if v in (None, ""):
        return None
    t = _normal(str(v)).replace("%", "").replace("por cento", "").strip()
    return _decimal(t, "sobra_pct")


def simular_preco(produto, apresentacao="", preco=None, sobra_pct=None, canal="", tabela="varejo", forma="",
                  conservacao=""):
    from .vendas import _tabela

    apr = _apresentacao_dita(produto, apresentacao, forma, conservacao)
    pct = _pct_dito(sobra_pct)
    p = None if preco in (None, "", 0) else _decimal(preco, "preco")
    s = precos.simular_preco(apresentacao_id=apr.id, preco=p, sobra_pct=pct, canal_id=_canal_unico(canal),
                             tabela=_tabela(tabela))
    nome = f"{apr.nome} de {apr.produto.nome}, {apr.forma}"
    canal_txt = _canal_dito(s["canal"])
    if s["sobra_pct_pedida"] is None:
        texto = f"Simulação, o preço da tabela não muda: {nome} a {reais(s['preco'])} no {canal_txt}."
    else:
        texto = (f"Simulação, o preço da tabela não muda: para sobrar {_pct(s['sobra_pct_pedida'])} do preço no "
                 f"{canal_txt}, o sistema calcula {nome} a {reais(s['preco'])}"
                 + (f", {_rs(s['preco_un'])} por salgado" if s["unidades"] > 1 else "") + ".")
    texto += f" CMV de {_rs(s['cmv'])}, {_pct(s['cmv_pct'])} do preço"
    if s["inclui_indiretos"]:
        texto += f"; indiretos de referência, {_rs(s['indiretos'])}"
    if s["taxa"]:
        texto += f"; taxa do canal, {_rs(s['taxa'])}"
    if s["sobra"] < 0:
        texto += f"; não sobra: fica negativo em {reais(abs(s['sobra']))}."
    else:
        texto += f"; sobram {reais(s['sobra'])}, {_pct(s['sobra_pct'])} do preço"
        if s["sobra_pct_pedida"] is not None and s["sobra_pct"] != s["sobra_pct_pedida"]:
            texto += " (o preço foi arredondado ao centavo)"
        texto += (f", {_rs(s['sobra_un'])} por salgado." if s["unidades"] > 1 else ".")
    if not s["inclui_indiretos"]:
        texto += " Sem indiretos de referência: a sobra não desconta mão de obra, energia e gás."
    if s["preco_atual"] is not None:
        dif = s["diferenca_preco_atual"]
        texto += f" Hoje a tabela está em {reais(s['preco_atual'])}"
        texto += ("." if not dif else f": este preço fica {reais(abs(dif))} {'acima' if dif > 0 else 'abaixo'}.")
    texto += " É só uma simulação: o preço só muda pela tela, e quem decide é o dono."
    return _json({**s, "produto": apr.produto.nome, "apresentacao": apr.nome, "texto": texto})


def ver_ponto_equilibrio(produto, apresentacao="", canal="", mes="", forma="", conservacao="", tabela="varejo"):
    from .despesas import _competencia
    from .vendas import _plural, _tabela

    apr = _apresentacao_dita(produto, apresentacao, forma, conservacao)
    comp = _competencia(mes)
    p = precos.ponto_equilibrio(apresentacao_id=apr.id, competencia=comp, canal_id=_canal_unico(canal),
                                tabela=_tabela(tabela))
    nome_mes = mes_falado(p["competencia"])
    if not p["despesas"]:
        texto = (f"Nenhuma despesa com valor em {nome_mes}: sem as despesas, não há ponto de equilíbrio para "
                 "dizer.")
    else:
        texto = (f"Estimativa, como se todas as vendas fossem {apr.nome} de {apr.produto.nome}, {apr.forma}, a "
                 f"{reais(p['preco'])} no {_canal_dito(p['canal'])}: cada venda deixa {reais(p['contribuicao'])} "
                 f"depois do CMV e da taxa; as despesas de {nome_mes} somam {reais(p['despesas'])}. Para pagar as "
                 f"despesas, seria preciso vender {p['apresentacoes']} {_plural(apr.nome, p['apresentacoes'])}")
        if p["unidades_por"] > 1:
            texto += f", {_un(p['unidades'])}"
        texto += f", {reais(p['receita'])} de vendas no mês."
    if not p["completo"]:
        texto += (f" Ficou fora, sem valor: {_juntar(p['faltando'])}; com ela o número é maior."
                  if len(p["faltando"]) == 1 else
                  f" Ficaram fora, sem valor: {_juntar(p['faltando'])}; com elas o número é maior.")
    return _json({**p, "produto": apr.produto.nome, "apresentacao": apr.nome, "texto": texto})


def ver_indireto_real(mes=""):
    from .despesas import _competencia, _ultimo_dia

    comp = _competencia(mes)
    r = precos.indireto_real(competencia=comp)
    nome_mes = mes_falado(r["competencia"])
    andamento = r["ate"] < _ultimo_dia(r["competencia"])
    quando_txt = f"{nome_mes}, de {r['de'].day} a {r['ate'].day}" if andamento else nome_mes
    if not r["unidades_produzidas"]:
        texto = (f"Em {quando_txt}, nenhuma produção concluída: sem salgados para dividir as despesas, não dá "
                 "para conferir o indireto.")
    elif not r["despesas_indiretas"]:
        texto = (f"Em {quando_txt}, nenhuma despesa da produção lançada (mão de obra, energia, gás e diária): sem "
                 "elas, não dá para conferir o indireto"
                 + (f"; a referência cadastrada é {_rs(r['referencia_un'])}" if r["referencia_un"] is not None else "")
                 + ".")
    else:
        texto = (f"Conferência dos indiretos de {quando_txt}: {_un(r['unidades_produzidas'])} boas produzidas; as "
                 f"despesas da produção (mão de obra, energia, gás e diária) somam {reais(r['despesas_indiretas'])}"
                 + (", com as mensais pela parte dos dias até hoje" if andamento else "") + ".")
        if r["indireto_real_un"] is not None:
            texto += f" Dá {_rs(r['indireto_real_un'])} por salgado"
            if r["referencia_un"] is not None:
                texto += f"; a referência cadastrada é {_rs(r['referencia_un'])}"
                dif = r["diferenca_un"]
                if dif:
                    texto += (f": o real está {_rs(abs(dif))} {'acima' if dif > 0 else 'abaixo'}"
                              + (f", {_pct(abs(r['diferenca_pct']))}" if r["diferenca_pct"] else ""))
                else:
                    texto += ": igual"
            else:
                texto += "; nenhum produto produzido tem indireto de referência cadastrado"
            texto += "."
        if r["despesa_total_un"] is not None and r["despesa_total_un"] != r["indireto_real_un"]:
            texto += (" Com todas as despesas, inclusive as que não são da produção, dá "
                      f"{_rs(r['despesa_total_un'])} por salgado.")
    if not r["completo"]:
        texto += f" Incompleto: {_faltando_despesa_txt(r['faltando'])}; o real pode ser maior."
    texto += " É estimado."
    return _json({**r, "texto": texto})
