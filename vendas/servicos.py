"""Apresentações com preço, venda direta, encomenda com reserva e entrega (PRD §7.10, FL-06/07/09).

Toda gravação passa pelo `executar()`. A venda baixa o estoque pelo que vence primeiro (FEFO por porção,
RN-18), sem tocar no que está reservado (RN-35) nem no vencido (RN-19). A encomenda reserva ao ser criada
e vira venda na entrega, uma única vez. Preço, fator e custo ficam gravados na linha (RN-30).
O sistema nunca cobra: venda a prazo e saldo de encomenda a prazo viram conta a receber (anotação).
"""

from datetime import time
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.utils import timezone

from cadastros.models import Cliente, Item
from cadastros.servicos import _normal
from estoque.models import ESTADOS, FORMAS, Lote, Movimento
from estoque.servicos import alocar_fefo, alocar_porcoes, saldo_lote, validade_porcao
from financeiro.servicos import abrir_conta_receber, cancelar_conta_da_venda
from nucleo.operacoes import RegraViolada, _json, executar
from nucleo.valores import CENTAVO, data, decimal, reais
from web.templatetags.formato import dinheiro
from web.templatetags.formato import quantidade as fmt_qtd

from .models import CONDICOES, DESTINOS, MODOS, TABELAS, Apresentacao, CanalVenda, Encomenda, ItemEncomenda, LinhaVenda, Reserva, Venda


def _inteiro(v, campo) -> int:
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        raise RegraViolada(f"Valor inválido em '{campo}' (use um número inteiro).") from None
    return n


def _rs(v) -> Decimal:
    return Decimal(v).quantize(CENTAVO, ROUND_HALF_UP)


def _un(q) -> str:
    return fmt_qtd(q, "un")


# ---------- canais de venda (taxas do estudo de preço, Plano 8) ----------

def salvar_canal_venda(*, nome, taxa_pct=None, ativo=True, canal_id=None, autor, canal="web", chave=None) -> dict:
    """Cria ou altera um canal de venda e a taxa que ele cobra (% do preço; vazio = não informada).
    Só pela tela, como o preço."""

    def func(op):
        n = (nome or "").strip()
        if not n:
            raise RegraViolada("Informe o nome do canal.")
        taxa = None if taxa_pct in (None, "") else decimal(taxa_pct, "taxa_pct").quantize(CENTAVO, ROUND_HALF_UP)
        if taxa is not None and not 0 <= taxa < 100:
            raise RegraViolada("A taxa vai de 0% a menos de 100%.")
        if any(_normal(c.nome) == _normal(n) for c in CanalVenda.objects.exclude(id=canal_id)):
            raise RegraViolada(f"Já existe o canal '{n}'.")
        if canal_id is None:
            c = CanalVenda(ordem=CanalVenda.objects.count() + 1)
        else:
            c = CanalVenda.objects.filter(id=canal_id).first()
            if c is None:
                raise RegraViolada("Canal não encontrado.")
        c.nome, c.taxa_pct, c.ativo = n, taxa, bool(ativo)
        c.save()
        return {"canal_id": c.id, "nome": c.nome, "taxa_pct": c.taxa_pct}

    return executar("salvar_canal_venda", func, autor=autor, canal=canal, chave=chave,
                    parametros={"canal_id": canal_id, "nome": nome, "taxa_pct": taxa_pct, "ativo": ativo})


# ---------- apresentações (preços) ----------

