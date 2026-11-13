"""Contas a pagar e a receber: parcelas, anotação de pagamento/recebimento, estorno e avisos de ajuste.

O sistema nunca paga nem cobra nada: `registrar_pagamento` só anota que o dono pagou e
`registrar_recebimento`, que o cliente pagou. As duas usam o mesmo `Pagamento` (a conta diz o tipo).
Situação e saldo da parcela são sempre derivados dos pagamentos não estornados.
"""

from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.db.models import Sum
from django.utils import timezone

from nucleo.operacoes import RegraViolada, executar
from nucleo.valores import CENTAVO, data, reais
from web.templatetags.formato import dinheiro

from .models import DIFERENCAS, AvisoAjuste, Conta, Pagamento, Parcela

CONDICOES = ("a_vista", "a_prazo")


# ---------- leitura (sem gravar) ----------

def pago_parcela(parcela) -> Decimal:
    return (parcela.pagamentos.filter(estorno_operacao__isnull=True)
            .aggregate(s=Sum("valor"))["s"] or Decimal("0"))


def saldo_parcela(parcela) -> Decimal:
    if parcela.conta.cancelada:
        return Decimal("0")
    return parcela.valor - pago_parcela(parcela)


def situacao_parcela(parcela) -> str:
    """aberta | parcial | paga | cancelada (RF-FIN-07). "Vencida" é derivada à parte."""
    if parcela.conta.cancelada:
        return "cancelada"
    pago = pago_parcela(parcela)
    if pago >= parcela.valor:
        return "paga"
    return "parcial" if pago > 0 else "aberta"


def vencida(parcela, hoje=None) -> bool:
    hoje = hoje or timezone.localdate()
    return situacao_parcela(parcela) in ("aberta", "parcial") and parcela.vencimento < hoje


def dividir_parcelas(total, n: int, primeiro_vencimento, intervalo_dias: int = 30) -> list[dict]:
    """Sugestão de parcelas iguais; os centavos que sobram vão na última. Soma = total (RN-32)."""
    total, primeiro_vencimento = reais(total, "total"), data(primeiro_vencimento, "primeiro_vencimento")
    if n < 1:
        raise RegraViolada("Informe ao menos uma parcela.")
    base = (total / n).quantize(CENTAVO, ROUND_DOWN)
    return [{"valor": base if i < n - 1 else total - base * (n - 1),
             "vencimento": primeiro_vencimento + timedelta(days=intervalo_dias * i)} for i in range(n)]


# ---------- usados dentro de outras operações (já dentro de executar) ----------

def _ler_parcelas(parcelas, total) -> list[tuple[Decimal, object]]:
    if not parcelas:
        raise RegraViolada("Informe as parcelas (valor e vencimento).")
    lidas = []
    for i, p in enumerate(parcelas, 1):
        valor, venc = reais(p.get("valor"), f"parcela {i}"), data(p.get("vencimento"), f"parcela {i}")
        if valor <= 0:
            raise RegraViolada(f"Parcela {i}: o valor deve ser maior que zero.")
        if venc is None:
            raise RegraViolada(f"Parcela {i}: informe o vencimento.")
        lidas.append((valor, venc))
    soma = sum(v for v, _ in lidas)
    if soma != total:
        raise RegraViolada(f"As parcelas somam {dinheiro(soma)} e o total é {dinheiro(total)}.")
    return lidas


def abrir_conta(op, *, compra, total, condicao, parcelas=None, data_pagamento=None, forma_pagamento=""):
    """Obrigação da compra (DEC-F2-006): à vista nasce quitada; a prazo, com parcelas."""
    if condicao not in CONDICOES:
        raise RegraViolada("Escolha a condição de pagamento: à vista ou a prazo.")
    if condicao == "a_vista":
        quando = data(data_pagamento, "data_pagamento") or compra.data
        lidas = [(total, quando)]
    else:
        lidas = _ler_parcelas(parcelas, total)
    conta = Conta.objects.create(origem="compra", compra=compra, fornecedor=compra.fornecedor, total=total,
                                 descricao=f"Compra {compra.id} — {compra.fornecedor}", operacao=op)
    for n, (valor, venc) in enumerate(lidas, 1):
        p = Parcela.objects.create(conta=conta, numero=n, valor=valor, vencimento=venc)
        if condicao == "a_vista":
            Pagamento.objects.create(parcela=p, valor=valor, data=venc, forma=(forma_pagamento or "").strip(),
                                     operacao=op)
    return conta


