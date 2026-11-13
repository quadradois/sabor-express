"""De qual lote pegar (Plano 9): a instrução de separação antes de fechar a venda, o lote indicado pelo
atendente e o aviso do lote que ficou para trás.

O `Separador` é o mesmo para a consulta (que não grava) e para a venda/entrega (que gravam): a tela e o
agente mostram exatamente o que a venda vai baixar. FEFO por porção (lote + conservação) na forma e
conservação da apresentação, julgando a validade no dia da venda (`quando`), sem o reservado para encomendas
e **sem vencido**: vencido só sai por lote indicado + motivo (decisão do dono: aviso com motivo, não trava).
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from estoque.lotes import checar_vencido, dia_producao, nome_lote, texto_vencido, vencida
from estoque.models import Lote
from estoque.servicos import livre_porcao, porcoes, reservado, saldo_lote, validade_porcao
from nucleo.operacoes import RegraViolada
from nucleo.valores import data

from .models import Apresentacao, Encomenda

ZERO = Decimal("0")


def _n(q) -> str:
    """Unidades faladas: 18, não 18,000."""
    q = Decimal(q)
    return str(int(q)) if q == q.to_integral_value() else str(q.normalize()).replace(".", ",")


def _juntar(partes) -> str:
    """"a, b e c"; com oração no meio ("..., que vence amanhã"), a vírgula fecha a oração: "..., que vence
    amanhã, e c"."""
    if len(partes) == 1:
        return partes[0]
    e = ", e " if ", que " in partes[-2] else " e "
    return ", ".join(partes[:-1]) + e + partes[-1]


def _inteiro(v, campo) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        raise RegraViolada(f"Valor inválido em '{campo}' (use um número inteiro).") from None


def dia_da_venda(valor, campo="data_venda", *, hoje=None):
    """A data em que a venda aconteceu (padrão hoje). Futura não vale: venda se registra depois, nunca antes."""
    hoje = hoje or timezone.localdate()
    quando = data(valor, campo) or hoje
    if quando > hoje:
        raise RegraViolada(f"A venda não pode ter data depois de hoje ({quando:%d/%m}).")
    return quando


def _vence(validade, quando, hoje) -> str:
    if validade is None:
        return ""
    if vencida(validade, quando):
        return f", que venceu em {validade:%d/%m}"
    if quando == hoje:
        return {0: ", que vence hoje", 1: ", que vence amanhã"}.get((validade - quando).days, "")
    return ""