def salvar_apresentacao(*, produto_id, nome, forma, estado, unidades, preco_varejo, preco_atacado=None,
                        embalagem_id=None, embalagens=0, ativo=True, apresentacao_id=None,
                        autor, canal="web", chave=None) -> dict:
    """Cria ou altera como um produto é vendido e por quanto (RF-CAD-04). Mudar o preço não muda vendas
    já feitas (RN-30). Apresentação já vendida ou encomendada não muda de forma, conservação nem de
    unidades (crie outra); pode mudar nome, preço, embalagem e ser inativada."""
    parametros = {"apresentacao_id": apresentacao_id, "produto_id": produto_id, "nome": nome, "forma": forma,
                  "estado": estado, "unidades": unidades, "preco_varejo": preco_varejo,
                  "preco_atacado": preco_atacado, "embalagem_id": embalagem_id, "embalagens": embalagens,
                  "ativo": ativo}

    def func(op):
        produto = Item.objects.filter(id=produto_id, tipo="produto").first()
        if produto is None:
            raise RegraViolada("Escolha um produto (salgado de um tamanho).")
        n = (nome or "").strip()
        if not n:
            raise RegraViolada("Dê um nome à apresentação (ex.: unidade, caixa com 25, cento).")
        if forma not in dict(FORMAS):
            raise RegraViolada("Escolha a forma: cru ou frito.")
        if estado not in dict(ESTADOS):
            raise RegraViolada("Escolha a conservação: fresco, resfriado ou congelado.")
        un = _inteiro(unidades, "unidades")
        if un < 1:
            raise RegraViolada("A apresentação precisa ter ao menos 1 unidade.")
        varejo = reais(preco_varejo, "preco_varejo")
        if varejo <= 0:
            raise RegraViolada("Informe o preço de varejo.")
        atacado = None if preco_atacado in (None, "") else reais(preco_atacado, "preco_atacado")
        if atacado is not None and atacado <= 0:
            raise RegraViolada("O preço de atacado deve ser maior que zero (ou deixe em branco).")
        emb, q_emb = None, decimal(embalagens or 0, "embalagens")
        if embalagem_id:
            emb = Item.objects.filter(id=embalagem_id, tipo="embalagem").first()
            if emb is None:
                raise RegraViolada("Escolha uma embalagem cadastrada.")
            if q_emb <= 0:
                raise RegraViolada("Informe quantas embalagens vão em cada apresentação.")
        else:
            q_emb = Decimal("0")
        outras = Apresentacao.objects.filter(produto=produto).exclude(id=apresentacao_id)
        if any(_normal(a.nome) == _normal(n) for a in outras):
            raise RegraViolada(f"'{produto.nome}' já tem a apresentação '{n}'.")
        if apresentacao_id is None:
            a = Apresentacao(produto=produto)
        else:
            a = Apresentacao.objects.filter(id=apresentacao_id).first()
            if a is None:
                raise RegraViolada("Apresentação não encontrada.")
            usada = (LinhaVenda.objects.filter(apresentacao=a).exists()
                     or ItemEncomenda.objects.filter(apresentacao=a).exists())
            if usada and (a.produto_id != produto.id or a.forma != forma or a.estado != estado or a.unidades != un):
                raise RegraViolada("Esta apresentação já foi vendida: produto, forma, conservação e unidades não "
                                   "mudam. Crie outra apresentação e inative esta.")
        a.produto, a.nome, a.forma, a.estado, a.unidades = produto, n, forma, estado, un
        a.preco_varejo, a.preco_atacado, a.embalagem, a.embalagens, a.ativo = varejo, atacado, emb, q_emb, bool(ativo)
        a.save()
        return {"apresentacao_id": a.id, "nome": str(a)}

    return executar("salvar_apresentacao", func, autor=autor, canal=canal, chave=chave, parametros=parametros)


def _preco(a, tabela) -> Decimal:
    if tabela == "atacado":
        if a.preco_atacado is None:
            raise RegraViolada(f"'{a}' não tem preço de atacado.")
        return a.preco_atacado
    return a.preco_varejo


def _ler_itens(itens, tabela) -> list[dict]:
    """[{apresentacao_id, quantidade, preco?}] → linhas com preço de tabela e praticado (desconto manual,
    RF-VEN-01: o original fica gravado)."""
    if tabela not in dict(TABELAS):
        raise RegraViolada("Escolha a tabela: varejo ou atacado.")
    if not itens:
        raise RegraViolada("Informe ao menos um item.")
    lidas = []
    for i, it in enumerate(itens, 1):
        a = (Apresentacao.objects.select_related("produto", "embalagem")
             .filter(id=it.get("apresentacao_id")).first())
        if a is None:
            raise RegraViolada(f"Item {i}: apresentação não encontrada.")
        if not a.ativo or not a.produto.ativo:
            raise RegraViolada(f"'{a}' está inativa.")
        qtd = _inteiro(it.get("quantidade"), f"item {i}")
        if qtd < 1:
            raise RegraViolada(f"Item {i}: a quantidade deve ser maior que zero.")
        tab = _preco(a, tabela)
        preco = tab if it.get("preco") in (None, "") else reais(it.get("preco"), f"item {i}")
        if preco < 0:
            raise RegraViolada(f"Item {i}: o preço não pode ser negativo.")
        lidas.append({"apresentacao": a, "quantidade": qtd, "unidades": qtd * a.unidades, "preco_tabela": tab,
                      "preco": preco, "total": _rs(preco * qtd)})
    return lidas


