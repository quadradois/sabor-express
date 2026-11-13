from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import F, Min, Q, Sum
from django.utils import timezone

from cadastros.models import Item
from cadastros.unidades import fator
from nucleo.operacoes import RegraViolada, executar

from web.templatetags.formato import quantidade as fmt_qtd

from .models import ESTADOS, ConsumoPendente, CriterioValidade, Lote, Movimento


def saldo(item) -> Decimal:
    return Movimento.objects.filter(item=item).aggregate(s=Sum("quantidade"))["s"] or Decimal("0")


def saldo_lote(lote, estado: str = "") -> Decimal:
    return Movimento.objects.filter(lote=lote, estado=estado).aggregate(s=Sum("quantidade"))["s"] or Decimal("0")


def validade_porcao(lote, estado: str = ""):
    v = Movimento.objects.filter(lote=lote, estado=estado, quantidade__gt=0).aggregate(v=Min("validade"))["v"]
    return v or lote.validade


def alocar_fefo_parcial(item, quantidade: Decimal, *, hoje) -> tuple[list, Decimal]:
    """Como `alocar_fefo`, mas devolve (alocação, quanto faltou) em vez de recusar."""
    lotes = (Lote.objects.filter(item=item).exclude(validade__lt=hoje)
             .order_by(F("validade").asc(nulls_last=True), "criado_em", "id"))
    falta, saida = quantidade, []
    for l in lotes:
        if falta <= 0:
            break
        s = saldo_lote(l)
        if s <= 0:
            continue
        q = min(s, falta)
        saida.append((l, q))
        falta -= q
    return saida, max(falta, Decimal("0"))


def alocar_fefo(item, quantidade: Decimal, *, hoje) -> list:
    saida, falta = alocar_fefo_parcial(item, quantidade, hoje=hoje)
    if falta > 0:
        raise RegraViolada(f"Falta {fmt_qtd(falta, item.unidade_base)} de '{item.nome}' no estoque.")
    return saida


def porcoes(*, item=None, ate=None, hoje=None) -> list[dict]:
    """Porções com saldo (lote + conservação), da validade mais próxima para a mais longe.

    A validade da porção é a da entrada mais antiga nela (`validade_porcao`) ou a do lote.
    `ate` limita a validade (inclusive; porções sem validade ficam de fora). `valor` = saldo × custo do lote.
    """
    hoje = hoje or timezone.localdate()
    qs = Movimento.objects.all() if item is None else Movimento.objects.filter(item=item)
    grupos = (qs.values("lote", "estado")
              .annotate(s=Sum("quantidade"), v=Min("validade", filter=Q(quantidade__gt=0))).filter(s__gt=0))
    lotes = Lote.objects.select_related("item").in_bulk({g["lote"] for g in grupos})
    saida = []
    for g in grupos:
        l = lotes[g["lote"]]
        validade = g["v"] or l.validade
        if ate is not None and (validade is None or validade > ate):
            continue
        saida.append({
            "lote_id": l.id, "item_id": l.item_id, "item": l.item.nome, "unidade_base": l.item.unidade_base,
            "codigo": l.codigo or "sem lote", "estado": g["estado"], "validade": validade,
            "dias": None if validade is None else (validade - hoje).days,
            "vencido": validade is not None and validade < hoje, "saldo": g["s"],
            "valor": (g["s"] * l.custo_unitario).quantize(Decimal("0.01"), ROUND_HALF_UP),
        })
    saida.sort(key=lambda p: (p["validade"] is None, p["validade"] or hoje, p["item"], p["lote_id"]))
    return saida


def _reservas(**filtro):
    from vendas.models import Reserva  # vendas depende de estoque; aqui só se lê

    return Reserva.objects.filter(situacao="ativa", **filtro)


def reservado(*, item=None, lote=None, estado=None) -> Decimal:
    """Quanto está reservado para encomendas (reservas ativas), por item, lote ou porção (lote + estado)."""
    filtro = {}
    if item is not None:
        filtro["lote__item"] = item
    if lote is not None:
        filtro["lote"] = lote
    if estado is not None:
        filtro["estado"] = estado
    return _reservas(**filtro).aggregate(s=Sum("quantidade"))["s"] or Decimal("0")