def abrir_conta_receber(op, *, venda, total, parcelas, descricao):
    """Recebível de venda a prazo ou do saldo de encomenda (RF-VEN-04, RF-FIN-06): parcelas somando o total."""
    lidas = _ler_parcelas(parcelas, total)
    conta = Conta.objects.create(tipo="receber", origem="venda", venda=venda, cliente=venda.cliente, total=total,
                                 descricao=descricao, operacao=op)
    for n, (valor, venc) in enumerate(lidas, 1):
        Parcela.objects.create(conta=conta, numero=n, valor=valor, vencimento=venc)
    return conta


def cancelar_conta_da_venda(op, conta, motivo) -> Decimal:
    """Cancela o recebível de uma venda cancelada ou devolvida (RF-VEN-10). Devolve quanto o cliente já
    tinha pago (o valor a devolver, anotado na venda); os recebimentos continuam visíveis."""
    recebido = (Pagamento.objects.filter(parcela__conta=conta, estorno_operacao__isnull=True)
                .aggregate(s=Sum("valor"))["s"] or Decimal("0"))
    conta.cancelada, conta.motivo_cancelamento = True, motivo[:200]
    conta.save(update_fields=["cancelada", "motivo_cancelamento"])
    return recebido


def avisar_ajuste(op, conta, texto):
    return AvisoAjuste.objects.create(conta=conta, texto=texto[:300], operacao=op)


# ---------- operações ----------

_TIPO = {"pagar": ("Esta parcela é de uma conta a receber: anote como recebimento.", "pagamento"),
         "receber": ("Esta parcela é de uma conta a pagar: anote como pagamento.", "recebimento")}


def _anotar(tipo, *, parcela_id, valor, data_pagamento, forma, diferenca, diferenca_tipo, diferenca_motivo):
    def func(op):
        p = Parcela.objects.select_related("conta").filter(id=parcela_id).first()
        if p is None:
            raise RegraViolada("Parcela não encontrada.")
        if p.conta.tipo != tipo:
            raise RegraViolada(_TIPO[tipo][0])
        if p.conta.cancelada:
            raise RegraViolada("Esta conta foi cancelada.")
        saldo = saldo_parcela(p)
        if saldo <= 0:
            raise RegraViolada("Esta parcela já está paga.")
        v = saldo if valor in (None, "") else reais(valor, "valor")
        if v <= 0:
            raise RegraViolada("O valor deve ser maior que zero.")
        if v > saldo:
            raise RegraViolada(f"O valor passa do saldo da parcela ({dinheiro(saldo)}).")
        dif, dtipo, motivo = reais(diferenca or 0, "diferenca"), (diferenca_tipo or "").strip(), (diferenca_motivo or "").strip()
        if dif < 0:
            raise RegraViolada("Informe a diferença sem sinal e escolha juros, multa ou desconto.")
        if dif > 0:
            if dtipo not in dict(DIFERENCAS):
                raise RegraViolada("Diga se a diferença é juros, multa ou desconto.")
            if not motivo:
                raise RegraViolada("Informe o motivo da diferença.")
            if dtipo == "desconto" and dif >= v:
                raise RegraViolada("O desconto deve ser menor que o valor abatido.")
        else:
            dtipo, motivo = "", ""
        quando = data(data_pagamento, "data_pagamento") or timezone.localdate()
        pg = Pagamento.objects.create(parcela=p, valor=v, data=quando, forma=(forma or "").strip(), diferenca=dif,
                                      diferenca_tipo=dtipo, diferenca_motivo=motivo, operacao=op)
        return {"pagamento_id": pg.id, "parcela_id": p.id, "valor": v, "valor_pago": pg.valor_pago,
                "situacao": situacao_parcela(p), "saldo": saldo_parcela(p)}

    return func