class Separador:
    """Aloca as linhas de uma venda (ou entrega) sem gravar, lembrando o que já foi pego nas linhas anteriores.

    `usar_reservas` = {(lote_id, estado): unidades} reservadas que podem ser usadas (as da própria encomenda).
    `exigir_motivo`: na venda (True), vencido indicado sem motivo é recusado; na consulta (False), vira aviso."""

    def __init__(self, *, quando, hoje=None, usar_reservas=None, motivo_vencido="", exigir_motivo=True):
        self.quando, self.hoje = quando, hoje or timezone.localdate()
        self.usar_reservas = usar_reservas or {}
        self.motivo_vencido, self.exigir_motivo = (motivo_vencido or "").strip(), exigir_motivo
        self.usado = defaultdict(Decimal)  # (lote_id, estado) -> unidades já pegas nesta venda
        self._lotes = {}

    # ---------- porções ----------

    def _candidatas(self, a) -> list[dict]:
        """Porções com saldo na forma e conservação da apresentação, FEFO. Lote feito depois do dia da venda
        vai para o fim (venda registrada depois: primeiro o que existia naquele dia)."""
        lotes = Lote.objects.select_related("item").filter(item=a.produto, forma=a.forma).in_bulk()
        saida = []
        for p in porcoes(item=a.produto, hoje=self.quando):
            if p["estado"] != a.estado or p["lote_id"] not in lotes:
                continue
            lote = self._lotes.setdefault(p["lote_id"], lotes[p["lote_id"]])
            saida.append({**p, "lote": lote, "depois": dia_producao(lote) > self.quando,
                          "vencido": vencida(p["validade"], self.quando)})
        return sorted(saida, key=lambda p: p["depois"])  # estável: dentro de cada grupo, a ordem FEFO

    def livre(self, lote, estado) -> Decimal:
        return (livre_porcao(lote, estado) + self.usar_reservas.get((lote.id, estado), ZERO)
                - self.usado[(lote.id, estado)])

    def _pegar(self, lote, estado, q):
        self.usado[(lote.id, estado)] += q

    # ---------- alocação ----------

    def fefo(self, a, unidades) -> tuple[list, Decimal]:
        """FEFO automático: nunca escolhe vencido sozinho. Devolve ([(lote, q)], quanto faltou)."""
        falta, saida = Decimal(unidades), []
        for p in self._candidatas(a):
            if falta <= 0:
                break
            if p["vencido"]:
                continue
            livre = self.livre(p["lote"], a.estado)
            if livre <= 0:
                continue
            q = min(livre, falta)
            self._pegar(p["lote"], a.estado, q)
            saida.append((p["lote"], q))
            falta -= q
        return saida, max(falta, ZERO)

    def indicada(self, a, unidades, lotes, n_linha=1) -> tuple[list, Decimal, list]:
        """Lotes que o atendente disse ter pego ([{lote_id, unidades}]). O que faltar para a linha sai por FEFO.
        Devolve ([(lote, q)], quanto faltou, avisos de vencido sem motivo — só na consulta)."""
        por_lote = defaultdict(int)
        for i, l in enumerate(lotes or [], 1):
            q = _inteiro(l.get("unidades"), f"item {n_linha}, lote {i}")
            if q < 1:
                raise RegraViolada(f"Item {n_linha}: as unidades de cada lote devem ser maiores que zero.")
            por_lote[l.get("lote_id")] += q
        if sum(por_lote.values()) > unidades:
            raise RegraViolada(f"Item {n_linha}: os lotes indicados somam {sum(por_lote.values())} un, mas o item "
                               f"pede {unidades} un.")
        saida, avisos = [], []
        for lote_id, q in por_lote.items():
            lote = Lote.objects.select_related("item").filter(id=lote_id).first()
            if lote is None:
                raise RegraViolada(f"Item {n_linha}: lote não encontrado.")
            self._lotes[lote.id] = lote
            nome = nome_lote(lote, hoje=self.hoje)
            if lote.item_id != a.produto_id:
                raise RegraViolada(f"O {nome} é de '{lote.item.nome}', não de '{a.produto.nome}'.")
            if lote.forma != a.forma:
                raise RegraViolada(f"O {nome} de '{a.produto.nome}' é {lote.forma or 'sem forma'}; "
                                   f"a apresentação é {a.forma}.")
            if dia_producao(lote) > self.quando:
                raise RegraViolada(f"O {nome} de '{a.produto.nome}' foi feito em {dia_producao(lote):%d/%m}, "
                                   f"depois do dia da venda ({self.quando:%d/%m}).")
            tem = saldo_lote(lote, a.estado) - self.usado[(lote.id, a.estado)]
            if q > tem:
                raise RegraViolada(f"O {nome} de '{a.produto.nome}' só tem {_n(max(tem, ZERO))} un em {a.estado}.")
            livre = self.livre(lote, a.estado)
            if q > livre:
                raise RegraViolada(f"Do {nome} de '{a.produto.nome}' só {_n(max(livre, ZERO))} un em {a.estado} não "
                                   "estão reservadas para encomendas.")
            validade = validade_porcao(lote, a.estado)
            if vencida(validade, self.quando):
                if self.exigir_motivo:
                    checar_vencido(lote, a.estado, validade, quando=self.quando, motivo_vencido=self.motivo_vencido,
                                   acao="vender dele")
                elif not self.motivo_vencido:
                    avisos.append({"tipo": "vencido_sem_motivo", "lote_id": lote.id, "precisa_motivo": True,
                                   "texto": f"{texto_vencido(lote, a.estado, validade)} Para vender dele, informe "
                                            "o motivo."})
            self._pegar(lote, a.estado, Decimal(q))
            saida.append((lote, Decimal(q)))
        resto, falta = self.fefo(a, Decimal(unidades - sum(por_lote.values())))
        return saida + resto, falta, avisos

    def deixados(self, a, alocacao) -> list[dict]:
        """Porções livres e válidas no dia da venda que vencem antes do lote mais novo que saiu nesta linha
        (o atendente pegou o mais novo e deixou o mais velho)."""
        validades = [validade_porcao(l, a.estado) for l, _ in alocacao]
        validas = [v or date.max for v in validades if not vencida(v, self.quando)]
        if not validas:
            return []
        limite, usados = max(validas), {l.id for l, _ in alocacao}
        saida = []
        for p in self._candidatas(a):
            if p["vencido"] or p["depois"] or (p["validade"] or date.max) >= limite:
                continue
            sobra = self.livre(p["lote"], a.estado)
            if sobra > 0:
                saida.append({"lote_id": p["lote_id"], "estado": a.estado, "unidades": sobra, "validade": p["validade"],
                              "nome": nome_lote(p["lote"], hoje=self.hoje), "usado_nesta_venda": p["lote_id"] in usados})
        return saida

    # ---------- texto ----------

    def lotes_saida(self, a, alocacao) -> list[dict]:
        """Cada lote da alocação com o que sobra nele depois (saldo da porção, reservado incluído)."""
        saida = []
        for lote, q in alocacao:
            validade = validade_porcao(lote, a.estado)
            saldo = saldo_lote(lote, a.estado)
            saida.append({"lote_id": lote.id, "codigo": lote.codigo or "sem lote", "nome": nome_lote(lote, hoje=self.hoje),
                          "dia_producao": dia_producao(lote), "validade": validade,
                          "vencido": vencida(validade, self.quando), "unidades": q,
                          "sobra": saldo - self.usado[(lote.id, a.estado)]})
        return saida

    def texto(self, a, unidades, lotes, falta) -> str:
        """"30 un de Coxinha cru congelado: 18 do lote do dia 8, que vence amanhã, e 12 do lote do dia 10; o lote
        do dia 8 zera e no lote do dia 10 sobram 28." """
        cabeca = f"{_n(unidades)} un de {a.produto.nome} {a.forma} {a.estado}"
        if not lotes:
            return f"{cabeca}: não há de onde pegar."
        partes = [f"{_n(l['unidades'])} do {l['nome']}{_vence(l['validade'], self.quando, self.hoje)}" for l in lotes]
        sobras = [f"o {l['nome']} zera" if l["sobra"] <= 0 else f"no {l['nome']} sobram {_n(l['sobra'])}"
                  for l in lotes]
        texto = f"{cabeca}: {_juntar(partes)}; {_juntar(sobras)}."
        if falta > 0:
            texto += f" Faltam {_n(falta)} un."
        return texto


