"""Registro rápido de fritura (PRD §7.8, FL-04): unidades cruas de um lote guardado viram um lote frito.

A fritura como última etapa de um preparo continua em `producao.servicos` (forma "frito"); aqui é a
fritura do balcão, a partir de um lote cru já produzido. Troca de óleo (RF-FRI-04) fica para depois.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from estoque.models import ESTADOS, Lote, Movimento
from estoque.servicos import calcular_validade, livre_porcao, saldo_lote, validade_porcao
from nucleo.operacoes import RegraViolada, executar
from web.templatetags.formato import quantidade as fmt_qtd

from .models import Fritura


def registrar_fritura(*, lote_id, quantidade, boas, estado="", estado_destino="fresco", perda_motivo="",
                      validade_manual=None, justificativa="", confirmar_perda_total=False,
                      autor, canal="web", chave=None) -> dict:
    """Frita `quantidade` unidades da porção (lote cru + `estado`) e gera um lote frito com as `boas`
    (RF-FRI-01), no `estado_destino` e com a validade do critério de "frito" (RN-27; sem critério, manual
    e justificada). Custo do lote frito = (custo do cru × fritas + óleo de referência × fritas) ÷ boas
    (RF-FRI-02, CA-24). Não frita o vencido (FL-04 E1) nem o reservado para encomendas."""
    parametros = {"lote_id": lote_id, "quantidade": quantidade, "boas": boas, "estado": estado,
                  "estado_destino": estado_destino, "perda_motivo": perda_motivo, "validade_manual": validade_manual,
                  "justificativa": justificativa, "confirmar_perda_total": confirmar_perda_total}

    def func(op):
        hoje = timezone.localdate()
        try:
            q, b = int(quantidade), int(boas)
        except (TypeError, ValueError):
            raise RegraViolada("Informe as quantidades em unidades inteiras.") from None
        lote = Lote.objects.select_related("item").filter(id=lote_id).first()
        if lote is None:
            raise RegraViolada("Lote não encontrado.")
        produto = lote.item
        if produto.tipo != "produto" or lote.forma != "cru":
            raise RegraViolada("Escolha um lote de salgado cru.")
        if not produto.oleo_ref_un:
            raise RegraViolada(f"Cadastre a referência de óleo de '{produto.nome}'.")
        if estado_destino not in dict(ESTADOS) or estado not in dict(ESTADOS):
            raise RegraViolada("Conservação inválida.")
        if q < 1:
            raise RegraViolada("Informe quantas unidades foram fritas.")
        if b < 0 or b > q:
            raise RegraViolada("As boas devem ficar entre zero e as fritas.")
        if b < q and not (perda_motivo or "").strip():
            raise RegraViolada("Informe o motivo das perdas.")
        if b == 0 and not confirmar_perda_total:
            raise RegraViolada("Nenhuma unidade boa: confirme a perda total.")
        v = validade_porcao(lote, estado)
        if v and v < hoje:
            raise RegraViolada("Lote vencido não pode ser frito; só descartado.")
        if q > saldo_lote(lote, estado):
            raise RegraViolada(f"Só há {fmt_qtd(saldo_lote(lote, estado), 'un')} desse lote em {estado}.")
        if q > livre_porcao(lote, estado):
            raise RegraViolada(f"Só {fmt_qtd(livre_porcao(lote, estado), 'un')} desse lote em {estado} não estão "
                               "reservadas para encomendas.")
        custo = (lote.custo_unitario * q + produto.oleo_ref_un * q).quantize(Decimal("0.01"), ROUND_HALF_UP)
        f = Fritura.objects.create(lote_origem=lote, estado_origem=estado, quantidade=q, boas=b,
                                   perda_motivo=(perda_motivo or "").strip() if b < q else "",
                                   estado=estado_destino, custo_total=custo, operacao=op)
        motivo = f"Fritura {f.id}"
        Movimento.objects.create(tipo="consumo_fritura", item=produto, lote=lote, quantidade=-q, quantidade_informada=q,
                                 unidade_informada="un", fator=Decimal("1"), motivo=motivo, estado=estado, operacao=op)
        validade, manual = None, False
        if b > 0:
            validade, manual = calcular_validade(produto, "frito", estado_destino, hoje=hoje, manual=validade_manual,
                                                 justificativa=justificativa)
            f.custo_unitario = (custo / b).quantize(Decimal("0.0001"), ROUND_HALF_UP)
            f.lote = Lote.objects.create(item=produto, codigo=f"{hoje:%y%m%d}-F{f.id}", forma="frito",
                                         validade=validade, custo_unitario=f.custo_unitario)
            Movimento.objects.create(tipo="entrada_fritura", item=produto, lote=f.lote, quantidade=b,
                                     quantidade_informada=b, unidade_informada="un", fator=Decimal("1"), motivo=motivo,
                                     estado=estado_destino, validade=validade, validade_manual=manual, operacao=op)
            f.save(update_fields=["custo_unitario", "lote"])
        return {"fritura_id": f.id, "lote_id": f.lote_id, "lote_origem_id": lote.id, "produto": produto.nome,
                "fritas": q, "boas": b, "perdas": q - b, "custo_total": custo, "custo_unitario": f.custo_unitario,
                "validade": validade, "validade_manual": manual}

    return executar("registrar_fritura", func, autor=autor, canal=canal, chave=chave, parametros=parametros)
