"""Vendas, encomendas, fritura, perda e contas a receber pelo agente de voz (Plano 6, fase 2b).

Mesmo padrão de `compras.py`: tudo chega pelo nome falado — produto e apresentação ("duas caixas de
coxinha congelada"), cliente, conservação — e é resolvido aqui, ignorando acento, caixa e plural;
ambíguo vira `ConsultaInvalida` com `opcoes`. Consultas devolvem os dados enxutos e um `texto` pronto
para falar, com totais já somados pelo sistema, dinheiro por extenso e datas faladas.

Alçada (plano 6, "Perguntas em aberto" e pedido do dono): ler é nível 0; cadastrar cliente e completar a
reserva de uma encomenda são nível 1; venda, encomenda, entrega, cancelamentos, fritura, perda e
recebimento de cliente são nível 2 (proposta simulada pelo núcleo, só grava com `confirmar_proposta`).
Preço não muda por voz (Q10): a venda usa sempre o preço da tabela. Nenhuma regra de negócio aqui:
preços, totais, reservas, custos e recusas vêm de `vendas`, `producao.fritura`, `estoque` e `financeiro`.
"""

import re
from difflib import SequenceMatcher
from datetime import date, time, timedelta
from decimal import Decimal

from django.utils import timezone

from cadastros.models import Cliente, Item
from cadastros.servicos import salvar_cliente
from estoque.models import Lote
from estoque.servicos import porcoes
from financeiro import consultas as fc
from financeiro.servicos import dividir_parcelas
from vendas import consultas as vc
from vendas.models import Apresentacao
from vendas.servicos import completar_reserva as _completar

from .acoes import _data, _decimal, _estado, _feito, _forma, _proposta, _uma_vez
from .lotes import (checar_motivo_na_separacao, lotes_da_apresentacao, lotes_indicados, nome, pedir_motivo, porcao_vencida, resolver_lote,
                    separacao_curta, separacao_resposta, vencidos_da_separacao, vencidos_txt)
from .compras import (_ate_cinco, _condicao, _dicts, _dinheiro, _juntar, _n, _parcela_txt, _sem_valor, _unidade,
                      qtd, quando, reais)
from .consultas import ConsultaInvalida, _casa, _inteiro, _normal, escolher, resolver_produto
from .decisoes import _periodo

ZERO = Decimal("0")
MAX_OPCOES = 8

# palavras que não ajudam a achar a apresentação ("duas caixas DE coxinha COM 25")
_VAZIAS = {"de", "da", "do", "das", "dos", "com", "a", "o", "as", "os", "e", "pra", "pro", "para", "em", "um", "uma",
           "uns", "umas", "no", "na"}
_SINONIMOS = {"fresc": "fresco", "resfri": "resfriado", "gelad": "resfriado", "congel": "congelado",
              "freez": "congelado", "frit": "frito"}  # por começo de palavra ("congeladas", "geladeira")
_IGUAIS = {"crua": "cru", "cru": "cru", "grama": "g", "gr": "g", "quilo": "kg"}  # palavra inteira
_DIAS_SEMANA = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")


# --- fala ---------------------------------------------------------------------------

def _num(q) -> str:
    q = Decimal(str(q))
    return f"{int(q)}" if q == q.to_integral() else f"{q.normalize():f}".replace(".", ",")


def _un(q) -> str:
    """"1 unidade", "30 unidades" (salgado é contado em unidades)."""
    return f"{_num(q)} {'unidade' if Decimal(str(q)) == 1 else 'unidades'}"


def _plural(nome, q) -> str:
    """"caixa com 25" → "caixas com 25", "unidade frita" → "unidades fritas" quando são várias."""
    if q == 1:
        return nome
    palavras, plural = nome.split(), True
    for i, w in enumerate(palavras):
        if _normal(w) in _VAZIAS or any(c.isdigit() for c in w):
            plural = False  # depois de "com", "de" ou de um número, nada muda
        if plural and not w.endswith("s"):
            palavras[i] = w + ("es" if w[-1:] in "rz" else "s")
    return " ".join(palavras)


def _jeito(forma, estado) -> str:
    return f"{forma} {estado}"


def _apres_txt(a, q=None) -> str:
    """"2 caixas com 25 de Coxinha 150 g, cru congelado"."""
    nome = a.nome if q is None else f"{q} {_plural(a.nome, q)}"
    return f"{nome} de {a.produto.nome}, {_jeito(a.forma, a.estado)}"


def _sem_em(t) -> str:
    return t[3:] if t.startswith("em ") else t


def _para(d) -> str:
    """"para amanhã", "para 21 de novembro"."""
    return f"para {_sem_em(quando(d))}"


def _hora_txt(h) -> str:
    if not h:
        return ""
    h = h if isinstance(h, time) else time.fromisoformat(str(h))
    return f" às {h.hour}h" + (f"{h.minute:02d}" if h.minute else "")


def _iso(v):
    return v.isoformat() if v else None


# --- entradas faladas ------------------------------------------------------------------

def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("eis"):
        return w[:-3] + "el"  # pastéis → pastel
    if len(w) > 3 and w.endswith("oes"):
        return w[:-3] + "ao"
    if len(w) > 3 and w.endswith("s"):
        return w[:-1]
    return w


def _tokens(texto) -> list[str]:
    saida = []
    for w in re.split(r"[\s,;()—\-]+", _normal(texto or "")):
        if not w or w in _VAZIAS:
            continue
        w = _singular(w)
        w = _IGUAIS.get(w) or next((c for p, c in _SINONIMOS.items() if w.startswith(p)), w)
        saida.append(w)
    return saida


def _cobre(ditos, tokens_alvo) -> bool:
    """Cada palavra dita bate (inteira ou como começo) com alguma palavra do alvo."""
    return all(any(t == d or t.startswith(d) for t in tokens_alvo) for d in ditos)


def _perto(dito, alvo) -> bool:
    return alvo == dito or alvo.startswith(dito) or SequenceMatcher(None, dito, alvo).ratio() >= 0.75


def _rotulo_apres(a) -> str:
    return f"{a.produto.nome} {a.nome} {a.forma} {a.estado}"


def _apresentacao(pedido: dict) -> Apresentacao:
    """A apresentação de um item falado: {produto, apresentacao?, forma?, conservacao?}."""
    dito = " ".join(str(pedido.get(k) or "") for k in ("produto", "apresentacao", "forma", "conservacao"))
    ditos = _tokens(dito)
    if not ditos:
        raise ConsultaInvalida("Diga o produto de cada item (ex.: coxinha, caixa com 25, congelada).")
    ativas = list(Apresentacao.objects.select_related("produto")
                  .filter(ativo=True, produto__ativo=True).order_by("produto__nome", "unidades", "nome"))
    achadas = [a for a in ativas if _cobre(ditos, _tokens(_rotulo_apres(a)))]
    if len(achadas) > 1:  # o nome da apresentação todo dito ganha das parciais ("caixa com 25" × "caixa com 50")
        inteiras = [a for a in achadas if set(_tokens(a.nome)) <= set(ditos)]
        achadas = inteiras or achadas
    if len(achadas) > 1:
        exatas = [a for a in achadas if set(_tokens(_rotulo_apres(a))) <= set(ditos)]
        achadas = exatas or achadas
    if len(achadas) == 1:
        return achadas[0]
    if not achadas:
        # nome ouvido torto ("previl" por "preview") ou forma/conservação que não existe: mostra o que há, não desiste
        prod = _tokens(pedido.get("produto"))
        proximas = [a for a in ativas if prod and all(any(_perto(d, x) for x in _tokens(a.produto.nome)) for d in prod)]
        if proximas:
            raise ConsultaInvalida(f"Não achei '{dito.strip()}' desse jeito. O que há parecido para vender está nas "
                                   "opções; pergunte qual.", 409, opcoes=[_apres_txt(a) for a in proximas[:MAX_OPCOES]])
        raise ConsultaInvalida(f"Não achei preço para '{dito.strip()}'. Confira o nome do produto ou veja os preços "
                               "(ver_precos); apresentação nova só pela tela.", 404)
    raise ConsultaInvalida(f"Mais de um jeito de vender '{dito.strip()}'; pergunte qual.", 409,
                           opcoes=[_apres_txt(a) for a in achadas[:MAX_OPCOES]])