# ---------- baixa de estoque (dentro de executar) ----------

def _baixar(op, lote, estado, q, motivo) -> dict:
    Movimento.objects.create(tipo="saida_venda", item=lote.item, lote=lote, quantidade=-q, quantidade_informada=q,
                             unidade_informada=lote.item.unidade_base, fator=Decimal("1"), motivo=motivo,
                             estado=estado, operacao=op)
    return {"lote_id": lote.id, "item_id": lote.item_id, "estado": estado, "quantidade": q,
            "custo": _rs(q * lote.custo_unitario)}


def _baixar_embalagens(op, a, quantidade, motivo, hoje) -> list[dict]:
    if not a.embalagem_id or a.embalagens <= 0:
        return []
    q = (a.embalagens * quantidade).quantize(Decimal("0.001"), ROUND_HALF_UP)
    return [_baixar(op, lote, "", x, motivo) for lote, x in alocar_fefo(a.embalagem, q, hoje=hoje)]


def _falta_produto(a, unidades, falta) -> RegraViolada:
    tem = unidades - falta
    return RegraViolada(f"Só há {_un(tem)} de '{a.produto.nome}' {a.forma} {a.estado} para vender "
                        f"(pedido: {_un(unidades)}). O resto está reservado, vencido ou não existe.")


def _cliente(cliente_id, obrigatorio_msg=None):
    if cliente_id in (None, ""):
        if obrigatorio_msg:
            raise RegraViolada(obrigatorio_msg)
        return None
    c = Cliente.objects.filter(id=cliente_id).first()
    if c is None:
        raise RegraViolada("Cliente não encontrado.")
    if not c.ativo:
        raise RegraViolada(f"O cliente '{c.nome}' está inativo.")
    return c


def _condicao(condicao):
    if condicao not in dict(CONDICOES):
        raise RegraViolada("Escolha a condição: à vista ou a prazo.")


def _parcelas_saida(conta):
    if conta is None:
        return None, []
    return conta.id, [{"parcela_id": p.id, "valor": p.valor, "vencimento": p.vencimento}
                      for p in conta.parcelas.order_by("numero")]


def _linhas_saida(venda):
    return [{"apresentacao_id": l.apresentacao_id, "apresentacao": str(l.apresentacao), "quantidade": l.quantidade,
             "unidades": l.quantidade * l.unidades_por, "preco": l.preco, "preco_tabela": l.preco_tabela,
             "total": l.total} for l in venda.linhas.select_related("apresentacao__produto")]


# ---------- venda direta ----------