def registrar_pagamento(*, parcela_id, valor=None, data_pagamento=None, forma="", diferenca=0,
                        diferenca_tipo="", diferenca_motivo="", autor, canal="web", chave=None) -> dict:
    """Anota que o dono pagou (total ou parte) uma parcela a pagar. `valor` = quanto abate (padrão: o saldo)."""
    parametros = {"parcela_id": parcela_id, "valor": valor, "data_pagamento": data_pagamento, "forma": forma,
                  "diferenca": diferenca, "diferenca_tipo": diferenca_tipo, "diferenca_motivo": diferenca_motivo}
    return executar("registrar_pagamento", _anotar("pagar", **parametros), autor=autor, canal=canal, chave=chave,
                    parametros=parametros)


def registrar_recebimento(*, parcela_id, valor=None, data_pagamento=None, forma="", diferenca=0,
                          diferenca_tipo="", diferenca_motivo="", autor, canal="web", chave=None) -> dict:
    """Anota que o cliente pagou (total ou parte) uma parcela a receber (RF-FIN-06). `valor` = quanto abate
    (padrão: o saldo); `valor_pago` no retorno = quanto entrou (desconto: o cliente pagou menos)."""
    parametros = {"parcela_id": parcela_id, "valor": valor, "data_pagamento": data_pagamento, "forma": forma,
                  "diferenca": diferenca, "diferenca_tipo": diferenca_tipo, "diferenca_motivo": diferenca_motivo}
    return executar("registrar_recebimento", _anotar("receber", **parametros), autor=autor, canal=canal,
                    chave=chave, parametros=parametros)


def _estornar(tipo, pagamento_id, motivo):
    def func(op):
        pg = Pagamento.objects.select_related("parcela__conta").filter(id=pagamento_id).first()
        if pg is None or pg.parcela.conta.tipo != tipo:
            raise RegraViolada(f"{_TIPO[tipo][1].capitalize()} não encontrado.")
        if not (motivo or "").strip():
            raise RegraViolada("Informe o motivo do estorno.")
        if pg.estorno_operacao_id:
            raise RegraViolada(f"Este {_TIPO[tipo][1]} já foi estornado.")
        pg.estorno_operacao, pg.motivo_estorno = op, motivo.strip()
        pg.save(update_fields=["estorno_operacao", "motivo_estorno"])
        return {"pagamento_id": pg.id, "parcela_id": pg.parcela_id, "situacao": situacao_parcela(pg.parcela),
                "saldo": saldo_parcela(pg.parcela)}

    return func


def estornar_pagamento(*, pagamento_id, motivo, autor, canal="web", chave=None) -> dict:
    """Anula um pagamento lançado errado (DEC-F2-027). O original fica visível; a parcela volta ao estado anterior."""
    return executar("estornar_pagamento", _estornar("pagar", pagamento_id, motivo), autor=autor, canal=canal,
                    chave=chave, parametros={"pagamento_id": pagamento_id, "motivo": motivo})


def estornar_recebimento_cliente(*, pagamento_id, motivo, autor, canal="web", chave=None) -> dict:
    """Anula um recebimento de cliente lançado errado (RF-FIN-09), como `estornar_pagamento`."""
    return executar("estornar_recebimento_cliente", _estornar("receber", pagamento_id, motivo), autor=autor,
                    canal=canal, chave=chave, parametros={"pagamento_id": pagamento_id, "motivo": motivo})


def resolver_aviso(*, aviso_id, observacao, autor, canal="web", chave=None) -> dict:
    """O dono diz o que fez com o aviso de ajuste (ex.: "fornecedor abateu no boleto")."""

    def func(op):
        a = AvisoAjuste.objects.filter(id=aviso_id).first()
        if a is None:
            raise RegraViolada("Aviso não encontrado.")
        if a.resolvido_operacao_id:
            raise RegraViolada("Este aviso já foi resolvido.")
        if not (observacao or "").strip():
            raise RegraViolada("Conte o que foi feito com o aviso.")
        a.resolvido_operacao, a.observacao = op, observacao.strip()
        a.save(update_fields=["resolvido_operacao", "observacao"])
        return {"aviso_id": a.id}

    return executar("resolver_aviso", func, autor=autor, canal=canal, chave=chave,
                    parametros={"aviso_id": aviso_id, "observacao": observacao})