def _itens(itens) -> list[tuple[Apresentacao, int]]:
    return [(a, q) for a, q, _ in _itens_com_lotes(itens)]


def _itens_com_lotes(itens) -> list[tuple[Apresentacao, int, list | None]]:
    """Itens falados com os lotes indicados ("peguei 10 do lote do dia 10") já resolvidos para o núcleo."""
    pedidos = _dicts(itens)
    if not pedidos:
        raise ConsultaInvalida("Diga os itens: produto, quantidade e, se houver mais de um jeito de vender, "
                               "a apresentação (unidade, caixa com 25...) e a conservação.")
    saida = []
    for p in pedidos:
        a = _apresentacao(p)
        saida.append((a, _inteiro(p.get("quantidade"), "quantidade"), lotes_indicados(a, _dicts(p.get("lotes")))))
    return saida


def _itens_nucleo(lidos) -> list[dict]:
    return [{"apresentacao_id": a.id, "quantidade": q, **({"lotes": l} if l else {})} for a, q, l in lidos]


def _data_venda(valor) -> date | None:
    """"ontem", "anteontem", "dia 12", AAAA-MM-DD: o dia em que a venda aconteceu (vazio = hoje). Data futura o
    núcleo recusa."""
    from .despesas import _data as data_falada

    d = data_falada(valor, "data", passado=True)
    return None if d == timezone.localdate() else d


def _cliente(nome, *, obrigatorio="") -> Cliente | None:
    if not (nome or "").strip():
        if obrigatorio:
            raise ConsultaInvalida(obrigatorio)
        return None
    return escolher(Cliente.objects.filter(ativo=True).order_by("nome"), nome, oque="cliente")


def _cliente_qualquer(nome) -> Cliente:
    """Para consultas: o cliente pelo nome, ativo ou não."""
    return escolher(Cliente.objects.order_by("nome"), nome, oque="cliente")


def _tabela(valor) -> str:
    v = _normal(valor or "varejo")
    if v.startswith("atac"):
        return "atacado"
    if v.startswith("varej") or not v:
        return "varejo"
    raise ConsultaInvalida("'tabela' deve ser varejo ou atacado.")


def _dia(valor, nome) -> date | None:
    """"hoje", "amanhã", "depois de amanhã", dia da semana ("sábado": o próximo, hoje incluído) ou AAAA-MM-DD."""
    v = _normal(str(valor or ""))
    if not v:
        return None
    hoje = timezone.localdate()
    if v == "hoje":
        return hoje
    if v == "amanha":
        return hoje + timedelta(days=1)
    if v.replace("-", " ") == "depois de amanha":
        return hoje + timedelta(days=2)
    for i, nome_dia in enumerate(_DIAS_SEMANA):
        if v.startswith(nome_dia):
            return hoje + timedelta(days=(i - hoje.weekday()) % 7)
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ConsultaInvalida(f"'{nome}' deve ser hoje, amanhã, um dia da semana ou uma data AAAA-MM-DD.") from None


def _hora(valor) -> str | None:
    v = _normal(str(valor or "")).replace(" ", "")
    if not v:
        return None
    m = re.fullmatch(r"(\d{1,2})(?:[h:](\d{2})?)?(?:min)?", v)
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        raise ConsultaInvalida("'hora' deve ser como 15:30 ou 15h.")
    return f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"


def _destino(valor) -> str:
    v = _normal(valor or "perda")
    if v.startswith("perd") or "lixo" in v or "fora" in v:
        return "perda"
    if "estoque" in v or v.startswith("volt"):
        return "estoque"
    raise ConsultaInvalida("'destino' deve ser perda ou estoque (volta ao estoque).")


def _parcelas(total, *, prazo_dias, vencimento, parcelas, intervalo_dias, desde, pergunta):
    if vencimento:
        primeiro = _data(vencimento, "vencimento")
    elif not _sem_valor(prazo_dias):
        primeiro = desde + timedelta(days=_inteiro(prazo_dias, "prazo_dias"))
    else:
        raise ConsultaInvalida(pergunta)
    if total is None:
        return []  # sem preço na tabela: o núcleo recusa a venda com a mensagem certa
    return dividir_parcelas(total, _inteiro(parcelas or 1, "parcelas"), primeiro,
                            _inteiro(intervalo_dias or 30, "intervalo_dias"))


def _prazo_txt(parcelas) -> str:
    if len(parcelas) == 1:
        return f"a prazo, vence {quando(parcelas[0]['vencimento'])}"
    return f"a prazo em {len(parcelas)} parcelas: " + _juntar(
        f"{reais(p['valor'])} {quando(p['vencimento'])}" for p in parcelas)


def _forma_txt(forma) -> str:
    f = (forma or "").strip()
    return f" no {f}" if f else ""


# --- consultas (nível 0) -------------------------------------------------------------

def _filtrar_por_produto(linhas, produto, rotulo):
    ditos = _tokens(produto)
    return [l for l in linhas if _cobre(ditos, _tokens(rotulo(l)))] if ditos else linhas


def ver_precos(produto=""):
    lista = _filtrar_por_produto(vc.apresentacoes(), produto,
                                 lambda a: f"{a['produto']} {a['nome']} {a['forma']} {a['estado']}")
    if not lista:
        texto = (f"Não há preço cadastrado para '{produto}'." if produto
                 else "Nenhum preço cadastrado ainda; os preços se cadastram pela tela.")
    else:
        texto = "Preços: " + _ate_cinco(
            f"{a['nome']} de {a['produto']}, {_jeito(a['forma'], a['estado'])}, {reais(a['preco_varejo'])}"
            + (f", no atacado {reais(a['preco_atacado'])}" if a["preco_atacado"] else "")
            + f", dá para vender {_num(a['livre_apresentacoes'])} agora" for a in lista)
    return {"precos": [{"apresentacao_id": a["apresentacao_id"], "produto": a["produto"], "apresentacao": a["nome"],
                        "forma": a["forma"], "conservacao": a["estado"], "unidades": a["unidades"],
                        "preco_varejo": _dinheiro(a["preco_varejo"]),
                        "preco_atacado": _dinheiro(a["preco_atacado"]) if a["preco_atacado"] else None,
                        "da_para_vender": a["livre_apresentacoes"]} for a in lista], "texto": texto}


def ver_estoque_para_venda(produto=""):
    lista = _filtrar_por_produto(vc.estoque_para_venda(), produto,
                                 lambda e: f"{e['produto']} {e['forma']} {e['estado']}")
    if not lista:
        texto = f"Nenhum salgado de '{produto}' no estoque." if produto else "Nenhum salgado pronto no estoque."
    else:
        def frase(e):
            t = f"{e['produto']}, {_jeito(e['forma'], e['estado'])}: {_un(e['livre'])} para vender"
            if e["reservado"]:
                t += f", {_un(e['reservado'])} reservadas para encomendas"
            if e["vencido"]:
                t += f", {_un(e['vencido'])} vencidas"
            return t
        texto = _ate_cinco(frase(e) for e in lista)
        texto = texto[0].upper() + texto[1:]
    return {"estoque": [{"produto": e["produto"], "forma": e["forma"], "conservacao": e["estado"],
                         "saldo": float(e["saldo"]), "reservado": float(e["reservado"]),
                         "vencido": float(e["vencido"]), "livre": float(e["livre"])} for e in lista], "texto": texto}


def buscar_clientes(busca=""):
    cs = [c for c in vc.clientes(ativos=False) if not busca or _casa(busca, c["nome"])]
    if not cs:
        texto = f"Nenhum cliente com o nome '{busca}'." if busca else "Nenhum cliente cadastrado."
    else:
        texto = "Clientes: " + _juntar(c["nome"] + ("" if c["ativo"] else " (inativo)") for c in cs) + "."
    return {"clientes": [{"cliente_id": c["cliente_id"], "nome": c["nome"], "contato": c["contato"],
                          "ativo": c["ativo"]} for c in cs], "texto": texto}