def registrar_venda(*, itens, tabela="varejo", cliente_id=None, condicao="a_vista", forma_pagamento="",
                    parcelas=None, data_venda=None, autor, canal="web", chave=None) -> dict:
    """Venda de balcão ou atacado (RF-VEN-01 a 04, FL-06): baixa cada apresentação em unidades do produto
    (FEFO pela porção na forma e conservação da apresentação, fora o reservado e o vencido) e as embalagens.
    Faltando estoque, recusa sem gravar (venda não aceita consumo pendente). À vista: entra na hora.
    A prazo: precisa do cliente e das parcelas (soma = total) e vira conta a receber."""
    parametros = {"itens": itens, "tabela": tabela, "cliente_id": cliente_id, "condicao": condicao,
                  "forma_pagamento": forma_pagamento, "parcelas": parcelas, "data_venda": data_venda}

    def func(op):
        _condicao(condicao)
        cliente = _cliente(cliente_id, "Venda a prazo precisa do cliente." if condicao == "a_prazo" else None)
        hoje = timezone.localdate()
        quando = data(data_venda, "data_venda") or hoje
        lidas = _ler_itens(itens, tabela)
        total = sum((l["total"] for l in lidas), Decimal("0"))
        v = Venda.objects.create(cliente=cliente, data=quando, tabela=tabela, condicao=condicao,
                                 forma_pagamento=(forma_pagamento or "").strip(), total=total, custo=0,
                                 recebido_na_hora=total if condicao == "a_vista" else 0, operacao=op)
        motivo, custo = f"Venda {v.id}", Decimal("0")
        for l in lidas:
            a = l["apresentacao"]
            alocacao, falta = alocar_porcoes(a.produto, Decimal(l["unidades"]), forma=a.forma, estado=a.estado,
                                             hoje=hoje)
            if falta > 0:
                raise _falta_produto(a, l["unidades"], falta)
            baixas = [_baixar(op, lote, a.estado, q, motivo) for lote, q in alocacao]
            baixas += _baixar_embalagens(op, a, l["quantidade"], motivo, hoje)
            c = sum((b["custo"] for b in baixas), Decimal("0"))
            custo += c
            LinhaVenda.objects.create(venda=v, apresentacao=a, quantidade=l["quantidade"], unidades_por=a.unidades,
                                      preco_tabela=l["preco_tabela"], preco=l["preco"], total=l["total"], custo=c,
                                      baixas=_json(baixas))
        v.custo = custo
        v.save(update_fields=["custo"])
        conta = None
        if condicao == "a_prazo":
            conta = abrir_conta_receber(op, venda=v, total=total, parcelas=parcelas,
                                        descricao=f"Venda {v.id} — {cliente}")
        conta_id, parc = _parcelas_saida(conta)
        return {"venda_id": v.id, "cliente": str(cliente or ""), "condicao": condicao, "total": total,
                "custo": custo, "recebido_na_hora": v.recebido_na_hora, "conta_id": conta_id, "parcelas": parc,
                "linhas": _linhas_saida(v)}

    return executar("registrar_venda", func, autor=autor, canal=canal, chave=chave, parametros=parametros)


def cancelar_venda(*, venda_id, motivo, destino="perda", autor, canal="web", chave=None) -> dict:
    """Cancela ou registra a devolução total de uma venda (RF-VEN-09/10, FL-09). As unidades vão para perda
    por padrão (RN-36); com `destino="estoque"` voltam aos lotes de origem, se a porção não venceu
    (embalagens não voltam). O recebível em aberto é cancelado; o que o cliente já pagou (à vista, sinal
    e recebimentos) fica anotado em `valor_devolvido`."""
    parametros = {"venda_id": venda_id, "motivo": motivo, "destino": destino}

    def func(op):
        v = Venda.objects.select_related("encomenda").filter(id=venda_id).first()
        if v is None:
            raise RegraViolada("Venda não encontrada.")
        if v.situacao == "cancelada":
            raise RegraViolada("Esta venda já foi cancelada.")
        texto = (motivo or "").strip()
        if not texto:
            raise RegraViolada("Informe o motivo do cancelamento.")
        if destino not in dict(DESTINOS):
            raise RegraViolada("Escolha o destino das unidades: perda ou volta ao estoque.")
        hoje, devolvidas = timezone.localdate(), Decimal("0")
        if destino == "estoque":
            for l in v.linhas.select_related("apresentacao"):
                for b in l.baixas:
                    if b["item_id"] != l.apresentacao.produto_id:
                        continue  # embalagem usada não volta
                    lote = Lote.objects.select_related("item").get(id=b["lote_id"])
                    validade = validade_porcao(lote, b["estado"])
                    if validade and validade < hoje:
                        raise RegraViolada(f"O lote {lote.codigo or 'sem lote'} de '{lote.item.nome}' venceu: "
                                           "a devolução vai para perda (RN-36).")
                    q = Decimal(b["quantidade"])
                    Movimento.objects.create(tipo="devolucao_cliente", item=lote.item, lote=lote, quantidade=q,
                                             quantidade_informada=q, unidade_informada="un", fator=Decimal("1"),
                                             motivo=f"Devolução da venda {v.id}: {texto}", estado=b["estado"],
                                             validade=validade, operacao=op)
                    devolvidas += q
        recebido = Decimal("0")
        conta = getattr(v, "conta", None)
        if conta is not None and not conta.cancelada:
            recebido = cancelar_conta_da_venda(op, conta, f"Venda {v.id} cancelada: {texto}")
        sinal = v.encomenda.sinal if v.encomenda_id else Decimal("0")
        v.situacao, v.cancelamento_operacao, v.motivo_cancelamento, v.destino = "cancelada", op, texto, destino
        v.valor_devolvido = v.recebido_na_hora + recebido + sinal
        v.save(update_fields=["situacao", "cancelamento_operacao", "motivo_cancelamento", "destino",
                              "valor_devolvido"])
        return {"venda_id": v.id, "destino": destino, "unidades_devolvidas": devolvidas,
                "valor_devolvido": v.valor_devolvido, "conta_cancelada": conta is not None}

    return executar("cancelar_venda", func, autor=autor, canal=canal, chave=chave, parametros=parametros)


