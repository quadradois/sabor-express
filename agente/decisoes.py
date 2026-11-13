"""Caixa de decisões, resumo do dia, histórico e backup pelo agente de voz (Plano 4, fase 2b).

O agente só fala quando alguém fala com ele: lê a caixa quando perguntado ("o que tem para decidir?",
"como está o dia?", "o que foi feito hoje?"). Tudo devolve um `texto` curto para falar: com muitos itens,
os totais, os três mais urgentes e quantos faltam. As decisões são ditas pelo número ("número 12"), para o
dono poder responder "aprova a doze".

Alçada (plano 4, contrato da fase 2): ler é nível 0; dar ciência num aviso e recusar uma decisão (com
motivo) são nível 1; aprovar uma decisão que executa operação é nível 2 — vira `agente.Proposta`, simulada
pelo núcleo, e só grava com `confirmar_proposta`. Nenhuma regra aqui: os números vêm de
`decisoes.consultas` e `backup.situacao`, e as gravações são os serviços de `decisoes.servicos`.
"""

import re
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from backup.situacao import situacao_backup
from decisoes import consultas as dc
from decisoes.servicos import aprovar_decisao as _aprovar
from decisoes.servicos import recusar_decisao as _recusar

from .acoes import _feito, _proposta, _uma_vez
from .compras import _juntar, _n, dia_falado, mes_falado, quando, reais, sem_mes_numerico
from .consultas import ConsultaInvalida, _casa, _inteiro, _normal

MAX_FALADOS = 3  # itens lidos no `texto`; o resto vira "e mais N"

# origem da decisão em português falado, com palavras que o dono pode usar para filtrar
ORIGENS = {
    "lotes_vencidos": ("produto vencido", "vencido validade"),
    "encomenda_sem_estoque": ("encomenda sem estoque", "encomendas reserva reservar produzir falta"),
    "contas_vencidas": ("conta vencida", "contas vencida pagar"),
    "despesas_sem_valor": ("despesa sem valor", "despesa despesas sem valor mensal luz energia internet gas"),
    "receber_vencidas": ("cliente devendo", "receber recebimento fiado devendo cliente"),
    "lotes_vencendo": ("validade perto de vencer", "vencendo vence validade"),
    "sobras_fritas": ("sobra de frito", "sobras frito fritos fritura"),
    "consumo_pendente": ("consumo pendente", "conciliar conciliacao"),
    "contas_a_vencer": ("conta a vencer", "contas vencer pagar"),
    "estoque_baixo": ("estoque baixo", "minimo falta acabando"),
    "recebimento_atrasado": ("compra atrasada", "recebimento entrega chegou compras"),
    "avisos_ajuste": ("aviso de ajuste", "ajuste fornecedor nota"),
    "ficha_rendimento": ("sugestão de ficha", "ficha rendimento receita"),
}
_URGENCIA = list(ORIGENS)  # a ordem acima é a da urgência

_CANAIS = {"voz": "agente", "agente": "agente", "telefone": "agente", "tela": "web", "web": "web", "site": "web",
           "computador": "web", "sistema": "sistema", "rotina": "sistema", "automatico": "sistema"}


# --- fala -------------------------------------------------------------------------

def _hora(dt) -> str:
    dt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
    return f"{dt.hour}h{dt.minute:02d}"


def _dia_local(dt) -> date:
    return timezone.localtime(dt).date() if timezone.is_aware(dt) else dt.date()


def _quem(autor) -> str:
    return {"agente-mcp": "pelo agente", "rotina": "pela rotina"}.get(autor, f"por {autor}")


def _sem_ponto(t) -> str:
    return (t or "").strip().rstrip(".?!;:")


def _e_mais(frases, n=MAX_FALADOS, resto="mais") -> str:
    frases = list(frases)
    sobra = len(frases) - n
    return " ".join(frases[:n]) + (f" E {resto} {sobra}." if sobra > 0 else "")


def _erro_limpo(erro) -> str:
    """O erro da trilha vem como "[chave=...] mensagem"; a voz só fala a mensagem."""
    erro = erro or ""
    return erro.split("] ", 1)[1] if erro.startswith("[chave=") and "] " in erro else erro


_DATA = re.compile(r"\b(em |de |para |desde )?(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b")
_DATA_ENTRE_PARENTESES = re.compile(r" \(\d{1,2}/\d{1,2}(?:/\d{4})?\)")
_DINHEIRO = re.compile(r"-?R\$ ?(\d{1,3}(?:\.\d{3})*,\d{2})")
_UN = re.compile(r"\b(\d+(?:,\d+)?) un\b")