def _linhas_txt(linhas) -> str:
    apres = Apresentacao.objects.select_related("produto").in_bulk({l["apresentacao_id"] for l in linhas})
    return _juntar(_apres_txt(apres[l["apresentacao_id"]], l["quantidade"]) for l in linhas)


def _venda_curta(v) -> dict:
    return {"venda_id": v["venda_id"], "data": v["data"].isoformat(), "cliente": v["cliente"],
            "condicao": v["condicao"], "forma_pagamento": v["forma_pagamento"], "total": _dinheiro(v["total"]),
            "situacao": v["situacao"], "encomenda_id": v["encomenda_id"],
            "itens": [{"apresentacao": l["apresentacao"], "quantidade": l["quantidade"], "unidades": l["unidades"],
                       "preco": _dinheiro(l["preco"]), "total": _dinheiro(l["total"])} for l in v["linhas"]]}


def _venda_txt(v) -> str:
    t = f"Venda {v['venda_id']}"
    if v["cliente"]:
        t += f", {v['cliente']}"
    t += f", {_linhas_txt(v['linhas'])}, {reais(v['total'])}"
    if v["condicao"] == "a_prazo":
        t += ", a prazo"
    if v["situacao"] == "cancelada":
        t += ", cancelada"
    return t


def ver_vendas(periodo="hoje", cliente=""):
    de, ate, quando_txt = _periodo(periodo)
    c = _cliente_qualquer(cliente) if (cliente or "").strip() else None
    r = vc.vendas(de=de, ate=ate, cliente_id=c.id if c else None, incluir_canceladas=True)
    t, lista = r["totais"], r["vendas"]
    de_quem = f" para {c.nome}" if c else ""
    if not t["vendas"]:
        texto = f"{quando_txt.capitalize()}, nenhuma venda{de_quem}."
    else:
        texto = f"{quando_txt.capitalize()}, {_n(t['vendas'], 'venda')}{de_quem}, somando {reais(t['total'])}"
        partes = []
        if t["recebido_na_hora"]:
            formas = [f"{reais(v)} {'sem forma dita' if f == 'não informada' else 'no ' + f}"
                      for f, v in t["por_forma_pagamento"].items()]
            partes.append(f"{reais(t['recebido_na_hora'])} recebidos na hora"
                          + (f" ({_juntar(formas)})" if len(formas) > 1 or "sem forma" not in formas[0] else ""))
        if t["a_prazo"]:
            partes.append(f"{reais(t['a_prazo'])} a prazo")
        texto += (": " + _juntar(partes) if partes else "") + ". "
        texto += "Por produto: " + _ate_cinco(f"{p['produto']}, {_un(p['unidades'])}, {reais(p['total'])}"
                                              for p in t["por_produto"])
    if t["canceladas"]:
        texto += f" {_n(t['canceladas'], 'venda cancelada', 'vendas canceladas')} fora da conta."
    return {"de": de.isoformat(), "ate": ate.isoformat(),
            "totais": {"vendas": t["vendas"], "total": _dinheiro(t["total"]),
                       "recebido_na_hora": _dinheiro(t["recebido_na_hora"]), "a_prazo": _dinheiro(t["a_prazo"]),
                       "por_forma_pagamento": {f: _dinheiro(v) for f, v in t["por_forma_pagamento"].items()},
                       "por_produto": [{"produto": p["produto"], "unidades": p["unidades"],
                                        "total": _dinheiro(p["total"])} for p in t["por_produto"]],
                       "canceladas": t["canceladas"]},
            "vendas": [_venda_curta(v) for v in lista[-20:]], "texto": texto}


def ver_venda(venda_id=None, cliente=""):
    if venda_id is None:
        if not (cliente or "").strip():
            raise ConsultaInvalida("Diga o número da venda ou o cliente.")
        c = _cliente_qualquer(cliente)
        # "o que ela comprou?": a venda da conta mais antiga em aberto; sem dívida, a última venda
        ps = fc.receber_em_aberto(cliente_id=c.id)
        ultimas = vc.vendas(cliente_id=c.id)["vendas"]
        if not ps and not ultimas:
            raise ConsultaInvalida(f"Nenhuma venda para {c.nome}.", 404)
        venda_id = ps[0]["venda_id"] if ps else ultimas[-1]["venda_id"]
    v = vc.detalhe_venda(_inteiro(venda_id, "venda_id"))
    if v is None:
        raise ConsultaInvalida("Venda não encontrada.", 404)
    return {**_venda_curta(v), "texto": f"{_venda_txt(v)}, {_sem_em(quando(v['data']))}."}


def _quando_encomenda(e) -> str:
    t = _para(e["entrega_data"]) + _hora_txt(e["entrega_hora"])
    return f"era {t}, já passou" if e["dias"] < 0 else t


def _falta_txt(e) -> str:
    falta = [i for i in e["itens"] if i["falta"] > 0]
    return _juntar(f"{_un(i['falta'])} de {i['produto']} {_jeito(i['forma'], i['estado'])}" for i in falta)


def _situacao_txt(e) -> str:
    if e["situacao"] == "pronta":
        return "pronta, tudo reservado"
    if e["situacao"] == "aberta":
        return f"falta reservar {_falta_txt(e)}"
    if e["situacao"] == "entregue":
        return f"entregue (venda {e['venda_id']})"
    return f"cancelada ({e['motivo_cancelamento']})"


def _encomenda_txt(e) -> str:
    itens = _juntar(_apres_txt(Apresentacao.objects.select_related("produto").get(id=i["apresentacao_id"]),
                               i["quantidade"]) for i in e["itens"])
    modo = "entrega" if e["modo"] == "entrega" else "retirada"
    return f"Encomenda {e['encomenda_id']} de {e['cliente']}, {_quando_encomenda(e)}, {modo}: {itens}; {_situacao_txt(e)}"


def _encomenda_curta(e) -> dict:
    return {"encomenda_id": e["encomenda_id"], "cliente": e["cliente"], "entrega_data": e["entrega_data"].isoformat(),
            "entrega_hora": e["entrega_hora"].strftime("%H:%M") if e["entrega_hora"] else None,
            "modo": e["modo"], "situacao": e["situacao"], "total": _dinheiro(e["total"]),
            "sinal": _dinheiro(e["sinal"]), "saldo": _dinheiro(e["saldo"]), "falta_unidades": float(e["falta"]),
            "observacao": e["observacao"],
            "itens": [{"apresentacao": i["apresentacao"], "quantidade": i["quantidade"], "unidades": i["unidades"],
                       "preco": _dinheiro(i["preco"]), "total": _dinheiro(i["total"]),
                       "reservado": float(i["reservado"]), "falta": float(i["falta"])} for i in e["itens"]]}


def ver_encomendas(dia="", cliente=""):
    c = _cliente_qualquer(cliente) if (cliente or "").strip() else None
    v = _normal(dia or "")
    hoje = timezone.localdate()
    if not v or v in ("todas", "abertas", "tudo"):
        de = ate = None
        sobre = ""
    elif "semana" in v:
        de, ate, sobre = hoje, hoje + timedelta(days=6), " nos próximos 7 dias"
    else:
        de = ate = _dia(dia, "dia")
        sobre = " " + _para(de)
    lista = vc.encomendas(de=de, ate=ate, cliente_id=c.id if c else None)
    de_quem = f" de {c.nome}" if c else ""
    if not lista:
        texto = f"Nenhuma encomenda em aberto{de_quem}{sobre}."
    else:
        prontas = sum(e["situacao"] == "pronta" for e in lista)
        cabeca = f"{_n(len(lista), 'encomenda')} em aberto{de_quem}{sobre}"
        if prontas == len(lista):
            cabeca += ", todas prontas"
        elif prontas:
            cabeca += f", {prontas} pronta" + ("s" if prontas > 1 else "")
        texto = cabeca + ". " + _ate_cinco(_encomenda_txt(e) for e in lista)
    return {"encomendas": [_encomenda_curta(e) for e in lista], "texto": texto}


