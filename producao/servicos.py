from cadastros.models import Item
from estoque.models import FORMAS
from fichas.escala import escalar
from fichas.versoes import versao_vigente
from nucleo.operacoes import RegraViolada, executar
from web.templatetags.formato import quantidade as fmt_qtd

from .models import LinhaPreparo, Producao


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
