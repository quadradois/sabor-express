from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Min, Sum
from django.utils import timezone

from cadastros.models import Item
from estoque.models import ESTADOS, FORMAS, ConsumoPendente, Lote, Movimento
from estoque.servicos import alocar_fefo, alocar_fefo_parcial, calcular_validade, saldo_lote
from fichas.escala import escalar
from fichas.versoes import versao_vigente
from nucleo.operacoes import RegraViolada, executar
from web.templatetags.formato import quantidade as fmt_qtd

from .models import Cronometro, LinhaPreparo, Producao


def iniciar_producao(*, produto_id, unidades, forma, pendente_justificativa="", autor, canal="web",
                     chave=None) -> dict:
    """Com `pendente_justificativa`, começa mesmo faltando estoque: o que faltar na conclusão vira
    consumo pendente de conciliação (DEC-F2-005)."""
    parametros = {"produto_id": produto_id, "unidades": unidades, "forma": forma}
    if pendente_justificativa:
        parametros["pendente_justificativa"] = pendente_justificativa

    def func(op):
        try:
            produto = Item.objects.select_related("ficha").get(id=produto_id, tipo="produto")
        except Item.DoesNotExist:
            raise RegraViolada("Produto não encontrado.")
        if not produto.ativo:
            raise RegraViolada(f"O produto '{produto.nome}' está inativo.")
        if forma not in dict(FORMAS):
            raise RegraViolada("Forma inválida.")
        if forma == "frito" and not produto.oleo_ref_un:
            raise RegraViolada(f"Cadastre a referência de óleo de '{produto.nome}'.")
        receita = escalar(produto.ficha, unidades, produto.peso_g)
        justificativa = (pendente_justificativa or "").strip()
        for b in receita.blocos:
            for l in b.linhas:
                if l.falta > 0 and not justificativa:
                    raise RegraViolada(f"Falta {fmt_qtd(l.falta, l.unidade_base)} de '{l.nome}'. Dê entrada no estoque antes de começar.")
        etapas = [{"bloco": b.nome, "instrucao": e.instrucao, "tempo_seg": e.tempo_seg, "ponto": e.ponto,
                   "midia": e.midia.url if e.midia else ""} for b in receita.blocos for e in b.etapas]
        if forma == "frito":
            etapas.append({"bloco": "Fritura", "instrucao": f"Frite as {unidades} unidades.",
                           "tempo_seg": None, "ponto": "", "midia": ""})
        p = Producao.objects.create(produto=produto, versao=versao_vigente(produto.ficha), unidades=unidades,
                                    peso_g=produto.peso_g, forma=forma, etapas=etapas,
                                    pendente_justificativa=justificativa)
        LinhaPreparo.objects.bulk_create([
            LinhaPreparo(producao=p, bloco=b.nome, item_id=l.item_id, previsto=l.quantidade, ordem=i)
            for i, (b, l) in enumerate((b, l) for b in receita.blocos for l in b.linhas)])
        return {"producao_id": p.id}

    return executar("iniciar_producao", func, autor=autor, canal=canal, chave=chave, parametros=parametros)


def _em_andamento(producao_id):
    p = Producao.objects.filter(id=producao_id).first()
    if p is None:
        raise RegraViolada("Produção não encontrada.")
    if p.status != "andamento":
        raise RegraViolada("Esta produção já foi encerrada.")
    return p


def _tudo_pesado(p):
    faltam = [l.item.nome for l in p.linhas.select_related("item").filter(usado__isnull=True)]
    if faltam:
        raise RegraViolada(f"Pese ou marque 'usei o previsto' em: {', '.join(faltam)}.")


