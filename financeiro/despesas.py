"""Despesas (Plano 8): categorias, despesa avulsa, despesa mensal e a conta de cada mês.

Despesa é conta a pagar (`Conta.origem="despesa"`, com `categoria` e `competencia`): vencimento, pagamento e
estorno seguem o fluxo das contas de fornecedor (`servicos.registrar_pagamento`, `estornar_pagamento`) e os
lembretes da caixa de decisões valem para as duas. O sistema nunca paga: só anota que o dono pagou.

A despesa mensal gera, uma vez por mês, uma `DespesaDoMes`. Com valor previsto, a conta do mês já nasce com
ele; sem valor, a conta só nasce quando o dono informa o valor (ou anota o pagamento com o valor real) —
até lá a despesa aparece "sem valor", nunca como zero.
"""

import calendar
from datetime import date

from django.utils import timezone

from nucleo.operacoes import RegraViolada, executar
from nucleo.valores import data, reais
from web.templatetags.formato import dinheiro

from .models import CategoriaDespesa, Conta, DespesaDoMes, DespesaMensal, Pagamento, Parcela
from .servicos import _anotar, pago_parcela


def mes(d: date) -> date:
    """Dia 1 do mês de `d` (a competência das despesas mensais)."""
    return d.replace(day=1)


def vencimento_no_mes(competencia: date, dia: int) -> date:
    """O dia `dia` do mês, ou o último dia se o mês for mais curto (dia 31 em fevereiro = dia 28/29)."""
    return competencia.replace(day=min(dia, calendar.monthrange(competencia.year, competencia.month)[1]))


def _nome_mes(competencia: date) -> str:
    return f"{competencia:%m/%Y}"


def _categoria(categoria_id) -> CategoriaDespesa:
    c = CategoriaDespesa.objects.filter(id=categoria_id).first()
    if c is None:
        raise RegraViolada("Escolha a categoria da despesa.")
    if not c.ativa:
        raise RegraViolada(f"A categoria '{c.nome}' está inativa.")
    return c


def _abrir(op, *, descricao, categoria, valor, vencimento, competencia) -> Conta:
    conta = Conta.objects.create(tipo="pagar", origem="despesa", categoria=categoria, competencia=competencia,
                                 descricao=descricao[:200], total=valor, operacao=op)
    Parcela.objects.create(conta=conta, numero=1, valor=valor, vencimento=vencimento)
    return conta


def _ativos(conta):
    return Pagamento.objects.filter(parcela__conta=conta, estorno_operacao__isnull=True)


# ---------- cadastros ----------

def salvar_categoria_despesa(*, nome, indireta=False, ativa=True, categoria_id=None, autor, canal="web",
                             chave=None) -> dict:
    """Cria (sem `categoria_id`) ou altera uma categoria. Categoria em uso não se apaga: inativa-se."""

    def func(op):
        n = (nome or "").strip()
        if not n:
            raise RegraViolada("Informe o nome da categoria.")
        if CategoriaDespesa.objects.filter(nome__iexact=n).exclude(id=categoria_id).exists():
            raise RegraViolada(f"Já existe a categoria '{n}'.")
        if categoria_id is None:
            c = CategoriaDespesa(nome=n, ordem=CategoriaDespesa.objects.count() + 1)
        else:
            c = CategoriaDespesa.objects.filter(id=categoria_id).first()
            if c is None:
                raise RegraViolada("Categoria não encontrada.")
        c.nome, c.indireta, c.ativa = n, bool(indireta), bool(ativa)
        c.save()
        return {"categoria_id": c.id, "nome": c.nome}

    return executar("salvar_categoria_despesa", func, autor=autor, canal=canal, chave=chave,
                    parametros={"categoria_id": categoria_id, "nome": nome, "indireta": indireta, "ativa": ativa})