# ---------- encomendas ----------

def _hora(v):
    if v in (None, ""):
        return None
    if isinstance(v, time):
        return v
    try:
        return time.fromisoformat(str(v))
    except ValueError:
        raise RegraViolada("Hora inválida (use HH:MM).") from None


def _reservar(op, ie, hoje) -> Decimal:
    """Reserva o que falta do item da encomenda (FEFO, só porções que valem até o dia da entrega).
    Devolve quanto ainda falta."""
    a = ie.apresentacao
    ja = ie.reservas.filter(situacao="ativa").aggregate(s=Sum("quantidade"))["s"] or Decimal("0")
    falta = Decimal(ie.unidades) - ja
    if falta <= 0:
        return Decimal("0")
    alocacao, falta = alocar_porcoes(a.produto, falta, forma=a.forma, estado=a.estado, hoje=hoje,
                                     valida_ate=ie.encomenda.entrega_data)
    for lote, q in alocacao:
        Reserva.objects.create(item_encomenda=ie, lote=lote, estado=a.estado, quantidade=q, operacao=op)
    return falta


def _liberar(op, reservas, motivo) -> list[int]:
    ids = []
    for r in reservas:
        r.situacao, r.fim_operacao, r.motivo = "liberada", op, motivo
        r.save(update_fields=["situacao", "fim_operacao", "motivo"])
        ids.append(r.id)
    return ids


def _itens_saida(e) -> list[dict]:
    saida = []
    for ie in e.itens.select_related("apresentacao__produto"):
        res = ie.reservas.filter(situacao__in=("ativa", "baixada")).aggregate(s=Sum("quantidade"))["s"] or 0
        saida.append({"item_encomenda_id": ie.id, "apresentacao_id": ie.apresentacao_id,
                      "apresentacao": str(ie.apresentacao), "quantidade": ie.quantidade, "unidades": ie.unidades,
                      "preco": ie.preco, "total": ie.total, "reservado": Decimal(res),
                      "falta": max(Decimal(ie.unidades) - Decimal(res), Decimal("0"))})
    return saida


def _resposta_encomenda(e) -> dict:
    itens = _itens_saida(e)
    falta = sum((i["falta"] for i in itens), Decimal("0"))
    situacao = e.situacao if e.situacao != "aberta" else ("pronta" if falta == 0 else "aberta")
    return {"encomenda_id": e.id, "cliente": str(e.cliente), "entrega_data": e.entrega_data,
            "entrega_hora": e.entrega_hora, "situacao": situacao, "total": e.total, "sinal": e.sinal,
            "saldo": e.total - e.sinal, "falta": falta, "itens": itens}


def _aberta(encomenda_id, lock=False) -> Encomenda:
    qs = Encomenda.objects.select_related("cliente")
    e = (qs.select_for_update() if lock else qs).filter(id=encomenda_id).first()
    if e is None:
        raise RegraViolada("Encomenda não encontrada.")
    if e.situacao == "entregue":
        raise RegraViolada(f"Esta encomenda já foi entregue (venda {e.venda.id}).")
    if e.situacao == "cancelada":
        raise RegraViolada("Esta encomenda foi cancelada.")
    return e