def _avisos_linha(sep, a, unidades, lotes, falta, deixados) -> list[dict]:
    avisos = []
    for l in lotes:
        if l["vencido"] or l["validade"] is None:
            continue
        dias = (l["validade"] - sep.quando).days
        if dias in (0, 1):
            quando = "hoje" if dias == 0 else "amanhã"
            avisos.append({"tipo": "vence_hoje" if dias == 0 else "vence_amanha", "lote_id": l["lote_id"],
                           "texto": f"O {l['nome']} vence {quando} ({l['validade']:%d/%m})."})
    for d in deixados:
        avisos.append({"tipo": "deixado", "lote_id": d["lote_id"],
                       "texto": f"Ficaram {_n(d['unidades'])} un do {d['nome']}, que vencem em {d['validade']:%d/%m}: "
                                "venda esse primeiro."})
    if falta > 0:
        tem = unidades - falta
        avisos.append({"tipo": "falta", "texto": f"Faltam {_n(falta)} un de {a.produto.nome} {a.forma} {a.estado}: "
                                                  f"só há {_n(tem)} un livres e dentro da validade."})
        vencidas = [p for p in sep._candidatas(a) if p["vencido"] and sep.livre(p["lote"], a.estado) > 0]
        for p in vencidas:
            avisos.append({"tipo": "so_vencido", "lote_id": p["lote_id"], "precisa_motivo": True,
                           "texto": f"Há {_n(sep.livre(p['lote'], a.estado))} un no "
                                    f"{nome_lote(p['lote'], hoje=sep.hoje)}, vencido em {p['validade']:%d/%m}: só sai "
                                    "indicando o lote e um motivo."})
    return avisos


def separar_linha(sep, a, unidades, lotes_indicados=None, n_linha=1) -> dict:
    """Aloca uma linha (FEFO ou lotes indicados) e monta a instrução de separação dela."""
    avisos = []
    if lotes_indicados:
        alocacao, falta, avisos = sep.indicada(a, unidades, lotes_indicados, n_linha)
        deixados = sep.deixados(a, alocacao)
    else:
        alocacao, falta = sep.fefo(a, unidades)
        deixados = []
    lotes = sep.lotes_saida(a, alocacao)
    return {"apresentacao_id": a.id, "apresentacao": str(a), "produto_id": a.produto_id, "produto": a.produto.nome,
            "forma": a.forma, "estado": a.estado, "unidades": unidades, "lotes": lotes, "falta": falta,
            "lotes_indicados": bool(lotes_indicados), "deixados": deixados, "alocacao": alocacao,
            "texto": sep.texto(a, unidades, lotes, falta),
            "avisos": avisos + _avisos_linha(sep, a, unidades, lotes, falta, deixados)}