def registrar_peso(*, linha_id, usado, lote_id=None, autor, canal="web", chave=None) -> dict:
    def func(op):
        l = LinhaPreparo.objects.select_related("item").filter(id=linha_id).first()
        if l is None:
            raise RegraViolada("Linha não encontrada.")
        _em_andamento(l.producao_id)
        v = l.previsto if usado is None else usado
        if v < 0:
            raise RegraViolada("O peso não pode ser negativo.")
        if lote_id is not None:
            lote = Lote.objects.filter(id=lote_id).first()
            if lote is None or lote.item_id != l.item_id:
                raise RegraViolada(f"Esse lote não é de '{l.item.nome}'.")
            l.lote = lote
        l.usado = v
        l.save()
        return {"linha_id": l.id, "usado": str(v)}

    return executar("registrar_peso", func, autor=autor, canal=canal, chave=chave,
                    parametros={"linha_id": linha_id, "usado": usado, "lote_id": lote_id})


def usar_previsto_restantes(*, producao_id, autor, canal="web", chave=None) -> dict:
    def func(op):
        p = _em_andamento(producao_id)
        n = 0
        for l in p.linhas.filter(usado__isnull=True):
            l.usado = l.previsto
            l.save()
            n += 1
        return {"linhas": n}

    return executar("usar_previsto_restantes", func, autor=autor, canal=canal, chave=chave,
                    parametros={"producao_id": producao_id})


def ir_para_etapa(*, producao_id, indice, autor, canal="web", chave=None) -> dict:
    def func(op):
        p = _em_andamento(producao_id)
        if not 0 <= indice <= p.fechamento:
            raise RegraViolada("Etapa inexistente.")
        if indice > 0:
            _tudo_pesado(p)
        p.etapa_atual = indice
        p.save()
        return {"etapa_atual": indice}

    return executar("ir_para_etapa", func, autor=autor, canal=canal, chave=chave,
                    parametros={"producao_id": producao_id, "indice": indice})


def iniciar_cronometro(*, producao_id, nome, segundos, autor, canal="web", chave=None) -> dict:
    def func(op):
        p = _em_andamento(producao_id)
        if segundos <= 0:
            raise RegraViolada("O tempo deve ser maior que zero.")
        c = Cronometro.objects.create(producao=p, nome=nome, fim=timezone.now() + timedelta(seconds=segundos))
        return {"cronometro_id": c.id, "fim": c.fim.isoformat()}

    return executar("iniciar_cronometro", func, autor=autor, canal=canal, chave=chave,
                    parametros={"producao_id": producao_id, "nome": nome, "segundos": segundos})


def parar_cronometro(*, cronometro_id, autor, canal="web", chave=None) -> dict:
    def func(op):
        c = Cronometro.objects.filter(id=cronometro_id).first()
        if c is None:
            raise RegraViolada("Cronômetro não encontrado.")
        _em_andamento(c.producao_id)
        if c.parado_em is None:
            c.parado_em = timezone.now()
            c.save()
        return {"cronometro_id": c.id}

    return executar("parar_cronometro", func, autor=autor, canal=canal, chave=chave,
                    parametros={"cronometro_id": cronometro_id})


def cancelar_producao(*, producao_id, motivo, autor, canal="web", chave=None) -> dict:
    def func(op):
        p = _em_andamento(producao_id)
        if not motivo.strip():
            raise RegraViolada("Informe o motivo do cancelamento.")
        p.status, p.motivo_cancelamento, p.encerrada_em = "cancelada", motivo.strip(), timezone.now()
        p.save()
        return {"producao_id": p.id}

    return executar("cancelar_producao", func, autor=autor, canal=canal, chave=chave,
                    parametros={"producao_id": producao_id, "motivo": motivo})