def _data_falada(m) -> str:
    prefixo, dia, mes, ano = m.group(1) or "", int(m.group(2)), int(m.group(3)), m.group(4)
    hoje = timezone.localdate()
    try:
        if ano:
            d = date(int(ano), mes, dia)
        else:  # sem ano: o mais perto de hoje (a caixa fala de dias próximos)
            d = min((date(hoje.year + k, mes, dia) for k in (-1, 0, 1)), key=lambda x: abs((x - hoje).days))
    except ValueError:
        return m.group(0)
    q = quando(d)
    nucleo = q[3:] if q.startswith("em ") else q
    if prefixo == "em ":
        return q
    return prefixo + nucleo


def falavel(texto) -> str:
    """O texto das decisões com datas e dinheiro como se fala ("venceu ontem", "100 reais", "30 unidades").

    Os geradores do núcleo escrevem "15/11" e "R$ 100,00" (pendência do Plano 4); a voz não lê isso bem."""
    t = _DATA_ENTRE_PARENTESES.sub("", texto or "")
    t = _DATA.sub(_data_falada, t)
    t = sem_mes_numerico(t)  # "Energia — 11/2026" → "Energia de novembro" (despesas, Plano 8)
    t = t.replace(", parcela 1 de 1,", ",")
    t = _DINHEIRO.sub(lambda m: reais(Decimal(m.group(1).replace(".", "").replace(",", "."))), t)
    t = _UN.sub(lambda m: m.group(1) + (" unidade" if m.group(1) == "1" else " unidades"), t)
    return t.replace(" (lote sem lote)", "").replace("lote sem lote", "lote sem código")


def _numero(d) -> str:
    return f"Número {d['decisao_id']}"


def _item_caixa(d) -> str:
    tipo = "para aprovar" if d["tipo"] == "decisao" else "aviso"
    t = f"{_numero(d)}, {tipo}: {_sem_ponto(falavel(d['texto']))}."
    if d.get("ultimo_erro"):
        t += f" Da última vez não deu para aprovar: {_sem_ponto(_erro_limpo(d['ultimo_erro']['erro']))}."
    return t


def _urgentes(itens) -> list[dict]:
    """Decisões (com operação) antes dos avisos; depois pela urgência da origem; empate, a ordem da caixa."""
    def peso(d):
        o = d["origem"]
        return (d["tipo"] != "decisao", _URGENCIA.index(o) if o in _URGENCIA else len(_URGENCIA))
    return sorted(itens, key=peso)


def _curta(d) -> dict:
    return {"decisao_id": d["decisao_id"], "tipo": d["tipo"], "origem": d["origem"],
            "origem_texto": ORIGENS.get(d["origem"], (d["origem"].replace("_", " "),))[0],
            "texto": falavel(d["texto"]),
            "criada_em": d["criada_em"].isoformat(timespec="seconds"),
            "ultimo_erro": _erro_limpo(d["ultimo_erro"]["erro"]) if d["ultimo_erro"] else None}


def _caixa_txt(decisoes, avisos) -> str:
    if not decisoes and not avisos:
        return "A caixa de decisões está vazia."
    partes = []
    if decisoes:
        partes.append(_n(decisoes, "decisão para aprovar", "decisões para aprovar"))
    if avisos:
        partes.append(_n(avisos, "aviso"))
    return f"Na caixa, {_juntar(partes)}."


# --- resolução do que foi dito ---------------------------------------------------------

def _origens(busca) -> set[str]:
    if not (busca or "").strip():
        return set()
    b = _normal(busca).replace("_", " ")
    achadas = {o for o, (rotulo, extra) in ORIGENS.items()
               if _normal(o).replace("_", " ") == b or _casa(busca, f"{o.replace('_', ' ')} {rotulo} {extra}")}
    if not achadas:
        raise ConsultaInvalida(f"Não conheço o assunto '{busca}' na caixa.", 400,
                               opcoes=[r for r, _ in ORIGENS.values()])
    return achadas


def _tipo(tipo) -> str | None:
    t = _normal(tipo or "")
    if not t or t in ("todos", "todas", "tudo"):
        return None
    if t.startswith("decis") or t.startswith("aprova"):
        return "decisao"
    if t.startswith("aviso"):
        return "aviso"
    raise ConsultaInvalida("'tipo' é decisao, aviso ou vazio (todos).")