def _publica(linha) -> dict:
    return {k: v for k, v in linha.items() if k != "alocacao"}


def separacao_venda(*, itens, data_venda=None, motivo_vencido="", hoje=None) -> dict:
    """Instrução de separação (só leitura): de quais lotes pegar cada item, em ordem FEFO, julgando a validade
    no dia da venda. Com `lotes` num item ([{lote_id, unidades}]), mostra a separação indicada (o que faltar
    sai por FEFO) e o que ficou para trás. Vencido indicado sem `motivo_vencido` vira aviso `precisa_motivo`.

    Recusa (RegraViolada) o que a venda também recusaria: apresentação, quantidade, data, lote errado."""
    hoje = hoje or timezone.localdate()
    quando = dia_da_venda(data_venda, hoje=hoje)
    if not itens:
        raise RegraViolada("Informe ao menos um item.")
    sep = Separador(quando=quando, hoje=hoje, motivo_vencido=motivo_vencido, exigir_motivo=False)
    linhas = []
    for i, it in enumerate(itens, 1):
        a = Apresentacao.objects.select_related("produto").filter(id=it.get("apresentacao_id")).first()
        if a is None:
            raise RegraViolada(f"Item {i}: apresentação não encontrada.")
        qtd = _inteiro(it.get("quantidade"), f"item {i}")
        if qtd < 1:
            raise RegraViolada(f"Item {i}: a quantidade deve ser maior que zero.")
        linhas.append(_publica(separar_linha(sep, a, qtd * a.unidades, it.get("lotes"), i)))
    return _resultado(quando, linhas)


def _resultado(quando, linhas) -> dict:
    avisos = [a for l in linhas for a in l["avisos"]]
    return {"data_venda": quando, "linhas": linhas, "avisos": avisos,
            "completo": all(l["falta"] <= 0 for l in linhas),
            "precisa_motivo": any(a.get("precisa_motivo") and a["tipo"] == "vencido_sem_motivo" for a in avisos),
            "texto": " ".join(l["texto"] for l in linhas)}


def reservas_da_encomenda(e) -> dict:
    """{(lote_id, estado): unidades} reservadas (ativas) para a própria encomenda: podem sair na entrega dela."""
    saida = defaultdict(Decimal)
    for ie in e.itens.all():
        for r in ie.reservas.filter(situacao="ativa"):
            saida[(r.lote_id, r.estado)] += r.quantidade
    return dict(saida)


def separacao_encomenda(*, encomenda_id, data_entrega=None, lotes=None, motivo_vencido="", hoje=None) -> dict:
    """Instrução de separação da entrega (só leitura), a partir das reservas: de qual lote pegar cada item e o
    que sobra em cada um. `lotes` = [{item_encomenda_id, lotes: [{lote_id, unidades}]}] mostra a separação
    indicada. Avisa reserva vencida (para entregar dela, motivo; ou complete a reserva com outro lote) e o que
    falta reservar."""
    hoje = hoje or timezone.localdate()
    e = Encomenda.objects.select_related("cliente").filter(id=encomenda_id).first()
    if e is None:
        raise RegraViolada("Encomenda não encontrada.")
    if e.situacao != "aberta":
        raise RegraViolada(f"Esta encomenda já está {e.situacao}.")
    quando = dia_da_venda(data_entrega, "data_entrega", hoje=hoje)
    indicados = _indicados_por_item(lotes)
    sep = Separador(quando=quando, hoje=hoje, usar_reservas=reservas_da_encomenda(e), motivo_vencido=motivo_vencido,
                    exigir_motivo=False)
    linhas = []
    for ie in e.itens.select_related("apresentacao__produto"):
        a = ie.apresentacao
        if ie.id in indicados:
            linha = separar_linha(sep, a, ie.unidades, indicados[ie.id])
        else:
            linha = _linha_das_reservas(sep, ie)
        linhas.append({"item_encomenda_id": ie.id, **_publica(linha)})
    return {"encomenda_id": e.id, "cliente": str(e.cliente), **_resultado(quando, linhas)}