def ver_encomenda(encomenda_id):
    e = vc.detalhe_encomenda(_inteiro(encomenda_id, "encomenda_id"))
    if e is None:
        raise ConsultaInvalida("Encomenda não encontrada.", 404)
    t = _encomenda_txt(e) + f". Total {reais(e['total'])}"
    if e["sinal"]:
        t += f", sinal de {reais(e['sinal'])}" + _forma_txt(e["sinal_forma"])
        if e["situacao"] in ("aberta", "pronta"):
            t += f", falta receber {reais(e['saldo'])} na entrega"
    if e["observacao"]:
        t += f". Observação: {e['observacao'].rstrip('.')}"
    return {**_encomenda_curta(e), "venda_id": e["venda_id"], "texto": t + "."}


def ver_necessidade_producao(dias=3):
    dias = _inteiro(dias, "dias")
    lista = vc.necessidade_producao(dias=dias)
    janela = f"as encomendas até daqui a {_n(dias, 'dia')}"
    if not lista:
        texto = f"Para {janela}, não falta nada: está tudo reservado."
    else:
        def frase(n):
            t = f"{n['produto']} {_jeito(n['forma'], n['estado'])}: faltam {_un(n['falta'])}"
            if n["livre"] > 0:
                t += f", {_un(min(n['livre'], n['falta']))} já estão no estoque e dá para reservar"
            if n["a_produzir"] > 0:
                t += f", produzir {_un(n['a_produzir'])}"
            return t + f", a primeira entrega é {_sem_em(quando(n['primeira_entrega']))}"
        texto = f"Para {janela}: " + _ate_cinco(frase(n) for n in lista)
    return {"dias": dias, "necessidade": [{"produto": n["produto"], "forma": n["forma"], "conservacao": n["estado"],
                                            "falta": float(n["falta"]), "livre": float(n["livre"]),
                                            "a_produzir": float(n["a_produzir"]),
                                            "primeira_entrega": n["primeira_entrega"].isoformat(),
                                            "encomendas": n["encomendas"]} for n in lista], "texto": texto}


_SITUACOES_RECEBER = {"todas": "todas", "aberta": "todas", "abertas": "todas", "vencidas": "vencidas",
                      "vencida": "vencidas", "a_vencer": "a_vencer", "a vencer": "a_vencer", "vencer": "a_vencer"}


def _parcela_receber(p) -> dict:
    return {"parcela_id": p["parcela_id"], "cliente": p["cliente"], "venda_id": p["venda_id"], "numero": p["numero"],
            "de": p["de"], "saldo": _dinheiro(p["saldo"]), "vencimento": p["vencimento"].isoformat(),
            "vencida": p["vencida"]}


def ver_a_receber(cliente="", situacao="todas", dias=7):
    tipo = _SITUACOES_RECEBER.get(_normal(situacao or "todas"))
    if tipo is None:
        raise ConsultaInvalida("'situacao' deve ser todas, vencidas ou a_vencer.")
    dias = _inteiro(dias, "dias")
    if (cliente or "").strip():
        c = _cliente_qualquer(cliente)
        ps = fc.receber_em_aberto(cliente_id=c.id)
        devido = sum((p["saldo"] for p in ps), ZERO)
        vencido = sum((p["saldo"] for p in ps if p["vencida"]), ZERO)
        if not ps:
            texto = f"{c.nome} não deve nada."
        else:
            texto = (f"{c.nome} deve {reais(devido)} em {_n(len(ps), 'parcela')}, "
                     + (f"{reais(vencido)} já vencidos." if vencido else "nada vencido.")
                     + f" A mais antiga: venda {ps[0]['venda_id']}, {_parcela_txt(ps[0])}.")
        return {"cliente": c.nome, "devido": _dinheiro(devido), "vencido": _dinheiro(vencido),
                "parcelas": [_parcela_receber(p) for p in ps], "texto": texto}
    if tipo == "vencidas":
        ps = fc.receber_vencidas()
    elif tipo == "a_vencer":
        ps = fc.receber_a_vencer(dias=dias)
    else:
        ps = None
    if ps is not None:
        total = sum((p["saldo"] for p in ps), ZERO)
        if not ps:
            texto = ("Nenhum cliente com conta vencida." if tipo == "vencidas"
                     else f"Nada a receber nos próximos {_n(dias, 'dia')}.")
        else:
            cabeca = (f"{_n(len(ps), 'conta a receber vencida', 'contas a receber vencidas')}" if tipo == "vencidas"
                      else f"{_n(len(ps), 'parcela')} a receber nos próximos {_n(dias, 'dia')}")
            texto = f"{cabeca}, somando {reais(total)}. " + _ate_cinco(
                f"{p['cliente']}, venda {p['venda_id']}, {_parcela_txt(p)}" for p in ps)
        return {"parcelas": [_parcela_receber(p) for p in ps], "total": _dinheiro(total), "texto": texto}
    devido = fc.devido_por_cliente()
    total = sum((d["devido"] for d in devido), ZERO)
    vencido = sum((d["vencido"] for d in devido), ZERO)
    if not devido:
        texto = "Nenhum cliente está devendo."
    else:
        texto = (f"Os clientes devem {reais(total)} no total"
                 + (f", {reais(vencido)} já vencidos" if vencido else "") + ". "
                 + _ate_cinco(f"{d['cliente']}, {reais(d['devido'])}"
                              + (f", sendo {reais(d['vencido'])} vencidos" if d["vencido"] else "") for d in devido))
    return {"clientes": [{"cliente": d["cliente"], "devido": _dinheiro(d["devido"]), "vencido": _dinheiro(d["vencido"]),
                          "parcelas": d["parcelas"]} for d in devido],
            "total": _dinheiro(total), "vencido": _dinheiro(vencido), "texto": texto}


def ver_sobras():
    sobras = vc.sobras_fritas()
    if not sobras:
        texto = "Nenhuma sobra de salgado frito no estoque."
    else:
        total = sum((s["saldo"] for s in sobras), ZERO)
        texto = f"Sobras fritas: {_un(total)}. " + _ate_cinco(
            f"{_un(s['saldo'])} de {s['item']} fritas {_sem_em(quando(s['frito_em']))}, {s['estado']}"
            + (f", {_un(s['reservado'])} reservadas" if s["reservado"] else "")
            + (", vencidas" if s["vencido"] else "") for s in sobras)
    return {"sobras": [{"lote_id": s["lote_id"], "codigo": s["codigo"], "produto": s["item"],
                        "conservacao": s["estado"], "saldo": float(s["saldo"]), "reservado": float(s["reservado"]),
                        "frito_em": s["frito_em"].isoformat(), "validade": _iso(s["validade"]),
                        "vencido": s["vencido"]} for s in sobras], "texto": texto}


# --- nível 1 ---------------------------------------------------------------------------

def cadastrar_cliente(*, nome, contato="", autor, canal):
    nome = (nome or "").strip()
    r, rep = _uma_vez("cadastrar_cliente", {"nome": _normal(nome)}, lambda chave: salvar_cliente(
        nome=nome, contato=contato, autor=autor, canal=canal, chave=chave))
    return _feito(f"Cliente {r['nome']} cadastrado.", r, rep, cliente_id=r["cliente_id"])


def _encomenda_aberta(encomenda_id=None, cliente="") -> dict:
    if encomenda_id:
        e = vc.detalhe_encomenda(_inteiro(encomenda_id, "encomenda_id"))
        if e is None:
            raise ConsultaInvalida("Encomenda não encontrada.", 404)
        return e  # entregue ou cancelada: quem recusa é o núcleo
    if not (cliente or "").strip():
        raise ConsultaInvalida("Diga de qual encomenda: o nome do cliente ou o número da encomenda.")
    c = _cliente_qualquer(cliente)
    abertas = vc.encomendas(cliente_id=c.id)
    if not abertas:
        raise ConsultaInvalida(f"Nenhuma encomenda em aberto de {c.nome}.", 404)
    if len(abertas) > 1:
        raise ConsultaInvalida(f"{c.nome} tem mais de uma encomenda em aberto; diga qual (encomenda_id).", 409,
                               opcoes=[f"Encomenda {e['encomenda_id']}, {_quando_encomenda(e)}, {reais(e['total'])}"
                                       for e in abertas])
    return abertas[0]