def _gerar(op, despesa, competencia) -> tuple[DespesaDoMes, bool]:
    """A despesa do mês, criada uma única vez (a restrição única segura a corrida)."""
    if d := DespesaDoMes.objects.filter(despesa=despesa, competencia=competencia).first():
        return d, False
    venc = vencimento_no_mes(competencia, despesa.dia_vencimento)
    conta = None
    if despesa.valor_previsto is not None:
        conta = _abrir(op, descricao=f"{despesa.nome} — {_nome_mes(competencia)}", categoria=despesa.categoria,
                       valor=despesa.valor_previsto, vencimento=venc, competencia=competencia)
    return DespesaDoMes.objects.create(despesa=despesa, competencia=competencia, vencimento=venc, conta=conta,
                                       operacao=op), True


def salvar_despesa_mensal(*, nome, categoria_id, dia_vencimento=10, valor_previsto=None, ativa=True,
                          despesa_id=None, hoje=None, autor, canal="web", chave=None) -> dict:
    """Cria ou altera uma despesa mensal. `valor_previsto` é opcional (vazio = o mês nasce sem valor).
    Ativa, já gera a despesa do mês corrente (se ainda não houver). Mudar dia ou valor vale para os próximos
    meses: o mês já gerado não muda (para ele, `informar_valor_despesa`)."""
    hoje = hoje or timezone.localdate()

    def func(op):
        n = (nome or "").strip()
        if not n:
            raise RegraViolada("Informe o nome da despesa.")
        cat = _categoria(categoria_id)
        try:
            dia = int(dia_vencimento)
        except (TypeError, ValueError):
            raise RegraViolada("Dia de vencimento inválido.") from None
        if not 1 <= dia <= 31:
            raise RegraViolada("O dia de vencimento vai de 1 a 31.")
        previsto = None if valor_previsto in (None, "") else reais(valor_previsto, "valor_previsto")
        if previsto is not None and previsto <= 0:
            raise RegraViolada("O valor previsto deve ser maior que zero (ou fique em branco).")
        if DespesaMensal.objects.filter(nome__iexact=n).exclude(id=despesa_id).exists():
            raise RegraViolada(f"Já existe a despesa mensal '{n}'.")
        if despesa_id is None:
            d = DespesaMensal()
        else:
            d = DespesaMensal.objects.filter(id=despesa_id).first()
            if d is None:
                raise RegraViolada("Despesa mensal não encontrada.")
        d.nome, d.categoria, d.dia_vencimento, d.valor_previsto, d.ativa = n, cat, dia, previsto, bool(ativa)
        d.save()
        gerada = None
        if d.ativa:
            dm, criada = _gerar(op, d, mes(hoje))
            gerada = dm.id if criada else None
        return {"despesa_id": d.id, "nome": d.nome, "despesa_do_mes_gerada": gerada}

    return executar("salvar_despesa_mensal", func, autor=autor, canal=canal, chave=chave,
                    parametros={"despesa_id": despesa_id, "nome": nome, "categoria_id": categoria_id,
                                "dia_vencimento": dia_vencimento, "valor_previsto": valor_previsto, "ativa": ativa})


# ---------- rotina ----------

def gerar_despesas_do_mes(*, hoje=None, autor="rotina", canal="sistema") -> dict:
    """Gera a despesa do mês de cada despesa mensal ativa que ainda não tem (idempotente: rodar de novo não
    duplica). Só o mês corrente: meses passados não são recriados."""
    hoje = hoje or timezone.localdate()
    competencia = mes(hoje)

    def func(op):
        criadas = []
        for d in DespesaMensal.objects.filter(ativa=True).select_related("categoria").order_by("id"):
            dm, criada = _gerar(op, d, competencia)
            if criada:
                criadas.append(dm.id)
        return {"competencia": competencia, "criadas": criadas}

    return executar("gerar_despesas_do_mes", func, autor=autor, canal=canal,
                    parametros={"competencia": competencia})


# ---------- despesa avulsa ----------