def concluir_producao(*, producao_id, quantidade_boa, perdas=0, perda_motivo="", estado, validade_manual=None,
                      justificativa="", anotacao="", confirmar_perda_total=False, pendente_justificativa="",
                      autor, canal="web", chave=None) -> dict:
    """Sem saldo para o que foi pesado: recusa, a menos que haja justificativa de consumo pendente
    (aqui ou ao iniciar); então o que faltar vira `ConsumoPendente` e o custo fica pendente."""
    parametros = {"producao_id": producao_id, "quantidade_boa": quantidade_boa, "perdas": perdas,
                  "perda_motivo": perda_motivo, "estado": estado, "validade_manual": validade_manual,
                  "justificativa": justificativa, "anotacao": anotacao, "confirmar_perda_total": confirmar_perda_total}
    if pendente_justificativa:
        parametros["pendente_justificativa"] = pendente_justificativa

    def func(op):
        p = _em_andamento(producao_id)
        _tudo_pesado(p)
        if quantidade_boa < 0 or perdas < 0:
            raise RegraViolada("As quantidades não podem ser negativas.")
        if perdas > 0 and not perda_motivo.strip():
            raise RegraViolada("Informe o motivo das perdas.")
        if estado not in dict(ESTADOS):
            raise RegraViolada("Escolha a conservação.")
        if quantidade_boa == 0 and not confirmar_perda_total:
            raise RegraViolada("Nenhuma unidade boa: confirme a perda total.")
        hoje, motivo, custo = timezone.localdate(), f"Produção {p.id}", Decimal("0")
        pendente = (pendente_justificativa or "").strip() or p.pendente_justificativa

        def consumir(lote, q):
            nonlocal custo
            Movimento.objects.create(tipo="consumo_producao", item=lote.item, lote=lote, quantidade=-q,
                                     quantidade_informada=q, unidade_informada=lote.item.unidade_base,
                                     fator=Decimal("1"), motivo=motivo, operacao=op)
            custo += q * lote.custo_unitario

        por_item = defaultdict(lambda: [Decimal("0"), defaultdict(Decimal)])  # item -> [total, {lote: q}]
        for l in p.linhas.select_related("item", "lote__item"):
            por_item[l.item][0] += l.usado
            if l.lote:
                por_item[l.item][1][l.lote] += l.usado
        for item, (total, fixos) in por_item.items():
            for lote, q in fixos.items():
                if (lote.validade and lote.validade < hoje) or saldo_lote(lote) < q:
                    raise RegraViolada(f"O lote escolhido de '{item.nome}' não tem {fmt_qtd(q, item.unidade_base)} disponíveis.")
                if q > 0:
                    consumir(lote, q)
            resto = total - sum(fixos.values())
            if resto > 0:  # depois dos fixados: o saldo já reflete o que eles consumiram
                if not pendente:
                    alocacao, falta = alocar_fefo(item, resto, hoje=hoje), Decimal("0")
                else:
                    alocacao, falta = alocar_fefo_parcial(item, resto, hoje=hoje)
                for lote, q in alocacao:
                    consumir(lote, q)
                if falta > 0:
                    ConsumoPendente.objects.create(item=item, quantidade=falta, justificativa=pendente,
                                                   producao=p, operacao=op)
                    p.custo_pendente = True
        if p.forma == "frito":
            custo += p.produto.oleo_ref_un * (quantidade_boa + perdas)
        p.custo_total = custo.quantize(Decimal("0.01"), ROUND_HALF_UP)
        if quantidade_boa > 0:
            p.custo_unitario = (p.custo_total / quantidade_boa).quantize(Decimal("0.0001"), ROUND_HALF_UP)
            validade, manual = calcular_validade(p.produto, p.forma, estado, hoje=hoje, manual=validade_manual,
                                                 justificativa=justificativa)
            p.lote = Lote.objects.create(item=p.produto, codigo=f"{hoje:%y%m%d}-{p.id}", forma=p.forma,
                                         validade=validade, custo_unitario=p.custo_unitario)
            Movimento.objects.create(tipo="entrada_producao", item=p.produto, lote=p.lote, quantidade=quantidade_boa,
                                     quantidade_informada=quantidade_boa, unidade_informada="un", fator=Decimal("1"),
                                     motivo=motivo, estado=estado, validade=validade, validade_manual=manual, operacao=op)
        p.status, p.quantidade_boa, p.perdas, p.perda_motivo = "concluida", quantidade_boa, perdas, perda_motivo.strip()
        p.anotacao, p.encerrada_em = anotacao.strip(), timezone.now()
        p.save()
        return {"lote_id": p.lote_id, "custo_total": p.custo_total, "custo_unitario": p.custo_unitario,
                "custo_pendente": p.custo_pendente,
                "pendentes": [{"pendente_id": c.id, "item": c.item.nome, "quantidade": c.quantidade}
                              for c in p.consumos_pendentes.select_related("item")]}

    return executar("concluir_producao", func, autor=autor, canal=canal, chave=chave, parametros=parametros)