def livre_porcao(lote, estado: str = "") -> Decimal:
    """Saldo da porção que não está reservado: o que venda, fritura, perda e transferência podem usar."""
    return saldo_lote(lote, estado) - reservado(lote=lote, estado=estado)


def disponivel(item, *, hoje=None) -> Decimal:
    """Disponível (RN-03) = saldo − reservado − vencido. A reserva em porção vencida não conta duas vezes
    (o vencido já saiu inteiro); a pendência de recebimento nunca está no saldo."""
    hoje = hoje or timezone.localdate()
    vencidas = porcoes(item=item, ate=hoje - timedelta(days=1), hoje=hoje)
    vencido = sum((p["saldo"] for p in vencidas), Decimal("0"))
    fora = {(p["lote_id"], p["estado"]) for p in vencidas}
    reserva = sum((r.quantidade for r in _reservas(lote__item=item) if (r.lote_id, r.estado) not in fora),
                  Decimal("0"))
    return saldo(item) - vencido - reserva


def alocar_porcoes(item, quantidade: Decimal, *, forma: str, estado: str, hoje, valida_ate=None,
                   usar_reservas=None) -> tuple[list, Decimal]:
    """FEFO por porção (RN-18) para produto vendido ou reservado: só lotes da `forma`, porções no `estado`,
    sem vencido (nem o que vence antes de `valida_ate`) e sem o reservado para outras encomendas.
    `usar_reservas` = {(lote_id, estado): quantidade} que pode ser usado mesmo reservado (as da própria
    encomenda). Devolve ([(lote, quantidade)], quanto faltou)."""
    limite = max(hoje, valida_ate or hoje)
    usar_reservas = usar_reservas or {}
    lotes = Lote.objects.filter(item=item, forma=forma).in_bulk()
    falta, saida = quantidade, []
    for p in porcoes(item=item, hoje=hoje):
        if falta <= 0:
            break
        if p["estado"] != estado or p["lote_id"] not in lotes or (p["validade"] and p["validade"] < limite):
            continue
        lote = lotes[p["lote_id"]]
        livre = livre_porcao(lote, estado) + usar_reservas.get((lote.id, estado), Decimal("0"))
        if livre <= 0:
            continue
        q = min(livre, falta)
        saida.append((lote, q))
        falta -= q
    return saida, max(falta, Decimal("0"))


def itens_abaixo_do_minimo(*, hoje=None) -> list[dict]:
    """Itens ativos com estoque mínimo e disponível abaixo dele (PRD: estoque baixo), do que mais falta."""
    saida = []
    for i in Item.objects.filter(ativo=True, estoque_minimo__gt=0).order_by("nome"):
        d = disponivel(i, hoje=hoje)
        if d < i.estoque_minimo:
            saida.append({"item_id": i.id, "item": i.nome, "tipo": i.tipo, "unidade_base": i.unidade_base,
                          "disponivel": d, "minimo": i.estoque_minimo, "falta": i.estoque_minimo - d})
    return sorted(saida, key=lambda x: (-(x["falta"] / x["minimo"]), x["item"]))


def consumos_pendentes(*, item_id=None, abertos=True) -> list[dict]:
    """Consumos sem saldo à espera de conciliação (RF-EST-04), com os lotes que podem cobri-los."""
    hoje = timezone.localdate()
    qs = ConsumoPendente.objects.select_related("item", "lote").order_by("criado_em", "id")
    if abertos:
        qs = qs.filter(lote__isnull=True)
    if item_id:
        qs = qs.filter(item_id=item_id)
    saida = []
    for p in qs:
        candidatos = [] if not p.aberto else [
            {"lote_id": l.id, "codigo": l.codigo or "sem lote", "validade": l.validade, "saldo": s,
             "custo_unitario": l.custo_unitario}
            for l in Lote.objects.filter(item=p.item).exclude(validade__lt=hoje).order_by(
                F("validade").asc(nulls_last=True), "criado_em", "id")
            if (s := saldo_lote(l)) >= p.quantidade]
        saida.append({"pendente_id": p.id, "item_id": p.item_id, "item": p.item.nome,
                      "unidade_base": p.item.unidade_base, "quantidade": p.quantidade,
                      "justificativa": p.justificativa, "producao_id": p.producao_id, "criado_em": p.criado_em,
                      "lote_id": p.lote_id, "custo": p.custo, "lotes_possiveis": candidatos})
    return saida