def completar_reserva(*, encomenda_id=None, cliente="", autor, canal):
    e = _encomenda_aberta(encomenda_id, cliente)
    n = e["encomenda_id"]
    r, rep = _uma_vez("completar_reserva", {"encomenda": n}, lambda chave: _completar(
        encomenda_id=n, autor=autor, canal=canal, chave=chave))
    if Decimal(str(r["falta"])) <= 0:
        dito = f"Encomenda {n} de {e['cliente']}: reserva completa, está pronta {_para(e['entrega_data'])}."
    else:
        faltas = _juntar(f"{_un(i['falta'])} de {_apres_txt(Apresentacao.objects.select_related('produto').get(id=i['apresentacao_id']))}"
                         for i in r["itens"] if Decimal(str(i["falta"])) > 0)
        dito = f"Encomenda {n} de {e['cliente']}: reservei o que havia no estoque; ainda falta {faltas}."
    if r.get("reservas_liberadas"):
        dito += " Troquei a reserva do lote que venceria antes da entrega."
    return _feito(dito, r, rep, encomenda_id=n)


# --- nível 2: venda --------------------------------------------------------------------

def _total_tabela(itens, tabela):
    """Soma do preço de tabela das linhas, só para dividir as parcelas; sem preço, None (o núcleo recusa)."""
    total = ZERO
    for a, q in itens:
        preco = a.preco_atacado if tabela == "atacado" else a.preco_varejo
        if preco is None:
            return None
        total += preco * q
    return total


def _linhas_venda_txt(itens, linhas) -> str:
    return _juntar(f"{_apres_txt(a, q)}, " + (f"a {reais(l['preco'])} cada" if q > 1 else f"por {reais(l['preco'])}")
                   for (a, q), l in zip(itens, linhas))


def _separacao_venda(lidos, quando_venda, motivo_vencido=""):
    from vendas.lotes import separacao_venda

    return separacao_venda(itens=_itens_nucleo(lidos), data_venda=quando_venda, motivo_vencido=motivo_vencido)


def ver_separacao(*, itens, data=""):
    """"30 coxinhas, de onde eu pego?": a separação do núcleo (a mesma que a venda vai baixar), falada."""
    lidos = _itens_com_lotes(itens)
    return separacao_resposta(_separacao_venda(lidos, _data_venda(data)))


def _motivo(motivo_vencido, vencidos) -> str:
    """O motivo só vai para o núcleo quando há vencido na separação (a trilha não guarda motivo à toa)."""
    return (motivo_vencido or "").strip() if vencidos else ""


def _separacao_proposta(sep, motivo) -> str:
    """O que a proposta diz da separação: só o lote de onde sai (produto e quantidade já foram ditos) e, se
    houver, o vencido com o motivo."""
    t = ". " + separacao_curta(sep).rstrip(".")
    return t + vencidos_txt([(n, v, "") for n, v in vencidos_da_separacao(sep)], motivo)


def propor_registrar_venda(*, itens, cliente="", condicao="a_vista", forma_pagamento="", tabela="varejo",
                           prazo_dias=None, vencimento="", parcelas=1, intervalo_dias=30, data="",
                           motivo_vencido="", autor, canal):
    lidos = _itens_com_lotes(itens)
    cond = _condicao(condicao or "a_vista")
    c = _cliente(cliente, obrigatorio="Venda a prazo precisa do cliente: para quem foi?" if cond == "a_prazo" else "")
    tab = _tabela(tabela)
    dia_venda = _data_venda(data)
    sep = _separacao_venda(lidos, dia_venda, motivo_vencido)
    checar_motivo_na_separacao(sep)
    motivo = _motivo(motivo_vencido, vencidos_da_separacao(sep))
    parametros = {"itens": _itens_nucleo(lidos), "tabela": tab, "cliente_id": c.id if c else None, "condicao": cond}
    if dia_venda:
        parametros["data_venda"] = dia_venda
    if motivo:
        parametros["motivo_vencido"] = motivo
    if cond == "a_prazo":
        parametros["parcelas"] = _parcelas(_total_tabela([(a, q) for a, q, _ in lidos], tab), prazo_dias=prazo_dias,
                                           vencimento=vencimento, parcelas=parcelas, intervalo_dias=intervalo_dias,
                                           desde=dia_venda or timezone.localdate(),
                                           pergunta="Quando o cliente vai pagar? Diga o prazo em dias ou a data.")
    else:
        parametros["forma_pagamento"] = (forma_pagamento or "").strip()

    def resumir(r):
        t = f"Vender {_linhas_venda_txt([(a, q) for a, q, _ in lidos], r['linhas'])}"
        if c:
            t += f", para {c.nome}"
        if dia_venda:
            t += f", venda de {_sem_em(quando(dia_venda))}"
        t += f". Total {reais(r['total'])}" + (", preço de atacado" if tab == "atacado" else "")
        if cond == "a_vista":
            t += ", à vista" + _forma_txt(forma_pagamento)
        else:
            t += ", " + _prazo_txt(r["parcelas"])
        return t + _separacao_proposta(sep, motivo)

    return pedir_motivo(lambda: _proposta("registrar_venda", parametros, resumir, autor, canal))


def _venda_alvo(venda_id, cliente) -> dict:
    if venda_id:
        v = vc.detalhe_venda(_inteiro(venda_id, "venda_id"))
        if v is None:
            raise ConsultaInvalida("Venda não encontrada.", 404)
        return v  # já cancelada: quem recusa é o núcleo
    if (cliente or "").strip():
        c = _cliente_qualquer(cliente)
        lista = list(reversed(vc.vendas(cliente_id=c.id)["vendas"]))
        if not lista:
            raise ConsultaInvalida(f"Nenhuma venda de {c.nome} para cancelar.", 404)
    else:
        lista = list(reversed(vc.vendas_do_dia()["vendas"]))
        if not lista:
            raise ConsultaInvalida("Nenhuma venda hoje. Diga o cliente ou o número da venda.", 404)
    if len(lista) > 1:
        raise ConsultaInvalida("Há mais de uma venda; diga qual (venda_id).", 409,
                               opcoes=[f"{_venda_txt(v)}, {quando(v['data'])}" for v in lista[:MAX_OPCOES]])
    return lista[0]


def _vencidos_da_venda(venda_id) -> list[tuple]:
    """Porções vencidas hoje de onde a venda saiu (o que voltaria vencido ao estoque)."""
    from vendas.models import LinhaVenda

    saida = []
    for l in LinhaVenda.objects.filter(venda_id=venda_id).select_related("apresentacao"):
        for b in l.baixas:
            if b["item_id"] != l.apresentacao.produto_id:
                continue
            x = porcao_vencida(Lote.objects.select_related("item").get(id=b["lote_id"]), b["estado"])
            if x and x not in saida:
                saida.append(x)
    return saida


def propor_cancelar_venda(*, motivo, venda_id=None, cliente="", destino="perda", motivo_vencido="", autor, canal):
    v = _venda_alvo(venda_id, cliente)
    d = _destino(destino)
    parametros = {"venda_id": v["venda_id"], "motivo": motivo, "destino": d}
    vencidos = _vencidos_da_venda(v["venda_id"]) if d == "estoque" else []
    mv = _motivo(motivo_vencido, vencidos)
    if mv:
        parametros["motivo_vencido"] = mv

    def resumir(r):
        t = (f"Cancelar a venda {v['venda_id']}, de {_sem_em(quando(v['data']))}, {_linhas_txt(v['linhas'])}"
             + (f", para {v['cliente']}" if v["cliente"] else "")
             + f", total {reais(v['total'])} (motivo: {(motivo or '').strip()}). ")
        if d == "perda":
            t += "As unidades vão para perda e não voltam ao estoque"
        else:
            t += f"{_un(r['unidades_devolvidas'])} voltam ao estoque; a embalagem não volta"
        if v["conta_id"]:
            t += ". A conta a receber é cancelada"
        if Decimal(str(r["valor_devolvido"])) > 0:
            t += f". Fica anotado que {reais(r['valor_devolvido'])} voltam para o cliente"
        if mv:
            t += vencidos_txt(vencidos, mv) + " (volta ao estoque ainda vencido)"
        return t

    return pedir_motivo(lambda: _proposta("cancelar_venda", parametros, resumir, autor, canal))


