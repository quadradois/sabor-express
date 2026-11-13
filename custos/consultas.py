"""Previsto × realizado da produção, margens das vendas, comparação de períodos, margem estimada das
apresentações, ranking de produtos e evolução de preço (Plano 7) — só leitura.

Devolvem dicts com Decimal e date. Percentuais vêm em pontos percentuais (0–100, 1 casa) nos campos `*_pct`;
dinheiro com 2 casas; custo por unidade com 4. Onde falta dado, o retorno diz o que ficou de fora
(`fora`, `faltando`, `custo_pendente`) em vez de contar como zero. Toda margem é **estimada** (RF-CUS-06).
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from cadastros.models import Item
from compras.consultas import ultimo_custo
from compras.models import LinhaCompra
from estoque.models import ConsumoPendente, Lote, Movimento
from nucleo.models import RegistroOperacao
from nucleo.operacoes import RegraViolada
from producao.models import Fritura, Producao
from vendas.models import Apresentacao, LinhaVenda

from .fichas import custo_estimado

ZERO = Decimal("0")
CENT, Q1, Q4 = Decimal("0.01"), Decimal("0.1"), Decimal("0.0001")

INCLUI_MARGEM = ["preço praticado (já com desconto)",
                 "custo gravado na venda: lotes de salgado baixados e embalagem da apresentação"]
NAO_INCLUI_MARGEM = ["tributos sobre a venda", "despesas comerciais e operacionais",
                     "indiretos de fabricação (mão de obra, gás, energia)", "ajuste de óleo"]


def _rs(v):
    return None if v is None else v.quantize(CENT, ROUND_HALF_UP)


def _pct(parte, todo):
    """parte ÷ todo em pontos percentuais (1 casa); None sem base."""
    if parte is None or not todo:
        return None
    return (parte * 100 / todo).quantize(Q1, ROUND_HALF_UP)


def _variacao_pct(novo, antigo):
    if novo is None or not antigo:
        return None
    return ((novo - antigo) * 100 / antigo).quantize(Q1, ROUND_HALF_UP)


# ---------- períodos ----------

PERIODOS = ("hoje", "ontem", "semana", "semana_passada", "mes", "mes_passado", "ultimos_7", "ultimos_30")


def _mes_anterior(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def _mesmo_dia(inicio: date, dia: int) -> date:
    """O dia `dia` do mês de `inicio`, ou o último dia desse mês."""
    fim = (inicio.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return inicio.replace(day=min(dia, fim.day))


def intervalo(periodo, *, hoje=None) -> tuple[date, date]:
    """(de, ate) de um período falado. "semana" vai de segunda até hoje; "mes", do dia 1 até hoje."""
    hoje = hoje or timezone.localdate()
    segunda = hoje - timedelta(days=hoje.weekday())
    if periodo == "hoje":
        return hoje, hoje
    if periodo == "ontem":
        return hoje - timedelta(days=1), hoje - timedelta(days=1)
    if periodo == "semana":
        return segunda, hoje
    if periodo == "semana_passada":
        return segunda - timedelta(days=7), segunda - timedelta(days=1)
    if periodo == "mes":
        return hoje.replace(day=1), hoje
    if periodo == "mes_passado":
        inicio = _mes_anterior(hoje)
        return inicio, hoje.replace(day=1) - timedelta(days=1)
    if periodo in ("ultimos_7", "ultimos_30"):
        n = int(periodo.split("_")[1])
        return hoje - timedelta(days=n - 1), hoje
    raise RegraViolada(f"Período desconhecido: {periodo}. Use {', '.join(PERIODOS)}.")


def intervalo_anterior(periodo, *, hoje=None) -> tuple[date, date]:
    """O período com que comparar: o mesmo trecho do período anterior. "semana" (segunda a quinta) compara
    com segunda a quinta da semana passada; "mes" (1 a 13), com 1 a 13 do mês passado; "hoje" com ontem;
    "semana_passada"/"mes_passado" com a semana/mês inteiros de antes; "ultimos_N" com os N dias anteriores."""
    hoje = hoje or timezone.localdate()
    de, ate = intervalo(periodo, hoje=hoje)
    if periodo in ("semana", "semana_passada"):
        return de - timedelta(days=7), ate - timedelta(days=7)
    if periodo == "mes":
        inicio = _mes_anterior(de)
        return inicio, _mesmo_dia(inicio, ate.day)
    if periodo == "mes_passado":
        inicio = _mes_anterior(de)
        return inicio, de - timedelta(days=1)
    n = (ate - de).days + 1
    return de - timedelta(days=n), de - timedelta(days=1)


# ---------- previsto × realizado da produção ----------

def _conclusao(p) -> RegistroOperacao | None:
    return (RegistroOperacao.objects.filter(nome="concluir_producao", status="sucesso", parametros__producao_id=p.id)
            .order_by("id").first())


def _producao(p) -> dict:
    """Previsto × realizado de uma produção concluída (RF-OP-09, PRD §16)."""
    dia = timezone.localtime(p.encerrada_em).date() if p.encerrada_em else None
    op = _conclusao(p)
    itens = {}
    for l in p.linhas.select_related("item"):
        i = itens.setdefault(l.item_id, {"item_id": l.item_id, "item": l.item.nome, "unidade_base": l.item.unidade_base,
                                         "previsto": ZERO, "usado": ZERO, "custo_real": ZERO, "pendente": ZERO})
        i["previsto"] += l.previsto
        i["usado"] += l.usado or ZERO
    consumos = ZERO
    if op is not None:
        for m in Movimento.objects.filter(operacao=op, tipo="consumo_producao").select_related("lote"):
            c = -m.quantidade * m.lote.custo_unitario
            consumos += c
            if m.item_id in itens:
                itens[m.item_id]["custo_real"] += c
    for c in ConsumoPendente.objects.filter(producao=p):
        if c.item_id not in itens:
            continue
        if c.aberto:
            itens[c.item_id]["pendente"] += c.quantidade
        else:
            itens[c.item_id]["custo_real"] += c.custo
            consumos += c.custo
    previsto, faltando = ZERO, []
    for i in itens.values():
        r = ultimo_custo(i["item_id"], ate=dia)
        i["referencia"] = r["custo_unitario"] if r else None
        i["custo_previsto"] = _rs(i["previsto"] * r["custo_unitario"]) if r else None
        if r is None:
            faltando.append({"item_id": i["item_id"], "item": i["item"], "motivo": "sem compra até a produção"})
        else:
            previsto += i["previsto"] * r["custo_unitario"]
        i["custo_real"] = _rs(i["custo_real"])
        i["desvio_pct"] = _variacao_pct(i["usado"], i["previsto"])
    fritas = (p.quantidade_boa or 0) + (p.perdas or 0)
    oleo_real = oleo_previsto = ZERO
    if p.forma == "frito":
        # óleo apropriado = o que o custo gravado tem além dos consumos (óleo de referência × fritas)
        oleo_real = _rs(p.custo_total - consumos) if fritas else ZERO
        taxa = (p.custo_total - consumos) / fritas if fritas else (p.produto.oleo_ref_un or ZERO)
        oleo_previsto = _rs(taxa * p.unidades)
        previsto += oleo_previsto
    custo_previsto = None if faltando else _rs(previsto)
    real = p.custo_total
    unit_prev = (custo_previsto / p.unidades).quantize(Q4, ROUND_HALF_UP) if custo_previsto is not None else None
    return {
        "producao_id": p.id, "produto_id": p.produto_id, "produto": p.produto.nome, "forma": p.forma, "data": dia,
        "versao": p.versao.numero, "unidades": p.unidades, "boas": p.quantidade_boa, "perdas": p.perdas,
        "perda_motivo": p.perda_motivo, "rendimento_pct": _pct(Decimal(p.quantidade_boa or 0), p.unidades),
        "custo_previsto": custo_previsto, "custo_real": real, "custo_pendente": p.custo_pendente,
        "desvio_custo": None if custo_previsto is None else real - custo_previsto,
        "desvio_custo_pct": _variacao_pct(real, custo_previsto),
        "custo_unitario_previsto": unit_prev, "custo_unitario_real": p.custo_unitario,
        "desvio_unitario_pct": _variacao_pct(p.custo_unitario, unit_prev),
        "oleo_previsto": oleo_previsto, "oleo_real": oleo_real, "faltando": faltando,
        "itens": sorted(itens.values(), key=lambda i: i["item"]),
    }


def previsto_realizado_producao(producao_id) -> dict | None:
    """Uma produção concluída; None se não existe ou não foi concluída."""
    p = (Producao.objects.select_related("produto", "versao").filter(id=producao_id, status="concluida").first())
    return None if p is None else _producao(p)


def previsto_realizado(*, de=None, ate=None, produto_id=None) -> dict:
    """Produções concluídas no período (dia do encerramento) e, por produto, a soma: unidades planejadas, boas,
    perdas, rendimento (boas ÷ planejadas) e custo previsto × real. O custo só compara as produções `comparadas`
    (com custo fechado e referência de todos os itens); as outras ficam em `fora` com o motivo."""
    qs = Producao.objects.select_related("produto", "versao").filter(status="concluida").order_by("encerrada_em", "id")
    if produto_id:
        qs = qs.filter(produto_id=produto_id)
    lista = [d for d in (_producao(p) for p in qs)
             if (not de or (d["data"] and d["data"] >= de)) and (not ate or (d["data"] and d["data"] <= ate))]
    grupos = {}
    for d in lista:
        g = grupos.setdefault(d["produto_id"], {
            "produto_id": d["produto_id"], "produto": d["produto"], "producoes": 0, "unidades": 0, "boas": 0,
            "perdas": 0, "comparadas": 0, "unidades_comparadas": 0, "boas_comparadas": 0,
            "custo_previsto": ZERO, "custo_real": ZERO})
        g["producoes"] += 1
        g["unidades"] += d["unidades"]
        g["boas"] += d["boas"] or 0
        g["perdas"] += d["perdas"] or 0
        if d["custo_previsto"] is not None and not d["custo_pendente"]:
            g["comparadas"] += 1
            g["unidades_comparadas"] += d["unidades"]
            g["boas_comparadas"] += d["boas"] or 0
            g["custo_previsto"] += d["custo_previsto"]
            g["custo_real"] += d["custo_real"]
    por_produto = []
    for g in sorted(grupos.values(), key=lambda g: g["produto"]):
        tem = g["comparadas"] > 0
        prev, real = (g["custo_previsto"], g["custo_real"]) if tem else (None, None)
        por_produto.append({
            **g, "custo_previsto": prev, "custo_real": real,
            "rendimento_pct": _pct(Decimal(g["boas"]), g["unidades"]),
            "desvio_custo": None if not tem else real - prev, "desvio_custo_pct": _variacao_pct(real, prev),
            "custo_unitario_previsto": (prev / g["unidades_comparadas"]).quantize(Q4, ROUND_HALF_UP) if tem else None,
            "custo_unitario_real": (real / g["boas_comparadas"]).quantize(Q4, ROUND_HALF_UP)
            if tem and g["boas_comparadas"] else None})
    return {"de": de, "ate": ate, "producoes": lista, "por_produto": por_produto,
            "fora": {"custo_pendente": [d["producao_id"] for d in lista if d["custo_pendente"]],
                     "sem_previsto": [d["producao_id"] for d in lista if d["custo_previsto"] is None]}}


# ---------- margem das vendas ----------

def _producao_do_lote(lote_ids) -> dict:
    """lote de salgado → produção que o gerou (direto, ou pelo lote cru de onde a fritura veio)."""
    mapa = {p.lote_id: p.id for p in Producao.objects.filter(lote_id__in=lote_ids)}
    for f in Fritura.objects.filter(lote_id__in=lote_ids).select_related("lote_origem__producao"):
        origem = getattr(f.lote_origem, "producao", None)
        if origem is not None:
            mapa[f.lote_id] = origem.id
    return mapa


def _pendencias_por_producao(producao_ids) -> dict:
    """produção → [(aberto, quando foi conciliado)] dos consumos pendentes."""
    saida = defaultdict(list)
    for c in (ConsumoPendente.objects.filter(producao_id__in=producao_ids)
              .select_related("conciliacao_operacao")):
        saida[c.producao_id].append((c.aberto, c.conciliacao_operacao.criado_em if c.conciliacao_operacao else None))
    return saida


def _linhas_venda(de, ate, *, cliente_id=None, produto_id=None, venda_id=None) -> list[dict]:
    qs = (LinhaVenda.objects.filter(venda__situacao="concluida")
          .select_related("venda__cliente", "venda__operacao", "apresentacao__produto").order_by("venda__data", "id"))
    if venda_id:
        qs = qs.filter(venda_id=venda_id)
    if de:
        qs = qs.filter(venda__data__gte=de)
    if ate:
        qs = qs.filter(venda__data__lte=ate)
    if cliente_id:
        qs = qs.filter(venda__cliente_id=cliente_id)
    if produto_id:
        qs = qs.filter(apresentacao__produto_id=produto_id)
    linhas = list(qs)
    lotes = {int(b["lote_id"]) for l in linhas for b in l.baixas if int(b["item_id"]) == l.apresentacao.produto_id}
    prod_do_lote = _producao_do_lote(lotes)
    pendencias = _pendencias_por_producao(set(prod_do_lote.values()))
    saida = []
    for l in linhas:
        v, a = l.venda, l.apresentacao
        motivo = ""
        if l.custo <= 0:
            motivo = "custo zero gravado"
        else:
            for b in l.baixas:
                for aberto, quando in pendencias.get(prod_do_lote.get(int(b["lote_id"])), []):
                    if aberto:
                        motivo = "custo pendente na produção do lote"
                    elif quando and quando > v.operacao.criado_em and not motivo:
                        motivo = "custo gravado antes da conciliação do consumo pendente"
        salgado = sum((Decimal(b["custo"]) for b in l.baixas if int(b["item_id"]) == a.produto_id), ZERO)
        saida.append({
            "linha_id": l.id, "venda_id": v.id, "data": v.data, "cliente_id": v.cliente_id,
            "cliente": v.cliente.nome if v.cliente else "", "tabela": v.tabela, "apresentacao_id": a.id,
            "apresentacao": str(a), "produto_id": a.produto_id, "produto": a.produto.nome,
            "quantidade": l.quantidade, "unidades": l.quantidade * l.unidades_por,
            "preco_tabela": l.preco_tabela, "preco": l.preco, "receita": l.total,
            "receita_tabela": _rs(l.preco_tabela * l.quantidade), "custo": l.custo, "custo_salgado": salgado,
            "custo_embalagem": l.custo - salgado, "margem": None if motivo else l.total - l.custo,
            "margem_pct": None if motivo else _pct(l.total - l.custo, l.total), "fora_motivo": motivo})
    return saida


AGRUPAMENTOS = {
    "produto": lambda l: (l["produto_id"], l["produto"]),
    "apresentacao": lambda l: (l["apresentacao_id"], l["apresentacao"]),
    "cliente": lambda l: (l["cliente_id"], l["cliente"] or "Sem cliente (balcão)"),
    "tabela": lambda l: (l["tabela"], l["tabela"]),
    "dia": lambda l: (l["data"], l["data"]),
}


def _somar(linhas) -> dict:
    receita = sum((l["receita"] for l in linhas), ZERO)
    tabela = sum((l["receita_tabela"] for l in linhas), ZERO)
    boas = [l for l in linhas if not l["fora_motivo"]]
    fora = [l for l in linhas if l["fora_motivo"]]
    rc = sum((l["receita"] for l in boas), ZERO)
    custo = sum((l["custo"] for l in boas), ZERO)
    motivos = defaultdict(int)
    for l in fora:
        motivos[l["fora_motivo"]] += 1
    return {"vendas": len({l["venda_id"] for l in linhas}), "linhas": len(linhas),
            "quantidade": sum(l["quantidade"] for l in linhas), "unidades": sum(l["unidades"] for l in linhas),
            "receita": receita, "receita_tabela": tabela, "desconto": tabela - receita,
            "receita_com_custo": rc, "custo": custo, "margem": rc - custo if boas else None,
            "margem_pct": _pct(rc - custo, rc),
            "fora": {"linhas": len(fora), "receita": sum((l["receita"] for l in fora), ZERO),
                     "motivos": dict(motivos), "linha_ids": [l["linha_id"] for l in fora]}}


def margens(*, de=None, ate=None, agrupar="produto", cliente_id=None, produto_id=None) -> dict:
    """Margem **estimada** das vendas concluídas no período (canceladas fora), por `agrupar` ("produto",
    "apresentacao", "cliente", "tabela", "dia"). Margem = receita (preço praticado) − custo gravado na linha
    (RN-30); `margem_pct` = margem ÷ receita. Linhas com custo duvidoso (zero, ou de lote com consumo pendente
    não conciliado na hora da venda) ficam **fora da margem**, mas dentro da receita: `fora` diz quantas,
    quanto e por quê. `desconto` = preço de tabela − praticado."""
    if agrupar not in AGRUPAMENTOS:
        raise RegraViolada(f"Agrupamento desconhecido: {agrupar}.")
    linhas = _linhas_venda(de, ate, cliente_id=cliente_id, produto_id=produto_id)
    return {"de": de, "ate": ate, "agrupar": agrupar, "rotulo": "estimada", "inclui": INCLUI_MARGEM,
            "nao_inclui": NAO_INCLUI_MARGEM, "totais": _somar(linhas), "grupos": _agrupar(linhas, agrupar)}


def _agrupar(linhas, agrupar) -> list[dict]:
    grupos = defaultdict(list)
    for l in linhas:
        grupos[AGRUPAMENTOS[agrupar](l)].append(l)
    lista = [{"chave": k[0], "nome": str(k[1]), **_somar(ls)} for k, ls in grupos.items()]
    if agrupar == "dia":
        return sorted(lista, key=lambda g: g["chave"])
    return sorted(lista, key=lambda g: (-g["receita"], g["nome"]))


def margem_das_linhas(*, venda_id) -> list[dict]:
    """Margem de cada linha de uma venda (concluída), com `fora_motivo` quando o custo é duvidoso."""
    return _linhas_venda(None, None, venda_id=venda_id)


def comparar_margens(*, de, ate, de_anterior=None, ate_anterior=None, agrupar="produto") -> dict:
    """Dois períodos lado a lado ("sua margem caiu 6 pontos"). Sem `de_anterior`/`ate_anterior`, compara com
    os mesmos tantos dias logo antes. `pontos` = margem_pct atual − anterior (pontos percentuais); `None`
    quando um dos lados não tem margem."""
    if de_anterior is None or ate_anterior is None:
        n = (ate - de).days + 1
        de_anterior, ate_anterior = de - timedelta(days=n), de - timedelta(days=1)
    atual = margens(de=de, ate=ate, agrupar=agrupar)
    anterior = margens(de=de_anterior, ate=ate_anterior, agrupar=agrupar)
    a, b = atual["totais"], anterior["totais"]

    def pontos(x, y):
        return None if x is None or y is None else x - y

    agora_por = {g["chave"]: g for g in atual["grupos"]}
    antes_por = {g["chave"]: g for g in anterior["grupos"]}
    grupos = []
    for k in list(agora_por) + [k for k in antes_por if k not in agora_por]:
        agora, velho = agora_por.get(k), antes_por.get(k)
        pct, pct_antes = (agora or {}).get("margem_pct"), (velho or {}).get("margem_pct")
        grupos.append({"chave": k, "nome": (agora or velho)["nome"],
                       "receita": agora["receita"] if agora else ZERO,
                       "receita_anterior": velho["receita"] if velho else ZERO,
                       "margem_pct": pct, "margem_pct_anterior": pct_antes, "pontos": pontos(pct, pct_antes)})
    return {"de": de, "ate": ate, "de_anterior": de_anterior, "ate_anterior": ate_anterior, "agrupar": agrupar,
            "rotulo": "estimada", "inclui": INCLUI_MARGEM, "nao_inclui": NAO_INCLUI_MARGEM,
            "atual": a, "anterior": b,
            "variacao": {"receita": a["receita"] - b["receita"], "receita_pct": _variacao_pct(a["receita"], b["receita"]),
                         "margem": None if a["margem"] is None or b["margem"] is None else a["margem"] - b["margem"],
                         "pontos": pontos(a["margem_pct"], b["margem_pct"])},
            "grupos": grupos}


# ---------- margem estimada das apresentações (tabela de preço atual × custo atual) ----------

def margem_apresentacoes(*, ativas=True, produto_id=None, em=None) -> list[dict]:
    """Para cada apresentação: custo estimado = unidades × custo da ficha por unidade (ingredientes, mais óleo
    de referência se frita) + embalagens × última compra da embalagem; margem estimada no varejo e no atacado
    pelo preço de tabela atual. Sem referência de algum item, `completo=False`, custo e margens `None` e o que
    falta em `faltando`. `custo_un_ultimo_lote` é o custo real por unidade do lote mais recente do produto
    nessa forma (só informação; a margem usa a ficha)."""
    qs = Apresentacao.objects.select_related("produto", "embalagem").order_by("produto__nome", "unidades", "nome")
    if ativas:
        qs = qs.filter(ativo=True, produto__ativo=True)
    if produto_id:
        qs = qs.filter(produto_id=produto_id)
    fichas, saida = {}, []
    for a in qs:
        if a.produto_id not in fichas:
            try:
                fichas[a.produto_id] = custo_estimado(produto_id=a.produto_id, em=em)
            except RegraViolada as e:
                fichas[a.produto_id] = {"erro": str(e), "completo": False, "faltando": [], "ingredientes": None,
                                        "oleo": None}
        f = fichas[a.produto_id]
        faltando = list(f["faltando"])
        por_un = f["ingredientes"]
        if por_un is not None and a.forma == "frito":
            if f["oleo"] is None:
                por_un = None
                faltando.append({"item_id": a.produto_id, "item": a.produto.nome, "motivo": "sem óleo de referência"})
            else:
                por_un += f["oleo"]
        salgado = None if por_un is None else por_un * a.unidades
        embalagem = ZERO
        if a.embalagem_id and a.embalagens > 0:
            r = ultimo_custo(a.embalagem_id, ate=em)
            if r is None:
                embalagem = None
                faltando.append({"item_id": a.embalagem_id, "item": a.embalagem.nome, "motivo": "nunca comprado"})
            else:
                embalagem = a.embalagens * r["custo_unitario"]
        custo = None if salgado is None or embalagem is None else _rs(salgado + embalagem)
        ultimo = Lote.objects.filter(item_id=a.produto_id, forma=a.forma).order_by("-criado_em", "-id").first()

        def margem(preco):
            return None if preco is None or custo is None else preco - custo

        saida.append({
            "apresentacao_id": a.id, "produto_id": a.produto_id, "produto": a.produto.nome, "nome": a.nome,
            "descricao": str(a), "forma": a.forma, "estado": a.estado, "unidades": a.unidades,
            "preco_varejo": a.preco_varejo, "preco_atacado": a.preco_atacado,
            "custo_salgado": _rs(salgado), "custo_embalagem": _rs(embalagem), "custo": custo,
            "completo": custo is not None, "faltando": faltando, "erro": f.get("erro", ""),
            "margem_varejo": margem(a.preco_varejo), "margem_varejo_pct": _pct(margem(a.preco_varejo), a.preco_varejo),
            "margem_atacado": margem(a.preco_atacado),
            "margem_atacado_pct": _pct(margem(a.preco_atacado), a.preco_atacado),
            "custo_un_ultimo_lote": ultimo.custo_unitario if ultimo else None,
            "ultimo_lote_id": ultimo.id if ultimo else None,
            "rotulo": "estimada", "nao_inclui": ["indiretos", "perdas da produção", "tributos e despesas comerciais"]})
    return saida


# ---------- ranking e evolução de preço ----------

def ranking_produtos(*, de=None, ate=None, ordem="receita", limite=None) -> dict:
    """Produtos do período do maior para o menor em `ordem` ("receita", "unidades" ou "margem"), com a
    participação de cada um no total e a participação acumulada. Na ordem "margem", produto sem margem
    (custo duvidoso em todas as linhas) vai para o fim e não entra na participação."""
    if ordem not in ("receita", "unidades", "margem"):
        raise RegraViolada("Ordem desconhecida: use receita, unidades ou margem.")
    m = margens(de=de, ate=ate, agrupar="produto")
    grupos = m["grupos"]
    com = [g for g in grupos if g[ordem] is not None]
    sem = [g for g in grupos if g[ordem] is None]
    com.sort(key=lambda g: (-g[ordem], g["nome"]))
    total = sum((Decimal(g[ordem]) for g in com), ZERO)
    acumulado, lista = ZERO, []
    for g in com:
        acumulado += Decimal(g[ordem])
        lista.append({**g, "participacao_pct": _pct(Decimal(g[ordem]), total),
                      "acumulado_pct": _pct(acumulado, total)})
    lista += [{**g, "participacao_pct": None, "acumulado_pct": None} for g in sem]
    if limite:
        lista = lista[:limite]
    return {"de": de, "ate": ate, "ordem": ordem, "total": total, "produtos": lista, "totais": m["totais"],
            "rotulo": "estimada"}


def evolucao_preco(*, item_id, de=None, ate=None) -> dict:
    """Custo unitário (RN-20) de cada compra aprovada do item, por data e fornecedor (RF-REL-02), com a
    variação sobre a compra anterior e do primeiro ao último preço do período."""
    item = Item.objects.filter(id=item_id).first()
    if item is None:
        raise RegraViolada("Item não encontrado.")
    qs = (LinhaCompra.objects.select_related("compra__fornecedor").exclude(compra__status="cancelada")
          .filter(item_id=item_id).order_by("compra__data", "compra_id", "id"))
    if de:
        qs = qs.filter(compra__data__gte=de)
    if ate:
        qs = qs.filter(compra__data__lte=ate)
    compras, anterior = [], None
    for l in qs:
        compras.append({"compra_id": l.compra_id, "data": l.compra.data, "fornecedor": l.compra.fornecedor.nome,
                        "quantidade_base": l.quantidade_base, "valor": l.valor, "custo_unitario": l.custo_unitario,
                        "variacao_pct": _variacao_pct(l.custo_unitario, anterior)})
        anterior = l.custo_unitario
    primeiro = compras[0]["custo_unitario"] if compras else None
    ultimo = compras[-1]["custo_unitario"] if compras else None
    return {"item_id": item.id, "item": item.nome, "unidade_base": item.unidade_base, "de": de, "ate": ate,
            "compras": compras, "primeiro": primeiro, "ultimo": ultimo,
            "variacao_pct": _variacao_pct(ultimo, primeiro)}