def criar_encomenda(*, cliente_id, entrega_data, itens, entrega_hora=None, tabela="varejo", modo="retirada",
                    observacao="", sinal=0, sinal_forma="", autor, canal="web", chave=None) -> dict:
    """Encomenda confirmada (RF-VEN-05/06, FL-07): preços gravados agora; reserva o que houver de cada item
    (porções na forma e conservação pedidas que valem até o dia da entrega) e devolve o que falta.
    Nenhuma produção é criada (DEC-F2-019). O sinal é anotado (não pode passar do total)."""
    parametros = {"cliente_id": cliente_id, "entrega_data": entrega_data, "entrega_hora": entrega_hora,
                  "itens": itens, "tabela": tabela, "modo": modo, "observacao": observacao, "sinal": sinal,
                  "sinal_forma": sinal_forma}

    def func(op):
        cliente = _cliente(cliente_id, "Encomenda precisa do cliente.")
        hoje = timezone.localdate()
        dia = data(entrega_data, "entrega_data")
        if dia is None:
            raise RegraViolada("Informe o dia da entrega ou retirada.")
        if dia < hoje:
            raise RegraViolada("O dia da entrega já passou.")
        if modo not in dict(MODOS):
            raise RegraViolada("Escolha entrega ou retirada.")
        lidas = _ler_itens(itens, tabela)
        total = sum((l["total"] for l in lidas), Decimal("0"))
        s = reais(sinal or 0, "sinal")
        if s < 0 or s > total:
            raise RegraViolada(f"O sinal deve ficar entre zero e o total ({dinheiro(total)}).")
        e = Encomenda.objects.create(cliente=cliente, entrega_data=dia, entrega_hora=_hora(entrega_hora), modo=modo,
                                     observacao=(observacao or "").strip(), tabela=tabela, total=total, sinal=s,
                                     sinal_forma=(sinal_forma or "").strip() if s else "", operacao=op)
        for l in lidas:
            ie = ItemEncomenda.objects.create(encomenda=e, apresentacao=l["apresentacao"], quantidade=l["quantidade"],
                                              unidades_por=l["apresentacao"].unidades, preco_tabela=l["preco_tabela"],
                                              preco=l["preco"], total=l["total"])
            _reservar(op, ie, hoje)
        return _resposta_encomenda(e)

    return executar("criar_encomenda", func, autor=autor, canal=canal, chave=chave, parametros=parametros)


def completar_reserva(*, encomenda_id, autor, canal="web", chave=None) -> dict:
    """Completa a reserva quando entrou estoque (RF-VEN-07: com confirmação, nunca sozinho). Antes, libera
    as reservas em porções que vencem antes da entrega (FL-07 A3) para reservar de outro lote."""

    def func(op):
        e = _aberta(encomenda_id, lock=True)
        hoje = timezone.localdate()
        limite = max(hoje, e.entrega_data)
        liberadas = []
        for ie in e.itens.select_related("apresentacao__produto"):
            ruins = [r for r in ie.reservas.filter(situacao="ativa").select_related("lote")
                     if (v := validade_porcao(r.lote, r.estado)) and v < limite]
            liberadas += _liberar(op, ruins, "lote vence antes da entrega")
            _reservar(op, ie, hoje)
        return {**_resposta_encomenda(e), "reservas_liberadas": liberadas}

    return executar("completar_reserva", func, autor=autor, canal=canal, chave=chave,
                    parametros={"encomenda_id": encomenda_id})


def cancelar_encomenda(*, encomenda_id, motivo, devolver_sinal=True, autor, canal="web", chave=None) -> dict:
    """Cancela antes da entrega (RF-VEN-09, RN-35): libera as reservas; nada sai do estoque. O sinal fica
    anotado como devolvido (ou retido, com `devolver_sinal=False`). Depois de entregue, cancela-se a venda."""
    parametros = {"encomenda_id": encomenda_id, "motivo": motivo, "devolver_sinal": devolver_sinal}

    def func(op):
        e = _aberta(encomenda_id, lock=True)
        texto = (motivo or "").strip()
        if not texto:
            raise RegraViolada("Informe o motivo do cancelamento.")
        liberadas = _liberar(op, Reserva.objects.filter(item_encomenda__encomenda=e, situacao="ativa"),
                             "encomenda cancelada")
        e.situacao, e.fim_operacao, e.motivo_cancelamento = "cancelada", op, texto
        e.sinal_devolvido = e.sinal if devolver_sinal else Decimal("0")
        e.save(update_fields=["situacao", "fim_operacao", "motivo_cancelamento", "sinal_devolvido"])
        return {"encomenda_id": e.id, "situacao": "cancelada", "reservas_liberadas": liberadas,
                "sinal": e.sinal, "sinal_devolvido": e.sinal_devolvido}

    return executar("cancelar_encomenda", func, autor=autor, canal=canal, chave=chave, parametros=parametros)