# --- nível 2: encomendas ------------------------------------------------------------------

def propor_criar_encomenda(*, cliente, dia, itens, hora="", modo="retirada", observacao="", sinal=0,
                           sinal_forma="", tabela="varejo", autor, canal):
    c = _cliente(cliente, obrigatorio="Encomenda precisa do cliente: para quem é?")
    quando_entrega = _dia(dia, "dia")
    if quando_entrega is None:
        raise ConsultaInvalida("Para que dia é a encomenda?")
    lidos = _itens(itens)
    m = _normal(modo or "retirada")
    m = "entrega" if m.startswith("entreg") or "levar" in m else "retirada" if m.startswith("retir") or "busca" in m \
        else m
    s = ZERO if _sem_valor(sinal) else _decimal(sinal, "sinal")
    h = _hora(hora)
    parametros = {"cliente_id": c.id, "entrega_data": quando_entrega, "entrega_hora": h,
                  "itens": [{"apresentacao_id": a.id, "quantidade": q} for a, q in lidos], "tabela": _tabela(tabela),
                  "modo": m, "observacao": (observacao or "").strip(), "sinal": s,
                  "sinal_forma": (sinal_forma or "").strip()}

    def resumir(r):
        t = (f"Encomenda de {c.nome} {_para(quando_entrega)}{_hora_txt(h)}, "
             f"{'entrega' if m == 'entrega' else 'retirada'}: {_linhas_venda_txt(lidos, r['itens'])}. "
             f"Total {reais(r['total'])}")
        if s:
            t += f"; sinal de {reais(r['sinal'])}{_forma_txt(sinal_forma)}, fica faltando {reais(r['saldo'])}"
        if Decimal(str(r["falta"])) <= 0:
            t += ". Já fica tudo reservado no estoque"
        else:
            faltas = [(a, i) for (a, _), i in zip(lidos, r["itens"]) if Decimal(str(i["falta"])) > 0]
            t += (". Reserva agora o que há no estoque; falta produzir "
                  + _juntar(f"{_un(i['falta'])} de {a.produto.nome} {_jeito(a.forma, a.estado)}" for a, i in faltas))
        if parametros["observacao"]:
            t += f". Observação: {parametros['observacao'].rstrip('.')}"
        return t

    return _proposta("criar_encomenda", parametros, resumir, autor, canal)


def _lotes_entrega(encomenda_id, pedidos) -> list[dict] | None:
    """[{lote | lote_id, unidades, produto?}] falados → [{item_encomenda_id, lotes: [{lote_id, unidades}]}]. O item
    da encomenda sai do lote (produto e forma) e, se a encomenda tiver mais de um item que sirva, do 'produto' dito."""
    from vendas.models import ItemEncomenda

    pedidos = _dicts(pedidos)
    if not pedidos:
        return None
    itens = list(ItemEncomenda.objects.filter(encomenda_id=encomenda_id).select_related("apresentacao__produto"))
    por_item = {}
    for p in pedidos:
        candidatos = itens
        if (p.get("produto") or "").strip():
            ditos = _tokens(p["produto"])
            candidatos = [i for i in itens if _cobre(ditos, _tokens(_rotulo_apres(i.apresentacao)))] or itens
        lotes = {l.id: l for i in candidatos for l in lotes_da_apresentacao(i.apresentacao)}
        oque = _juntar(sorted({f"{i.apresentacao.produto.nome} {i.apresentacao.forma} {i.apresentacao.estado}"
                               for i in candidatos}))
        lote = resolver_lote(p.get("lote"), lotes.values(), oque=oque, lote_id=p.get("lote_id"))
        servem = [i for i in candidatos if i.apresentacao.produto_id == lote.item_id
                  and i.apresentacao.forma == lote.forma and lote in lotes_da_apresentacao(i.apresentacao)]
        if len(servem) > 1:
            raise ConsultaInvalida(f"O {nome(lote)} serve para mais de um item da encomenda; diga qual ('produto').",
                                   409, opcoes=[_apres_txt(i.apresentacao, i.quantidade) for i in servem])
        por_item.setdefault(servem[0].id, []).append(
            {"lote_id": lote.id, "unidades": _inteiro(p.get("unidades"), "unidades do lote")})
    return [{"item_encomenda_id": k, "lotes": v} for k, v in por_item.items()]


def _separacao_encomenda(n, dia, lotes, motivo_vencido=""):
    from vendas.lotes import separacao_encomenda

    return separacao_encomenda(encomenda_id=n, data_entrega=dia, lotes=lotes, motivo_vencido=motivo_vencido)


def ver_separacao_encomenda(*, encomenda_id=None, cliente="", data="", lotes=None):
    """"A encomenda do João, de quais lotes?": a separação da entrega (pelas reservas ou pelos lotes indicados)."""
    e = _encomenda_aberta(encomenda_id, cliente)
    n = e["encomenda_id"]
    sep = _separacao_encomenda(n, _data_venda(data), _lotes_entrega(n, lotes))
    r = separacao_resposta(sep, encomenda_id=n, cliente=e["cliente"])
    r["texto"] = f"Encomenda {n} de {e['cliente']}: {r['texto']}"
    return r


def propor_entregar_encomenda(*, encomenda_id=None, cliente="", condicao="a_vista", forma_pagamento="",
                              prazo_dias=None, vencimento="", parcelas=1, intervalo_dias=30, lotes=None, data="",
                              motivo_vencido="", autor, canal):
    e = _encomenda_aberta(encomenda_id, cliente)
    cond = _condicao(condicao or "a_vista")
    parametros = {"encomenda_id": e["encomenda_id"], "condicao": cond}
    dia_entrega = _data_venda(data)
    indicados = _lotes_entrega(e["encomenda_id"], lotes) if e["situacao"] in ("aberta", "pronta") else None
    sep = None
    if e["situacao"] in ("aberta", "pronta"):  # entregue/cancelada: quem recusa é o núcleo
        sep = _separacao_encomenda(e["encomenda_id"], dia_entrega, indicados, motivo_vencido)
        checar_motivo_na_separacao(sep)
    mv = _motivo(motivo_vencido, vencidos_da_separacao(sep) if sep else [])
    for k, v in (("data_entrega", dia_entrega), ("lotes", indicados), ("motivo_vencido", mv)):
        if v:
            parametros[k] = v
    if cond == "a_prazo" and e["saldo"] > 0:
        parametros["parcelas"] = _parcelas(e["saldo"], prazo_dias=prazo_dias, vencimento=vencimento,
                                           parcelas=parcelas, intervalo_dias=intervalo_dias,
                                           desde=timezone.localdate(),
                                           pergunta="Quando o cliente vai pagar o resto? Diga o prazo em dias ou a data.")
    else:
        parametros["forma_pagamento"] = (forma_pagamento or "").strip()

    def resumir(r):
        t = (f"Entregar a encomenda {e['encomenda_id']} de {e['cliente']}: {_linhas_txt(r['linhas'])}. "
             f"Total {reais(r['total'])}")
        sinal, saldo = Decimal(str(r["sinal"])), Decimal(str(r["saldo"]))
        if sinal:
            t += f", com {reais(sinal)} de sinal já pago"
        if saldo <= 0:
            t += ". Já está tudo pago"
        elif r["condicao"] == "a_vista":
            t += f". Recebe {reais(saldo)} agora" + _forma_txt(forma_pagamento)
        else:
            t += f". Os {reais(saldo)} ficam {_prazo_txt(r['parcelas'])}"
        if dia_entrega:
            t += f". Entrega de {_sem_em(quando(dia_entrega))}"
        return t + (_separacao_proposta(sep, mv) if sep else "")

    return pedir_motivo(lambda: _proposta("entregar_encomenda", parametros, resumir, autor, canal))


