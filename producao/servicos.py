from datetime import timedelta

from django.utils import timezone

from cadastros.models import Item
from estoque.models import FORMAS, Lote
from fichas.escala import escalar
from fichas.versoes import versao_vigente
from nucleo.operacoes import RegraViolada, executar
from web.templatetags.formato import quantidade as fmt_qtd

from .models import Cronometro, LinhaPreparo, Producao


def iniciar_producao(*, produto_id, unidades, forma, autor, canal="web", chave=None) -> dict:
    parametros = {"produto_id": produto_id, "unidades": unidades, "forma": forma}

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
        for b in receita.blocos:
            for l in b.linhas:
                if l.falta > 0:
                    raise RegraViolada(f"Falta {fmt_qtd(l.falta, l.unidade_base)} de '{l.nome}'. Dê entrada no estoque antes de começar.")
        etapas = [{"bloco": b.nome, "instrucao": e.instrucao, "tempo_seg": e.tempo_seg, "ponto": e.ponto,
                   "midia": e.midia.url if e.midia else ""} for b in receita.blocos for e in b.etapas]
        if forma == "frito":
            etapas.append({"bloco": "Fritura", "instrucao": f"Frite as {unidades} unidades.",
                           "tempo_seg": None, "ponto": "", "midia": ""})
        p = Producao.objects.create(produto=produto, versao=versao_vigente(produto.ficha), unidades=unidades,
                                    peso_g=produto.peso_g, forma=forma, etapas=etapas)
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
            faltam = [l.item.nome for l in p.linhas.select_related("item").filter(usado__isnull=True)]
            if faltam:
                raise RegraViolada(f"Pese ou marque 'usei o previsto' em: {', '.join(faltam)}.")
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