def _decisao(decisao_id) -> dict:
    n = _inteiro(decisao_id, "decisao_id")
    d = dc.detalhe_decisao(n)
    if d is None:
        raise ConsultaInvalida(f"Não achei a decisão número {n}.", 404)
    return d


def _ja_decidida(d) -> str:
    """Frase para uma decisão que não está mais pendente (vale para aprovar, recusar e dar ciência)."""
    s, quem = d["situacao"], d["decidida_por"]
    if s == "aprovada":
        return (f"O número {d['decisao_id']} já está "
                + ("com ciência dada" if d["tipo"] == "aviso" else "aprovado") + f" {_quem(quem)}; não faço de novo.")
    if s == "recusada":
        return f"O número {d['decisao_id']} já foi recusado {_quem(quem)} ({_sem_ponto(d['motivo'])})."
    return (f"O número {d['decisao_id']} não vale mais: a situação mudou ou o prazo passou. "
            "Se ainda fizer sentido, a rotina põe de novo na caixa.")


# --- leitura (nível 0) -------------------------------------------------------------

def _assuntos(r, backup) -> list[dict]:
    """O que o resumo do dia tem a dizer, do mais urgente ao menos, cada um numa frase."""
    t, a = r["totais"], []

    def add(chave, rotulo, texto):
        a.append({"assunto": chave, "rotulo": rotulo, "texto": texto})

    venc = r["validade"]["vencidos"]
    if venc:
        nomes = _juntar(sorted({p["item"] for p in venc}))
        add("vencidos", "produto vencido",
            f"Atenção: {_n(len(venc), 'lote vencido', 'lotes vencidos')} em estoque, "
            f"{reais(r['validade']['valor_vencido'])} em mercadoria: {nomes}. Vencido não pode ser usado.")
    if backup:
        add("backup", "backup", backup)
    enc = r.get("encomendas") or {}
    if enc.get("atrasadas"):
        atrasadas = enc["atrasadas"]
        add("encomendas_atrasadas", "encomenda atrasada",
            f"{_n(len(atrasadas), 'encomenda atrasada', 'encomendas atrasadas')}, com o dia já passado e sem "
            f"entrega: {_juntar([f'a {e['encomenda_id']} de {e['cliente']}' for e in atrasadas[:MAX_FALADOS]])}.")
    if enc.get("hoje"):
        de_hoje = enc["hoje"]
        prontas = sum(e["situacao"] == "pronta" for e in de_hoje)
        faltando = len(de_hoje) - prontas
        partes = ([_n(prontas, "pronta", "prontas")] if prontas else []) + \
            ([f"{faltando} faltando reservar"] if faltando else [])
        add("encomendas_hoje", "encomendas de hoje",
            f"{_n(len(de_hoje), 'encomenda')} para hoje: {_juntar(partes)}.")
    if t["contas_vencidas"]:
        add("contas_vencidas", "conta vencida",
            f"{_n(t['contas_vencidas'], 'conta vencida', 'contas vencidas')}, somando "
            f"{reais(t['valor_contas_vencidas'])}.")
    despesas = r.get("despesas") or {}
    if despesas.get("sem_valor_vencidas"):
        sem = despesas["sem_valor_vencidas"]
        add("despesas_sem_valor_vencidas", "despesa vencida sem valor",
            f"{_n(len(sem), 'despesa do mês venceu', 'despesas do mês venceram')} sem valor nem pagamento anotado: "
            + _juntar([f"{d['despesa']} de {mes_falado(d['competencia'])}, {dia_falado(d['vencimento'])}"
                       for d in sem[:MAX_FALADOS]]) + ". Se já pagou, diga quanto foi.")
    if t.get("receber_vencidas"):
        add("receber_vencidas", "cliente devendo",
            f"{_n(t['receber_vencidas'], 'conta a receber vencida', 'contas a receber vencidas')} de clientes, "
            f"somando {reais(t['valor_receber_vencidas'])}.")
    vencendo = r["validade"]["vencendo"]
    if vencendo:
        nomes = _juntar(sorted({p["item"] for p in vencendo}))
        verbo = "vence" if len(vencendo) == 1 else "vencem"
        add("vencendo", "validade perto de vencer",
            f"{_n(len(vencendo), 'lote')} {verbo} até daqui a {_n(r['validade']['dias'], 'dia')}: {nomes}.")
    a_produzir = [x for x in enc.get("necessidade") or [] if x["a_produzir"] > 0]
    if a_produzir:
        from .vendas import _un

        add("falta_produzir", "falta produzir para encomendas",
            f"Para as encomendas dos próximos {_n(enc['dias'], 'dia')}, falta produzir "
            + _juntar([f"{_un(x['a_produzir'])} de {x['produto']} {x['forma']} {x['estado']}"
                       for x in a_produzir[:MAX_FALADOS]]) + ".")
    if t["itens_abaixo_do_minimo"]:
        baixo = r["estoque_baixo"]
        nomes = _juntar([i["item"] for i in baixo[:MAX_FALADOS]]
                        + ([f"mais {len(baixo) - MAX_FALADOS}"] if len(baixo) > MAX_FALADOS else []))
        add("estoque_baixo", "estoque baixo",
            f"{_n(len(baixo), 'item abaixo', 'itens abaixo')} do mínimo: {nomes}.")
    if t["contas_a_vencer"]:
        verbo = "vence" if t["contas_a_vencer"] == 1 else "vencem"
        add("contas_a_vencer", "contas a vencer",
            f"{_n(t['contas_a_vencer'], 'conta')} {verbo} nos próximos {r['contas']['dias']} dias, somando "
            f"{reais(t['valor_contas_a_vencer'])}.")
    a_vencer_sem = [d for d in despesas.get("sem_valor") or [] if not d["vencida"]]
    if a_vencer_sem:
        verbo = "vence" if len(a_vencer_sem) == 1 else "vencem"
        add("despesas_sem_valor", "despesa sem valor",
            f"{_n(len(a_vencer_sem), 'despesa do mês', 'despesas do mês')} {verbo} logo e ainda sem valor: "
            + _juntar([f"{d['despesa']}, {dia_falado(d['vencimento'])}" for d in a_vencer_sem[:MAX_FALADOS]])
            + ". Quando a conta chegar, é só dizer o valor.")
    if r.get("sobras_fritas"):
        from .vendas import _un

        sobras = r["sobras_fritas"]
        nomes = _juntar(sorted({x["item"] for x in sobras}))
        add("sobras_fritas", "sobra de frito",
            f"Sobra de frito no estoque: {_un(sum(x['saldo'] for x in sobras))} de {nomes}.")
    if t["compras_atrasadas"]:
        add("compras_atrasadas", "compra atrasada",
            f"{_n(t['compras_atrasadas'], 'compra atrasada', 'compras atrasadas')}: sete dias ou mais sem chegar tudo.")
    if t["consumos_pendentes"]:
        add("consumos_pendentes", "consumo pendente",
            f"{_n(t['consumos_pendentes'], 'consumo pendente', 'consumos pendentes')} de conciliar.")
    if t["producoes_custo_pendente"]:
        add("custo_pendente", "custo pendente",
            f"{_n(t['producoes_custo_pendente'], 'produção', 'produções')} com custo pendente.")
    if t["avisos_de_ajuste"]:
        add("avisos_de_ajuste", "aviso de ajuste",
            f"{_n(t['avisos_de_ajuste'], 'aviso')} de ajuste em aberto nas contas.")
    if t["producoes_em_andamento"]:
        nomes = _juntar([f"{p['unidades']} {p['produto']}" for p in r["producoes"]["em_andamento"][:MAX_FALADOS]])
        add("producoes", "produção em andamento",
            f"{_n(t['producoes_em_andamento'], 'produção', 'produções')} em andamento: {nomes}.")
    a_chegar = t["compras_a_chegar"] - t["compras_atrasadas"]
    if a_chegar > 0:
        add("a_chegar", "compras a chegar", f"{_n(a_chegar, 'compra')} esperando entrega.")
    proximas = [e for e in enc.get("proximas") or [] if e["dias"] > 0]
    if proximas:
        add("encomendas_proximas", "encomendas dos próximos dias",
            f"{_n(len(proximas), 'encomenda')} para os próximos {_n(enc['dias'], 'dia')}.")
    if t.get("vendas_hoje"):
        add("vendas", "vendas de hoje",
            f"Hoje, {_n(t['vendas_hoje'], 'venda')}, somando {reais(t['valor_vendas_hoje'])}.")
    return a