def conciliar_consumo(*, pendente_id, lote_id, autor, canal="web", chave=None) -> dict:
    """Vincula um consumo pendente a um lote (DEC-F2-033): baixa do lote e fecha o custo, uma única vez.

    O custo da produção (e do lote que ela gerou) passa a incluir o custo desse lote; quando não restar
    pendência, o custo deixa de ser "pendente" (RN-25 a).
    """

    def func(op):
        c = ConsumoPendente.objects.select_related("item", "producao__lote").filter(id=pendente_id).first()
        if c is None:
            raise RegraViolada("Consumo pendente não encontrado.")
        if not c.aberto:
            raise RegraViolada("Este consumo pendente já foi conciliado.")
        lote = Lote.objects.select_related("item").filter(id=lote_id).first()
        if lote is None or lote.item_id != c.item_id:
            raise RegraViolada(f"Esse lote não é de '{c.item.nome}'.")
        if lote.validade and lote.validade < timezone.localdate():
            raise RegraViolada("Lote vencido não pode ser consumido.")
        disponivel = saldo_lote(lote)
        if disponivel < c.quantidade:
            raise RegraViolada(f"O lote só tem {fmt_qtd(disponivel, c.item.unidade_base)} de '{c.item.nome}'.")
        Movimento.objects.create(tipo="consumo_producao", item=c.item, lote=lote, quantidade=-c.quantidade,
                                 quantidade_informada=c.quantidade, unidade_informada=c.item.unidade_base,
                                 fator=Decimal("1"), motivo=f"Conciliação do consumo pendente {c.id}", operacao=op)
        c.lote, c.conciliacao_operacao = lote, op
        c.custo = (c.quantidade * lote.custo_unitario).quantize(Decimal("0.01"), ROUND_HALF_UP)
        c.save(update_fields=["lote", "conciliacao_operacao", "custo"])
        p = c.producao
        if p is not None:
            p.custo_total += c.custo
            p.custo_pendente = p.consumos_pendentes.filter(lote__isnull=True).exists()
            if p.quantidade_boa:
                p.custo_unitario = (p.custo_total / p.quantidade_boa).quantize(Decimal("0.0001"), ROUND_HALF_UP)
                p.lote.custo_unitario = p.custo_unitario
                p.lote.save(update_fields=["custo_unitario"])
            p.save(update_fields=["custo_total", "custo_pendente", "custo_unitario"])
        return {"pendente_id": c.id, "lote_id": lote.id, "custo": c.custo, "producao_id": c.producao_id,
                "custo_total": p.custo_total if p else None, "custo_pendente": p.custo_pendente if p else False}

    return executar("conciliar_consumo", func, autor=autor, canal=canal, chave=chave,
                    parametros={"pendente_id": pendente_id, "lote_id": lote_id})


def origem(lote) -> list:
    entrada = Movimento.objects.filter(lote=lote, tipo="entrada_producao").first()
    if entrada is None:
        return []
    linhas = (Movimento.objects.filter(operacao_id=entrada.operacao_id, quantidade__lt=0)
              .values("lote").annotate(q=Sum("quantidade"), primeiro=Min("id")).order_by("primeiro"))
    lotes = Lote.objects.in_bulk([r["lote"] for r in linhas])
    conciliados = ConsumoPendente.objects.filter(producao__lote=lote, lote__isnull=False).select_related("lote")
    return [(lotes[r["lote"]], -r["q"]) for r in linhas] + [(c.lote, c.quantidade) for c in conciliados]