def entregar_encomenda(*, encomenda_id, condicao="a_vista", forma_pagamento="", parcelas=None, data_entrega=None,
                       autor, canal="web", chave=None) -> dict:
    """Entrega ou retirada (RF-VEN-08): só com tudo reservado e dentro da validade; as reservas viram saída
    por venda e as embalagens são baixadas. Vira uma venda, uma única vez. O saldo (total − sinal) entra
    na hora (à vista) ou vira conta a receber (a prazo, parcelas somando o saldo)."""
    parametros = {"encomenda_id": encomenda_id, "condicao": condicao, "forma_pagamento": forma_pagamento,
                  "parcelas": parcelas, "data_entrega": data_entrega}

    def func(op):
        e = _aberta(encomenda_id, lock=True)
        _condicao(condicao)
        hoje = timezone.localdate()
        quando = data(data_entrega, "data_entrega") or hoje
        saldo = e.total - e.sinal
        cond = condicao if saldo > 0 else "a_vista"
        v = Venda.objects.create(cliente=e.cliente, data=quando, tabela=e.tabela, condicao=cond,
                                 forma_pagamento=(forma_pagamento or "").strip(), total=e.total, custo=0,
                                 recebido_na_hora=saldo if cond == "a_vista" else 0, encomenda=e, operacao=op)
        motivo, custo = f"Venda {v.id} (encomenda {e.id})", Decimal("0")
        for ie in e.itens.select_related("apresentacao__produto", "apresentacao__embalagem"):
            a = ie.apresentacao
            reservas = list(ie.reservas.filter(situacao="ativa").select_related("lote__item"))
            tem = sum((r.quantidade for r in reservas), Decimal("0"))
            if tem < ie.unidades:
                raise RegraViolada(f"Falta reservar {_un(ie.unidades - tem)} de '{a.produto.nome}' {a.forma} "
                                   f"{a.estado}. Complete a reserva antes de entregar.")
            baixas = []
            for r in reservas:
                validade = validade_porcao(r.lote, r.estado)
                if validade and validade < hoje:
                    raise RegraViolada(f"O lote {r.lote.codigo or 'sem lote'} reservado de '{a.produto.nome}' "
                                       "venceu. Complete a reserva com outro lote antes de entregar.")
                if saldo_lote(r.lote, r.estado) < r.quantidade:
                    raise RegraViolada(f"O lote {r.lote.codigo or 'sem lote'} de '{a.produto.nome}' não tem mais "
                                       f"{_un(r.quantidade)} em {r.estado}.")
                baixas.append(_baixar(op, r.lote, r.estado, r.quantidade, motivo))
                r.situacao, r.fim_operacao = "baixada", op
                r.save(update_fields=["situacao", "fim_operacao"])
            baixas += _baixar_embalagens(op, a, ie.quantidade, motivo, hoje)
            c = sum((b["custo"] for b in baixas), Decimal("0"))
            custo += c
            LinhaVenda.objects.create(venda=v, apresentacao=a, quantidade=ie.quantidade, unidades_por=ie.unidades_por,
                                      preco_tabela=ie.preco_tabela, preco=ie.preco, total=ie.total, custo=c,
                                      baixas=_json(baixas))
        v.custo = custo
        v.save(update_fields=["custo"])
        conta = None
        if cond == "a_prazo":
            conta = abrir_conta_receber(op, venda=v, total=saldo, parcelas=parcelas,
                                        descricao=f"Encomenda {e.id} — {e.cliente}")
        e.situacao, e.fim_operacao = "entregue", op
        e.save(update_fields=["situacao", "fim_operacao"])
        conta_id, parc = _parcelas_saida(conta)
        return {"venda_id": v.id, "encomenda_id": e.id, "cliente": str(e.cliente), "condicao": cond,
                "total": e.total, "sinal": e.sinal, "saldo": saldo, "recebido_na_hora": v.recebido_na_hora,
                "custo": custo, "conta_id": conta_id, "parcelas": parc, "linhas": _linhas_saida(v)}

    return executar("entregar_encomenda", func, autor=autor, canal=canal, chave=chave, parametros=parametros)