def entrada_manual(*, item_id, quantidade, unidade, custo_total, motivo, lote_codigo="",
                   validade=None, autor, canal="web", chave=None) -> dict:
    parametros = {"item_id": item_id, "quantidade": quantidade, "unidade": unidade,
                  "custo_total": custo_total, "motivo": motivo, "lote_codigo": lote_codigo,
                  "validade": validade}

    def func(op):
        # validações dentro de executar: recusa também fica na trilha (status "erro")
        texto_motivo = (motivo or "").strip()
        if not texto_motivo:
            raise RegraViolada("Informe o motivo da entrada.")
        if quantidade <= 0:
            raise RegraViolada("A quantidade deve ser maior que zero.")
        try:
            item = Item.objects.get(id=item_id)
        except Item.DoesNotExist:
            raise RegraViolada("Item não encontrado.")
        if item.controla_validade and not validade:
            raise RegraViolada(f"Informe a validade de '{item.nome}'.")
        if custo_total < 0:
            raise RegraViolada("O custo total não pode ser negativo.")
        un, f = fator(item, unidade)
        qtd = (quantidade * f).quantize(Decimal("0.001"), ROUND_HALF_UP)
        if qtd <= 0:
            raise RegraViolada("A quantidade deve ser maior que zero.")
        custo = (custo_total / qtd).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        codigo = (lote_codigo or "").strip()
        lote = Lote.objects.create(item=item, codigo=codigo, sem_lote=not codigo,
                                   validade=validade, custo_unitario=custo)
        Movimento.objects.create(tipo="entrada_manual", item=item, lote=lote, quantidade=qtd,
                                 quantidade_informada=quantidade, unidade_informada=un, fator=f,
                                 motivo=texto_motivo, validade=validade, operacao=op)
        return {"lote_id": lote.id, "quantidade_base": qtd}

    return executar("entrada_manual", func, autor=autor, canal=canal, chave=chave,
                    parametros=parametros)


def calcular_validade(produto, forma: str, estado: str, *, hoje, manual, justificativa: str):
    c = CriterioValidade.objects.filter(produto=produto, forma=forma, estado=estado).first()
    if c:
        return hoje + timedelta(days=c.dias), False
    if not manual:
        raise RegraViolada(f"Sem critério de validade para '{produto.nome}' {forma} {estado}: informe a validade.")
    if not (justificativa or "").strip():
        raise RegraViolada("Justifique a validade informada.")
    return manual, True