def lancar_despesa(*, descricao, categoria_id, valor, paga=False, data_pagamento=None, vencimento=None,
                   competencia=None, forma="", hoje=None, autor, canal="web", chave=None) -> dict:
    """Despesa avulsa: já paga (`paga=True`: "paguei 850 de luz hoje", nasce quitada em `data_pagamento`, padrão
    hoje) ou a pagar (`vencimento` obrigatório). `competencia` = o dia a que o gasto pertence (padrão: o dia do
    pagamento, se paga; senão, hoje). `parecidas` no retorno lista despesas mensais da mesma categoria ainda
    em aberto no mês (se for a mesma, o certo é anotar o pagamento nela: `pagar_despesa_do_mes`)."""
    hoje = hoje or timezone.localdate()

    def func(op):
        desc = (descricao or "").strip()
        if not desc:
            raise RegraViolada("Diga do que é a despesa.")
        cat = _categoria(categoria_id)
        v = reais(valor, "valor") if valor not in (None, "") else None
        if v is None or v <= 0:
            raise RegraViolada("Informe o valor da despesa (maior que zero).")
        quando = data(data_pagamento, "data_pagamento") or hoje
        if paga:
            venc = quando
        else:
            venc = data(vencimento, "vencimento")
            if venc is None:
                raise RegraViolada("Informe o vencimento (ou diga que já está paga).")
        comp = data(competencia, "competencia") or (quando if paga else hoje)
        conta = _abrir(op, descricao=desc, categoria=cat, valor=v, vencimento=venc, competencia=comp)
        if paga:
            Pagamento.objects.create(parcela=conta.parcelas.get(), valor=v, data=quando, forma=(forma or "").strip(),
                                     operacao=op)
        parecidas = [{"despesa_do_mes_id": dm.id, "despesa": dm.despesa.nome, "vencimento": dm.vencimento}
                     for dm in DespesaDoMes.objects.filter(despesa__categoria=cat, competencia=mes(comp))
                     .select_related("despesa", "conta") if _em_aberto(dm)]
        return {"conta_id": conta.id, "parcela_id": conta.parcelas.get().id, "valor": v, "paga": bool(paga),
                "vencimento": venc, "competencia": comp, "parecidas": parecidas}

    return executar("lancar_despesa", func, autor=autor, canal=canal, chave=chave,
                    parametros={"descricao": descricao, "categoria_id": categoria_id, "valor": valor, "paga": paga,
                                "data_pagamento": data_pagamento, "vencimento": vencimento,
                                "competencia": competencia, "forma": forma})


def _em_aberto(dm) -> bool:
    """Despesa do mês sem valor, ou com conta não cancelada e saldo a pagar."""
    if dm.conta is None:
        return True
    if dm.conta.cancelada:
        return False
    return any(p.valor - pago_parcela(p) > 0 for p in dm.conta.parcelas.all())


def cancelar_despesa(*, conta_id, motivo, autor, canal="web", chave=None) -> dict:
    """Cancela uma despesa lançada errado ou que não vai acontecer (nada é apagado). Os pagamentos anotados nela
    são estornados na mesma operação, com o mesmo motivo. Despesa mensal cancelada = não há essa despesa neste
    mês (sai dos lembretes e do resultado); para mudar só o valor, use `informar_valor_despesa`."""

    def func(op):
        conta = Conta.objects.filter(id=conta_id, origem="despesa").first()
        if conta is None:
            raise RegraViolada("Despesa não encontrada.")
        if conta.cancelada:
            raise RegraViolada("Esta despesa já foi cancelada.")
        m = (motivo or "").strip()
        if not m:
            raise RegraViolada("Informe o motivo do cancelamento.")
        estornados = []
        for pg in _ativos(conta):
            pg.estorno_operacao, pg.motivo_estorno = op, m[:200]
            pg.save(update_fields=["estorno_operacao", "motivo_estorno"])
            estornados.append(pg.id)
        conta.cancelada, conta.motivo_cancelamento = True, m[:200]
        conta.save(update_fields=["cancelada", "motivo_cancelamento"])
        return {"conta_id": conta.id, "pagamentos_estornados": estornados}

    return executar("cancelar_despesa", func, autor=autor, canal=canal, chave=chave,
                    parametros={"conta_id": conta_id, "motivo": motivo})