def _backup_alerta() -> str:
    """Só o que pede atenção: backup atrasado ou ausente (RF-ADM-06). Em dia, o resumo não fala dele."""
    try:
        s = situacao_backup()
    except OSError:
        return "Não consegui ver a situação do backup; peça para conferirem o computador da cozinha."
    if not s["existe"]:
        return "Atenção: não há nenhum backup do sistema."
    if s["atrasado"]:
        return f"Atenção: o backup está atrasado; o último foi {quando(s['ultimo_em'].date())}."
    return ""


def ver_resumo_do_dia():
    r = dc.resumo_do_dia()
    t = r["totais"]
    assuntos = _assuntos(r, _backup_alerta())
    caixa = _caixa_txt(t["decisoes_pendentes"], t["avisos_pendentes"])
    if not assuntos:
        texto = ("Dia tranquilo: nada vencido nem para vencer, nada abaixo do mínimo, nenhuma conta para pagar "
                 "na semana e nenhuma produção em andamento. " + caixa)
    else:
        texto = caixa + " " + " ".join(x["texto"] for x in assuntos[:MAX_FALADOS])
        resto = assuntos[MAX_FALADOS:]
        if resto:
            texto += (f" Tem mais {_n(len(resto), 'assunto')}: {_juntar([x['rotulo'] for x in resto])}. "
                      "Quer que eu fale?")
    # o núcleo já conta sem a rotina automática (Plano 7): só o que pessoas e o agente fizeram
    feitas = t["operacoes_hoje"]
    if feitas:
        texto += f" Hoje já foram feitas {_n(feitas, 'operação', 'operações')} no sistema."
    return {"hoje": r["hoje"].isoformat(), "texto": texto, "assuntos": assuntos,
            "totais": {k: (float(v) if not isinstance(v, int) else v) for k, v in t.items()}}