def transferir_estado(*, lote_id, quantidade, de, para, validade_manual=None, justificativa="",
                      autor, canal="web", chave=None) -> dict:
    parametros = {"lote_id": lote_id, "quantidade": quantidade, "de": de, "para": para,
                  "validade_manual": validade_manual, "justificativa": justificativa}

    def func(op):
        hoje = timezone.localdate()
        if quantidade <= 0:
            raise RegraViolada("A quantidade deve ser maior que zero.")
        if de == para:
            raise RegraViolada("Os estados de origem e destino devem ser diferentes.")
        if {de, para} - {e for e, _ in ESTADOS}:
            raise RegraViolada("Estado inválido.")
        try:
            lote = Lote.objects.select_related("item").get(id=lote_id)
        except Lote.DoesNotExist:
            raise RegraViolada("Lote não encontrado.")
        v = validade_porcao(lote, de)
        if v and v < hoje:
            raise RegraViolada("Lote vencido só aceita descarte.")
        if quantidade > saldo_lote(lote, de):
            raise RegraViolada(f"Só há {fmt_qtd(saldo_lote(lote, de), lote.item.unidade_base)} em {de}.")
        if quantidade > livre_porcao(lote, de):
            raise RegraViolada(f"Só {fmt_qtd(livre_porcao(lote, de), lote.item.unidade_base)} em {de} não estão "
                               "reservadas para encomendas.")
        nova, manual = calcular_validade(lote.item, lote.forma, para, hoje=hoje, manual=validade_manual,
                                         justificativa=justificativa)
        for estado, q, val, man in ((de, -quantidade, None, False), (para, quantidade, nova, manual)):
            Movimento.objects.create(tipo="transferencia_estado", item=lote.item, lote=lote, quantidade=q,
                                     quantidade_informada=q, unidade_informada="un", fator=Decimal("1"),
                                     motivo=f"{de} → {para}", estado=estado, validade=val,
                                     validade_manual=man, operacao=op)
        return {"lote_id": lote.id, "validade": nova.isoformat(), "validade_manual": manual}

    return executar("transferir_estado", func, autor=autor, canal=canal, chave=chave, parametros=parametros)


def registrar_perda(*, lote_id, estado="", quantidade, unidade="", motivo, autor, canal="web", chave=None) -> dict:
    """Baixa com motivo (RF-EST-02 perda/descarte): sobra de frito, quebra, vencido (RF-EST-10, RN-19).

    Não passa do saldo da porção. Fora do vencido, não toca no reservado; descartar porção vencida
    libera as reservas dela (FL-07 A3: o sistema avisa para reservar de outro lote).
    `quantidade` na `unidade` informada (padrão: a unidade base do item)."""
    parametros = {"lote_id": lote_id, "estado": estado, "quantidade": quantidade, "unidade": unidade,
                  "motivo": motivo}

    def func(op):
        from nucleo.valores import decimal

        texto = (motivo or "").strip()
        if not texto:
            raise RegraViolada("Informe o motivo da perda.")
        lote = Lote.objects.select_related("item").filter(id=lote_id).first()
        if lote is None:
            raise RegraViolada("Lote não encontrado.")
        un, f = fator(lote.item, unidade or lote.item.unidade_base)
        qtd = (decimal(quantidade, "quantidade") * f).quantize(Decimal("0.001"), ROUND_HALF_UP)
        if qtd <= 0:
            raise RegraViolada("A quantidade deve ser maior que zero.")
        base = lote.item.unidade_base
        tem = saldo_lote(lote, estado)
        if qtd > tem:
            raise RegraViolada(f"Só há {fmt_qtd(tem, base)} de '{lote.item.nome}' nessa porção.")
        v = validade_porcao(lote, estado)
        vencido = v is not None and v < timezone.localdate()
        liberadas = []
        if vencido:
            for r in _reservas(lote=lote, estado=estado):
                r.situacao, r.fim_operacao, r.motivo = "liberada", op, "lote vencido descartado"
                r.save(update_fields=["situacao", "fim_operacao", "motivo"])
                liberadas.append(r.id)
        elif qtd > livre_porcao(lote, estado):
            raise RegraViolada(f"Só {fmt_qtd(livre_porcao(lote, estado), base)} não estão reservadas para "
                               "encomendas. Cancele a encomenda antes de dar a perda.")
        m = Movimento.objects.create(tipo="perda", item=lote.item, lote=lote, quantidade=-qtd,
                                     quantidade_informada=decimal(quantidade, "quantidade"), unidade_informada=un,
                                     fator=f, motivo=texto, estado=estado, operacao=op)
        return {"movimento_id": m.id, "lote_id": lote.id, "item": lote.item.nome, "quantidade": qtd,
                "unidade_base": base, "vencido": vencido, "reservas_liberadas": liberadas,
                "valor": (qtd * lote.custo_unitario).quantize(Decimal("0.01"), ROUND_HALF_UP),
                "saldo": saldo_lote(lote, estado)}

    return executar("registrar_perda", func, autor=autor, canal=canal, chave=chave, parametros=parametros)