def propor_cancelar_encomenda(*, motivo, encomenda_id=None, cliente="", devolver_sinal=True, autor, canal):
    e = _encomenda_aberta(encomenda_id, cliente)
    parametros = {"encomenda_id": e["encomenda_id"], "motivo": motivo, "devolver_sinal": bool(devolver_sinal)}

    def resumir(r):
        t = (f"Cancelar a encomenda {e['encomenda_id']} de {e['cliente']}, {_quando_encomenda(e)}, "
             f"total {reais(e['total'])} (motivo: {(motivo or '').strip()}). As reservas são liberadas e nada sai "
             "do estoque")
        if Decimal(str(r["sinal"])) > 0:
            t += (f". O sinal de {reais(r['sinal'])} fica anotado como devolvido ao cliente" if devolver_sinal
                  else f". O sinal de {reais(r['sinal'])} fica com você, não é devolvido")
        return t

    return _proposta("cancelar_encomenda", parametros, resumir, autor, canal)


# --- nível 2: fritura e perda -----------------------------------------------------------

def _porcoes_cruas_do_lote(p, lote, conservacao):
    """Fritura de um lote dito ("frita do lote do dia 8"): as porções cruas dele, vencidas inclusive (vencido só
    sai com motivo, quem confere é o núcleo)."""
    crus = Lote.objects.select_related("item").filter(item=p, forma="cru")
    ps = [x for x in porcoes(item=p) if x["lote_id"] in {l.id for l in crus}]
    if (conservacao or "").strip():
        ps = [x for x in ps if x["estado"] == _estado(conservacao)]
    escolhido = resolver_lote(lote, [l for l in crus if l.id in {x["lote_id"] for x in ps}], oque=f"{p.nome} cru")
    return [x for x in ps if x["lote_id"] == escolhido.id]


def propor_registrar_fritura(*, produto, quantidade, boas=None, motivo_perdas="", conservacao="", destino="fresco",
                             validade="", justificativa="", lote="", motivo_vencido="", autor, canal):
    p = resolver_produto(produto)
    q = _inteiro(quantidade, "quantidade")
    b = q if _sem_valor(boas) and boas != 0 else _inteiro(boas, "boas")
    if (lote or "").strip():
        porcoes_cruas = _porcoes_cruas_do_lote(p, lote, conservacao)
    else:
        porcoes_cruas = vc.lotes_para_fritar(produto_id=p.id)
    if (conservacao or "").strip():
        estado = _estado(conservacao)
        porcoes_cruas = [x for x in porcoes_cruas if x["estado"] == estado]
    if not porcoes_cruas:
        onde = f" {_estado(conservacao)}" if (conservacao or "").strip() else ""
        raise ConsultaInvalida(f"Nenhum lote de {p.nome} cru{onde} livre para fritar (não vencido e não reservado).",
                               404)
    estados = list(dict.fromkeys(x["estado"] for x in porcoes_cruas))
    if len(estados) > 1:
        livres = {e: sum((x["livre"] for x in porcoes_cruas if x["estado"] == e), ZERO) for e in estados}
        raise ConsultaInvalida(f"Há {p.nome} cru em mais de uma conservação; pergunte de qual saiu.", 409,
                               opcoes=[f"{e}: {_un(livres[e])} livres" for e in estados])
    porcao = porcoes_cruas[0]  # a que vence primeiro (RN-18), ou a do lote dito
    destino_estado = _estado(destino or "fresco", "destino")
    cru = Lote.objects.select_related("item").get(id=porcao["lote_id"])
    vencido = porcao_vencida(cru, porcao["estado"])
    mv = _motivo(motivo_vencido, [vencido] if vencido else [])
    parametros = {"lote_id": porcao["lote_id"], "quantidade": q, "boas": b, "estado": porcao["estado"],
                  "estado_destino": destino_estado, "perda_motivo": (motivo_perdas or "").strip(),
                  "validade_manual": _data(validade, "validade"), "justificativa": justificativa,
                  "confirmar_perda_total": b == 0}
    if mv:
        parametros["motivo_vencido"] = mv
    origem = (f"do {nome(cru)}, {porcao['estado']}"
              + (f", que {'venceu' if vencido else 'vence'} {quando(porcao['validade'])}" if porcao["validade"] else ""))

    def resumir(r):
        t = f"Fritar {_un(q)} de {p.nome} {origem}: "
        perdas = r["perdas"]
        perda = f"{perdas} perdida{'s' if perdas > 1 else ''} ({parametros['perda_motivo']})" if perdas else ""
        if r["boas"] == 0:
            return (t + "PERDA TOTAL, nenhuma boa" + (f", {perda}" if perda else "")
                    + (vencidos_txt([vencido], mv) if mv else ""))
        t += f"{r['boas']} boa{'s' if r['boas'] > 1 else ''}" + (f" e {perda}" if perda else "")
        t += f". Custo de {reais(r['custo_unitario'])} por unidade frita"
        if r["validade"]:
            t += f"; o frito fica {destino_estado} e vale até {_sem_em(quando(r['validade']))}"
        return t + (vencidos_txt([vencido], mv) if mv else "")

    return pedir_motivo(lambda: _proposta("registrar_fritura", parametros, resumir, autor, canal))


def _porcao_para_perda(produto, *, conservacao="", forma="", lote="", vencido=False, lote_id=None):
    """(item, porção) com saldo pelo nome falado; ambíguo → opcoes com lote, conservação, validade e saldo."""
    if not (produto or "").strip():
        raise ConsultaInvalida("Diga o que vai ser jogado fora.")
    i = escolher(Item.objects.filter(ativo=True).order_by("nome"), produto, oque="item")
    ps = porcoes(item=i)
    if (conservacao or "").strip():
        estado = _estado(conservacao)
        ps = [x for x in ps if x["estado"] == estado]
    if (forma or "").strip():
        f = _forma(forma)
        formas = Lote.objects.in_bulk({x["lote_id"] for x in ps})
        ps = [x for x in ps if formas[x["lote_id"]].forma == f]
    if (lote or "").strip() or lote_id not in (None, ""):
        lotes = Lote.objects.select_related("item").in_bulk({x["lote_id"] for x in ps})
        escolhido = resolver_lote(lote, lotes.values(), oque=i.nome, lote_id=lote_id)
        ps = [x for x in ps if x["lote_id"] == escolhido.id]
    if vencido:
        ps = [x for x in ps if x["vencido"]]
    if not ps:
        raise ConsultaInvalida(f"Nenhum lote de {i.nome}" + (" vencido" if vencido else "") + " com saldo"
                               + (" nessa conservação" if (conservacao or "").strip() else "") + ".", 404)
    if len(ps) > 1:
        raise ConsultaInvalida(f"Há mais de um lote de {i.nome} com saldo; pergunte qual (conservação, frito ou "
                               "cru, ou o dia do lote).", 409, opcoes=[_porcao_txt(i, x) for x in ps[:MAX_OPCOES]])
    return i, ps[0]


def _porcao_txt(i, x) -> str:
    l = Lote.objects.get(id=x["lote_id"])
    forma = l.forma if i.tipo == "produto" else ""
    t = nome(l) + (f", {forma}" if forma else "") + (f", {x['estado']}" if x["estado"] else "")
    t += f", {qtd(x['saldo'], x['unidade_base'])}"
    if x["validade"]:
        t += f", {'venceu' if x['vencido'] else 'vence'} {quando(x['validade'])}"
    return t


_DESTINOS_PERDA = (("consumo_equipe", ("equipe", "consumo", "funcionari", "comeram", "comer")),
                   ("doacao", ("doa",)), ("descarte", ("descart", "lixo", "fora", "jog")), ("perda", ("perd",)))
_VERBO_DESTINO = {"perda": "Dar perda de", "descarte": "Descartar", "consumo_equipe": "Dar para consumo da equipe",
                  "doacao": "Doar"}


def _destino_perda(valor) -> str:
    """perda (padrão), descarte, consumo da equipe ou doação — como foi dito."""
    v = _normal(valor or "perda").replace("_", " ")
    for chave, sinais in _DESTINOS_PERDA:
        if any(s in v for s in sinais):
            return chave
    raise ConsultaInvalida("'destino' deve ser perda, descarte, consumo da equipe ou doação.")