def ver_decisoes(tipo="", origem=""):
    origens, tipo = _origens(origem), _tipo(tipo)
    itens = dc.decisoes(tipo=tipo)
    if origens:
        itens = [d for d in itens if d["origem"] in origens]
    itens = _urgentes(itens)
    n_dec = sum(d["tipo"] == "decisao" for d in itens)
    if not itens:
        sobre = f" sobre {_juntar(sorted(ORIGENS[o][0] for o in origens))}" if origens else ""
        if tipo == "decisao":
            texto = f"Nenhuma decisão para aprovar{sobre} na caixa."
        elif tipo == "aviso":
            texto = f"Nenhum aviso{sobre} na caixa."
        elif origens:
            texto = f"Nada{sobre} na caixa."
        else:
            texto = "A caixa de decisões está vazia: nada esperando você."
    else:
        texto = _caixa_txt(n_dec, len(itens) - n_dec) + " " + _e_mais((_item_caixa(d) for d in itens),
                                                                      resto="tem mais")
    return {"total": len(itens), "decisoes": n_dec, "avisos": len(itens) - n_dec,
            "itens": [_curta(d) for d in itens], "texto": texto}


def ver_decisao(decisao_id):
    d = _decisao(decisao_id)
    origem = ORIGENS.get(d["origem"], (d["origem"].replace("_", " "),))[0]
    tipo = "decisão para aprovar" if d["tipo"] == "decisao" else "aviso"
    t = f"{_numero(d)}, {tipo}, {origem}: {_sem_ponto(falavel(d['texto']))}."
    s = d["situacao"]
    if s == "pendente":
        t += f" Está na caixa desde {quando(_dia_local(d['criada_em']))}."
        if d["ultimo_erro"]:
            t += f" Da última vez não deu para aprovar: {_sem_ponto(_erro_limpo(d['ultimo_erro']['erro']))}."
    elif s == "aprovada":
        feito = "Ciência dada" if d["tipo"] == "aviso" else "Aprovada"
        t += f" {feito} {_quem(d['decidida_por'])} {quando(_dia_local(d['decidida_em']))} às {_hora(d['decidida_em'])}."
    elif s == "recusada":
        t += (f" Recusada {_quem(d['decidida_por'])} {quando(_dia_local(d['decidida_em']))}: "
              f"{_sem_ponto(d['motivo'])}.")
    else:
        t += " Não vale mais: " + ("o prazo passou." if s == "expirada" else "a situação deixou de existir.")
    return {**_curta(d), "situacao": s, "detalhes": d["detalhes"], "motivo": d["motivo"],
            "decidida_por": d["decidida_por"], "texto_decisao": d["texto"], "texto": t}