def _indicados_por_item(lotes) -> dict:
    saida = {}
    for x in lotes or []:
        try:
            saida[int(x.get("item_encomenda_id"))] = x.get("lotes") or []
        except (TypeError, ValueError):
            raise RegraViolada("Item da encomenda inválido nos lotes indicados.") from None
    return saida


def _linha_das_reservas(sep, ie) -> dict:
    """A entrega sem lote indicado baixa exatamente as reservas; aqui elas viram instrução de separação."""
    a = ie.apresentacao
    alocacao, avisos = [], []
    for r in ie.reservas.filter(situacao="ativa").select_related("lote__item").order_by("id"):
        validade = validade_porcao(r.lote, r.estado)
        if vencida(validade, sep.quando) and not sep.motivo_vencido:
            avisos.append({"tipo": "vencido_sem_motivo", "lote_id": r.lote_id, "precisa_motivo": True,
                           "texto": f"{texto_vencido(r.lote, r.estado, validade)} Complete a reserva com outro lote "
                                    "ou, para entregar dele mesmo assim, informe o motivo."})
        sep._lotes[r.lote_id] = r.lote
        sep._pegar(r.lote, r.estado, r.quantidade)
        alocacao.append((r.lote, r.quantidade))
    tem = sum((q for _, q in alocacao), ZERO)
    falta = max(Decimal(ie.unidades) - tem, ZERO)
    lotes = sep.lotes_saida(a, alocacao)
    if falta > 0:
        avisos.append({"tipo": "falta", "texto": f"Falta reservar {_n(falta)} un de {a.produto.nome} {a.forma} "
                                                  f"{a.estado}. Complete a reserva antes de entregar."})
    return {"apresentacao_id": a.id, "apresentacao": str(a), "produto_id": a.produto_id, "produto": a.produto.nome,
            "forma": a.forma, "estado": a.estado, "unidades": ie.unidades, "lotes": lotes, "falta": falta,
            "lotes_indicados": False, "deixados": [], "alocacao": alocacao,
            "texto": sep.texto(a, ie.unidades, lotes, falta),
            "avisos": avisos + [x for x in _avisos_linha(sep, a, ie.unidades, lotes, ZERO, []) if x["tipo"] != "falta"]}


# ---------- lotes deixados para trás (resumo e caixa de decisões) ----------

def lotes_deixados(*, hoje=None, dias_validade=3) -> list[dict]:
    """Porções que uma venda com lote indicado deixou para trás e que seguem esquecidas: ainda têm saldo, não
    venceram e ainda não entraram no aviso "vence logo" (até `dias_validade`), nem saiu nada delas depois
    daquela venda. Uma por porção, com a venda mais recente que a deixou."""
    from estoque.models import Movimento

    from .models import LinhaVenda

    hoje = hoje or timezone.localdate()
    limite = hoje + timedelta(days=dias_validade)
    vistos, saida = set(), []
    linhas = (LinhaVenda.objects.filter(lotes_indicados=True, venda__situacao="concluida").exclude(deixados=[])
              .select_related("venda", "apresentacao__produto").order_by("-venda__operacao_id", "-id"))
    for l in linhas:
        for d in l.deixados:
            porcao = (d["lote_id"], d["estado"])
            if porcao in vistos:
                continue
            vistos.add(porcao)
            lote = Lote.objects.select_related("item").filter(id=d["lote_id"]).first()
            validade = validade_porcao(lote, d["estado"])
            saldo = saldo_lote(lote, d["estado"])
            if saldo <= 0 or validade is None or validade <= limite:
                continue  # acabou, ou o aviso de validade (vencendo/vencido) já cobre
            saiu_depois = Movimento.objects.filter(lote=lote, estado=d["estado"], quantidade__lt=0,
                                                   operacao_id__gt=l.venda.operacao_id).exists()
            if saiu_depois:
                continue
            saida.append({"lote_id": lote.id, "estado": d["estado"], "item_id": lote.item_id, "item": lote.item.nome,
                          "codigo": lote.codigo or "sem lote", "nome": nome_lote(lote, hoje=hoje),
                          "dia_producao": dia_producao(lote), "validade": validade, "saldo": saldo,
                          "livre": saldo - reservado(lote=lote, estado=d["estado"]),
                          "venda_id": l.venda_id, "data_venda": l.venda.data})
    return sorted(saida, key=lambda x: (x["validade"], x["item"], x["lote_id"]))