# ---------- despesa do mês: valor e pagamento ----------

def _despesa_do_mes(despesa_do_mes_id) -> DespesaDoMes:
    dm = DespesaDoMes.objects.select_related("despesa__categoria", "conta").filter(id=despesa_do_mes_id).first()
    if dm is None:
        raise RegraViolada("Despesa do mês não encontrada.")
    if dm.conta_id and dm.conta.cancelada:
        raise RegraViolada(f"A despesa {dm.despesa.nome} de {_nome_mes(dm.competencia)} foi cancelada.")
    return dm


def _informar(op, dm, valor) -> dict:
    """Dá (ou corrige) o valor do mês. Com pagamento já anotado, recusa: estorne antes."""
    v = reais(valor, "valor")
    if v <= 0:
        raise RegraViolada("O valor deve ser maior que zero.")
    if dm.conta is None:
        dm.conta = _abrir(op, descricao=f"{dm.despesa.nome} — {_nome_mes(dm.competencia)}",
                          categoria=dm.despesa.categoria, valor=v, vencimento=dm.vencimento,
                          competencia=dm.competencia)
        dm.save(update_fields=["conta"])
        return {"valor_anterior": None, "valor": v}
    anterior = dm.conta.total
    if v != anterior:
        if _ativos(dm.conta).exists():
            raise RegraViolada(f"Já há pagamento anotado de {dm.despesa.nome}: estorne o pagamento antes "
                               f"de mudar o valor.")
        dm.conta.total = v
        dm.conta.save(update_fields=["total"])
        dm.conta.parcelas.update(valor=v)
    return {"valor_anterior": anterior, "valor": v}


def informar_valor_despesa(*, despesa_do_mes_id, valor, autor, canal="web", chave=None) -> dict:
    """Informa o valor da despesa mensal neste mês (a conta de luz chegou: R$ 812,40). Corrige o previsto
    enquanto não houver pagamento anotado."""

    def func(op):
        dm = _despesa_do_mes(despesa_do_mes_id)
        r = _informar(op, dm, valor)
        return {"despesa_do_mes_id": dm.id, "conta_id": dm.conta_id, **r}

    return executar("informar_valor_despesa", func, autor=autor, canal=canal, chave=chave,
                    parametros={"despesa_do_mes_id": despesa_do_mes_id, "valor": valor})


def pagar_despesa_do_mes(*, despesa_do_mes_id, valor=None, data_pagamento=None, forma="", autor, canal="web",
                         chave=None) -> dict:
    """Anota o pagamento da despesa do mês. `valor` = quanto foi a conta (o valor real); sem `valor`, paga o
    valor que já está na conta. Sem valor nenhum (mês nascido sem valor), recusa e pede o valor."""

    def func(op):
        dm = _despesa_do_mes(despesa_do_mes_id)
        if valor in (None, ""):
            if dm.conta is None:
                raise RegraViolada(f"{dm.despesa.nome} de {_nome_mes(dm.competencia)} ainda não tem valor: "
                                   f"diga quanto foi pago.")
        else:
            _informar(op, dm, valor)
        parcela = dm.conta.parcelas.get()
        if parcela.valor - pago_parcela(parcela) <= 0:
            raise RegraViolada(f"{dm.despesa.nome} de {_nome_mes(dm.competencia)} já está paga "
                               f"({dinheiro(parcela.valor)}).")
        r = _anotar("pagar", parcela_id=parcela.id, valor=None, data_pagamento=data_pagamento, forma=forma,
                    diferenca=0, diferenca_tipo="", diferenca_motivo="")(op)
        return {"despesa_do_mes_id": dm.id, "conta_id": dm.conta_id, **r}

    return executar("pagar_despesa_do_mes", func, autor=autor, canal=canal, chave=chave,
                    parametros={"despesa_do_mes_id": despesa_do_mes_id, "valor": valor,
                                "data_pagamento": data_pagamento, "forma": forma})