def _periodo(periodo) -> tuple[date, date, str]:
    hoje = timezone.localdate()
    p = _normal(periodo or "hoje")
    if p in ("hoje", "dia"):
        return hoje, hoje, "hoje"
    if p == "ontem":
        return hoje - timedelta(days=1), hoje - timedelta(days=1), "ontem"
    if "semana" in p or p in ("7 dias", "sete dias"):
        return hoje - timedelta(days=6), hoje, "nos últimos 7 dias"
    if p.startswith("mes"):
        return hoje - timedelta(days=29), hoje, "nos últimos 30 dias"
    try:
        d = date.fromisoformat(p)
    except ValueError:
        raise ConsultaInvalida("'periodo' é hoje, ontem, semana, mes ou uma data AAAA-MM-DD.") from None
    return d, d, quando(d)


def ver_historico(periodo="hoje", autor="", canal="", operacao="", so_erros=False):
    de, ate, quando_txt = _periodo(periodo)
    c = _CANAIS.get(_normal(canal), _normal(canal)) if canal else ""
    linhas = dc.historico_operacoes(de=de, ate=ate, canal=c, status="erro" if so_erros else "sucesso", limite=None)
    if not c:
        linhas = [h for h in linhas if h["canal"] != "sistema"]  # a rotina automática só com canal="sistema"
    if autor:
        linhas = [h for h in linhas if _casa(autor, h["autor"])]
    if operacao:
        nomes = {n for n, r in dc.ROTULOS.items() if _casa(operacao, r) or _casa(operacao, n.replace("_", " "))}
        if not nomes:
            raise ConsultaInvalida(f"Não conheço a operação '{operacao}'. Diga com outras palavras, "
                                   "como compra, pagamento, produção ou peso.")
        linhas = [h for h in linhas if h["nome"] in nomes]
    filtros = "".join([f" de {operacao}" if operacao else "", f" {_quem(autor)}" if autor else "",
                       f" pelo canal {canal}" if canal else ""])
    oque = "tentativa recusada" if so_erros else "operação"
    um_dia = de == ate

    def frase(h):
        dia = "" if um_dia else f" {quando(_dia_local(h['criado_em']))}"
        t = f"{h['rotulo']}{dia} às {_hora(h['criado_em'])}, {_quem(h['autor'])}"
        return t + (f" ({_sem_ponto(_erro_limpo(h['erro']))})" if so_erros and h["erro"] else "") + "."

    if not linhas:
        texto = f"{quando_txt.capitalize()}, nenhuma {oque}{filtros}."
    else:
        plural = {"operação": "operações", "tentativa recusada": "tentativas recusadas"}[oque]
        texto = (f"{quando_txt.capitalize()}, {_n(len(linhas), oque, plural)}{filtros}. "
                 + ("As mais recentes: " if len(linhas) > MAX_FALADOS else "")
                 + _e_mais((frase(h) for h in linhas), resto="mais"))
    por_tipo = {}
    for h in linhas:
        por_tipo[h["rotulo"]] = por_tipo.get(h["rotulo"], 0) + 1
    return {"de": de.isoformat(), "ate": ate.isoformat(), "total": len(linhas),
            "por_tipo": dict(sorted(por_tipo.items(), key=lambda x: -x[1])),
            "operacoes": [{"operacao_id": h["operacao_id"], "rotulo": h["rotulo"], "nome": h["nome"],
                           "quando": timezone.localtime(h["criado_em"]).isoformat(timespec="seconds"),
                           "autor": h["autor"], "canal": h["canal"],
                           **({"erro": _erro_limpo(h["erro"])} if h["status"] == "erro" else {})}
                          for h in linhas[:20]],
            "texto": texto}