def propor_perda_lote(lote, estado, quantidade, unidade, motivo, destino, *, autor, canal, resumo_porcao=None):
    """Proposta de perda de uma porção já escolhida (também a resposta "estão aqui" da conferência do vencido)."""
    i = lote.item
    x = next((p for p in porcoes(item=i) if p["lote_id"] == lote.id and p["estado"] == estado), None)
    porcao = resumo_porcao or (_porcao_txt(i, x) if x else nome(lote))
    parametros = {"lote_id": lote.id, "estado": estado, "quantidade": quantidade, "unidade": unidade,
                  "motivo": motivo}
    if destino != "perda":
        parametros["destino"] = destino

    def resumir(r):
        base = r["unidade_base"]
        quanto = _un(r["quantidade"]) if base == "un" else qtd(r["quantidade"], base)
        verbo = "Descartar" if r["vencido"] and destino == "perda" else _VERBO_DESTINO[destino]
        t = f"{verbo} {quanto} de {i.nome}, {porcao} (motivo: {(motivo or '').strip()}). "
        t += f"Sai do estoque sem volta: {reais(r['valor'])} em mercadoria"
        saldo = Decimal(str(r["saldo"]))
        t += f". Ficam {_un(saldo) if base == 'un' else qtd(saldo, base)} nesse lote" if saldo > 0 else \
            ". O lote fica zerado"
        if r["reservas_liberadas"]:
            t += (". Isso libera a reserva de encomenda que estava nesse lote vencido: depois complete a reserva "
                  "com outro lote")
        return t

    return _proposta("registrar_perda", parametros, resumir, autor, canal)


def propor_registrar_perda(*, produto, motivo, quantidade=None, unidade="", conservacao="", forma="", lote="",
                           vencido=False, destino="perda", lote_id=None, autor, canal):
    d = _destino_perda(destino)
    i, x = _porcao_para_perda(produto, conservacao=conservacao, forma=forma, lote=lote, vencido=vencido,
                              lote_id=lote_id)
    if _sem_valor(quantidade):  # sem quantidade: o lote todo (ex.: "joga fora o vencido")
        q, un = x["saldo"], i.unidade_base
    else:
        q = _decimal(quantidade, "quantidade")
        un = i.unidade_base if i.tipo == "produto" else (_unidade(i, unidade) or i.unidade_base)
    lote_obj = Lote.objects.select_related("item").get(id=x["lote_id"])
    return propor_perda_lote(lote_obj, x["estado"], q, un, motivo, d, autor=autor, canal=canal,
                             resumo_porcao=_porcao_txt(i, x))


# --- nível 2: contas a receber ------------------------------------------------------------

def _uma_parcela_receber(cliente, venda_id, valor):
    c = _cliente_qualquer(cliente) if (cliente or "").strip() else None
    if not c and not venda_id:
        raise ConsultaInvalida("Diga qual cliente pagou.")
    ps = fc.receber_em_aberto(cliente_id=c.id if c else None)
    if venda_id:
        ps = [p for p in ps if p["venda_id"] == _inteiro(venda_id, "venda_id")]
    de_quem = f" de {c.nome}" if c else ""
    if not ps:
        raise ConsultaInvalida(f"Nenhuma conta a receber{de_quem} em aberto.", 404)
    if len({p["conta_id"] for p in ps}) == 1:
        return ps[0]  # parcelas da mesma venda: abate-se a mais antiga
    if not _sem_valor(valor):
        mesmas = [p for p in ps if p["saldo"] == _decimal(valor, "valor").quantize(Decimal("0.01"))]
        if len(mesmas) == 1:
            return mesmas[0]
    raise ConsultaInvalida(f"Há mais de uma conta a receber{de_quem} em aberto; diga qual (parcela_id).", 409,
                           opcoes=[f"Parcela {p['parcela_id']}: {p['cliente']}, venda {p['venda_id']}, "
                                   f"{_parcela_txt(p)}" for p in ps])


def propor_registrar_recebimento(*, cliente="", valor=None, data_pagamento="", forma="", venda_id=None,
                                 parcela_id=None, juros=0, multa=0, desconto=0, motivo_diferenca="", autor, canal):
    if parcela_id:
        abertas = [p for p in fc.receber_em_aberto() if p["parcela_id"] == _inteiro(parcela_id, "parcela_id")]
        if not abertas:
            raise ConsultaInvalida("Essa parcela a receber não está em aberto.", 404)
        p = abertas[0]
    else:
        p = _uma_parcela_receber(cliente, venda_id, valor)
    difs = [(t, _decimal(v, t)) for t, v in (("juros", juros), ("multa", multa), ("desconto", desconto))
            if not _sem_valor(v)]
    if len(difs) > 1:
        raise ConsultaInvalida("Diga só um entre juros, multa e desconto.")
    tipo, dif = difs[0] if difs else ("", ZERO)
    dia = _data(data_pagamento, "data_pagamento") or timezone.localdate()
    parametros = {"parcela_id": p["parcela_id"], "valor": None if _sem_valor(valor) else _decimal(valor, "valor"),
                  "data_pagamento": dia, "forma": (forma or "").strip(), "diferenca": dif, "diferenca_tipo": tipo,
                  "diferenca_motivo": motivo_diferenca}

    def resumir(r):
        t = (f"Anotar que {p['cliente']} pagou {reais(r['valor_pago'])} {quando(dia)}, venda {p['venda_id']}, "
             f"{_parcela_txt(p)}" + _forma_txt(forma))
        if dif:
            t += f", com {reais(dif)} de {tipo}"
        return t + (". A parcela fica quitada" if r["situacao"] == "paga"
                    else f". Ficam faltando {reais(r['saldo'])} nesta parcela")

    return _proposta("registrar_recebimento", parametros, resumir, autor, canal)


def propor_estornar_recebimento_cliente(*, motivo, cliente="", pagamento_id=None, autor, canal):
    if pagamento_id:
        pid = _inteiro(pagamento_id, "pagamento_id")
        rs = [x for x in fc.recebimentos() if x["pagamento_id"] == pid]
        if not rs:
            raise ConsultaInvalida("Recebimento de cliente não encontrado ou já estornado.", 404)
    else:
        c = _cliente_qualquer(cliente) if (cliente or "").strip() else None
        if c is None:
            raise ConsultaInvalida("Diga de qual cliente é o recebimento a desfazer.")
        rs = list(reversed(fc.recebimentos(cliente_id=c.id)))
        if not rs:
            raise ConsultaInvalida(f"Nenhum recebimento anotado de {c.nome}.", 404)
    rotulo = lambda x: f"{reais(x['valor_pago'])} de {x['cliente']}, {_sem_em(quando(x['data']))}, venda {x['venda_id']}"
    if len(rs) > 1:
        raise ConsultaInvalida("Há mais de um recebimento; diga qual (pagamento_id).", 409,
                               opcoes=[f"Recebimento {x['pagamento_id']}: {rotulo(x)}" for x in rs[:MAX_OPCOES]])
    x = rs[0]
    return _proposta("estornar_recebimento_cliente", {"pagamento_id": x["pagamento_id"], "motivo": motivo}, lambda r: (
        f"Desfazer o recebimento de {rotulo(x)} (motivo: {(motivo or '').strip()}). "
        f"A parcela volta a ficar em aberto com {reais(r['saldo'])}"), autor, canal)


# --- o que dizer depois de confirmar ---------------------------------------------------

def depois(p) -> str:
    r = p.resultado
    if p.operacao == "registrar_venda":
        return f" É a venda {r['venda_id']}." + _avisos_falados(r)
    if p.operacao == "criar_encomenda":
        return f" É a encomenda {r['encomenda_id']}."
    if p.operacao == "entregar_encomenda":
        return f" Virou a venda {r['venda_id']}." + _avisos_falados(r)
    return ""


def _avisos_falados(r) -> str:
    """Os avisos da venda gravada (lote deixado para trás, vence hoje/amanhã), como se fala."""
    from .decisoes import falavel

    return "".join(f" {falavel(a)}" for a in r.get("avisos") or [])