def ver_backup():
    s = situacao_backup()
    if not s["existe"]:
        texto = "Atenção: não encontrei nenhum backup do sistema. Avise quem cuida do computador da cozinha."
    else:
        d = s["ultimo_em"]
        horas = s["horas_desde_ultimo"]
        ha = _n(int(horas // 24), "dia") if horas >= 48 else _n(int(horas), "hora")
        foi = f"o último backup foi {quando(d.date())} às {_hora(d)}"
        guardados = f"Há {_n(s['quantidade'], 'backup guardado', 'backups guardados')}."
        texto = (f"Atenção: o backup está atrasado; {foi}, há {ha}. {guardados} Avise quem cuida do computador "
                 "da cozinha." if s["atrasado"] else f"Backup em dia: {foi}. {guardados}")
        texto = texto[0].upper() + texto[1:]
    return {"existe": s["existe"], "atrasado": s["atrasado"], "quantidade": s["quantidade"],
            "ultimo_em": s["ultimo_em"].isoformat(timespec="seconds") if s["ultimo_em"] else None,
            "horas_desde_ultimo": s["horas_desde_ultimo"],
            "tamanho_mb": round(s["ultimo_tamanho_bytes"] / 1_000_000, 1) if s["ultimo_tamanho_bytes"] else None,
            "texto": texto}


# --- nível 1: ciência e recusa -----------------------------------------------------

def dar_ciencia(*, decisao_id, autor, canal):
    d = _decisao(decisao_id)

    def fazer(chave):
        if d["tipo"] != "aviso":
            raise ConsultaInvalida(f"O número {d['decisao_id']} não é aviso: é uma decisão que precisa de "
                                   "aprovação (aprovar_decisao) ou de recusa com motivo.", 409)
        if d["situacao"] != "pendente":
            raise ConsultaInvalida(_ja_decidida(d), 409)
        return _aprovar(decisao_id=d["decisao_id"], autor=autor, canal=canal, chave=chave)

    r, rep = _uma_vez("dar_ciencia", {"decisao": d["decisao_id"]}, fazer)
    return _feito(f"Ciente do número {d['decisao_id']}: {_sem_ponto(falavel(d['texto']))}. Saiu da caixa.", r, rep,
                  decisao_id=d["decisao_id"])


def recusar_decisao(*, decisao_id, motivo, autor, canal):
    d, motivo = _decisao(decisao_id), (motivo or "").strip()

    def fazer(chave):
        if d["tipo"] == "aviso":
            raise ConsultaInvalida(f"O número {d['decisao_id']} é um aviso: aviso não se recusa, só se dá ciência "
                                   "(dar_ciencia).", 409)
        if d["situacao"] != "pendente":
            raise ConsultaInvalida(_ja_decidida(d), 409)
        if not motivo:
            raise ConsultaInvalida("Para recusar, preciso do motivo: pergunte por quê (uma frase curta basta).")
        return _recusar(decisao_id=d["decisao_id"], motivo=motivo, autor=autor, canal=canal, chave=chave)

    r, rep = _uma_vez("recusar_decisao", {"decisao": d["decisao_id"], "motivo": motivo}, fazer)
    return _feito(f"Recusei o número {d['decisao_id']} ({_sem_ponto(falavel(d['texto']))}). Motivo: {_sem_ponto(motivo)}.",
                  r, rep, decisao_id=d["decisao_id"])


# --- nível 2: aprovar ---------------------------------------------------------------

def _efeito(r) -> str:
    """O que a operação simulada fez, nos números do núcleo."""
    res = r.get("resultado") or {}
    if r.get("operacao") == "conciliar_consumo":
        t = f"Baixa do lote e custo de {reais(res['custo'])}"
        if res.get("producao_id") and not res.get("custo_pendente"):
            t += f"; o custo da produção {res['producao_id']} fica fechado"
        return t
    if r.get("operacao") == "completar_reserva":
        from .vendas import _un

        t = f"Vou reservar para a encomenda {res['encomenda_id']} o que houver no estoque"
        falta = Decimal(str(res.get("falta") or 0))
        t += f"; ainda vai faltar {_un(falta)}" if falta > 0 else "; ela fica pronta, com tudo reservado"
        if res.get("reservas_liberadas"):
            t += ", trocando a reserva do lote que venceria antes da entrega"
        return t
    return ""


def propor_aprovar_decisao(*, decisao_id, autor, canal):
    d = _decisao(decisao_id)
    if d["tipo"] == "aviso":
        raise ConsultaInvalida(f"O número {d['decisao_id']} é um aviso, não tem o que aprovar: "
                               "se o dono viu, dê ciência (dar_ciencia).", 409)
    if d["situacao"] != "pendente":
        raise ConsultaInvalida(_ja_decidida(d), 409)

    def resumir(r):
        efeito = _efeito(r)
        return (f"Aprovar o número {d['decisao_id']}: {_sem_ponto(falavel(d['texto']))}"
                + (f". {efeito}" if efeito else ""))

    return {**_proposta("aprovar_decisao", {"decisao_id": d["decisao_id"]}, resumir, autor, canal),
            "decisao_id": d["decisao_id"]}
