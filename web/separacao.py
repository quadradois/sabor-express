"""Apoio das telas de separação (Plano 9): ler o que o atendente digitou ("peguei de outro lote"), listar os
lotes disponíveis e montar o painel de "de qual lote pegar". Não calcula alocação: tudo vem de
`vendas.lotes.separacao_venda` / `separacao_encomenda` (o mesmo Separador que a venda usa)."""
import hashlib

from estoque.lotes import dia_producao, nome_lote, vencida
from estoque.models import Lote
from estoque.servicos import livre_porcao, porcoes
from nucleo.operacoes import RegraViolada


def lotes_post(post, chave) -> list[dict]:
    """Os campos `lote_{chave}_{lote_id}` preenchidos -> [{lote_id, unidades}]."""
    prefixo, saida = f"lote_{chave}_", []
    for nome in post:
        if not nome.startswith(prefixo):
            continue
        valor = (post.get(nome) or "").strip()
        if valor in ("", "0"):
            continue
        sufixo = nome[len(prefixo):]
        if not (valor.isdigit() and sufixo.isdigit()):
            raise RegraViolada("Lotes indicados: use números inteiros de unidades.")
        saida.append({"lote_id": int(sufixo), "unidades": int(valor)})
    return sorted(saida, key=lambda x: x["lote_id"])


def assinatura(post) -> str:
    """Impressão digital do que muda a separação (itens, lotes indicados, data): se mudou depois que a
    separação foi mostrada, a tela mostra de novo antes de gravar."""
    pares = sorted((k, (post.get(k) or "").strip()) for k in post
                   if k.startswith(("qtd_", "lote_", "todo_", "data_")) and (post.get(k) or "").strip())
    return hashlib.sha1(repr(pares).encode()).hexdigest()[:16]


def disponiveis(apresentacao, quando, extra=None) -> list[dict]:
    """Lotes (porções) da forma e conservação da apresentação que o atendente pode ter pego: com saldo livre
    (mais o reservado da própria encomenda, em `extra`), feitos até o dia da venda. Vencido aparece marcado."""
    extra = extra or {}
    lotes = Lote.objects.filter(item=apresentacao.produto, forma=apresentacao.forma).in_bulk()
    saida = []
    for p in porcoes(item=apresentacao.produto, hoje=quando):
        lote = lotes.get(p["lote_id"])
        if lote is None or p["estado"] != apresentacao.estado or dia_producao(lote) > quando:
            continue
        livre = livre_porcao(lote, p["estado"]) + extra.get((lote.id, p["estado"]), 0)
        if livre > 0:
            saida.append({"lote_id": lote.id, "codigo": lote.codigo or "sem lote", "nome": nome_lote(lote),
                          "validade": p["validade"], "vencido": vencida(p["validade"], quando), "livre": livre})
    return saida


def painel(sep, post, quando, apresentacoes, *, chave_da_linha, extra=None) -> list[dict]:
    """Uma entrada por linha da separação: a linha do núcleo, os lotes que o atendente pode indicar e o que ele
    já digitou. `apresentacoes` = {id: Apresentacao}; `chave_da_linha(linha)` dá a chave dos campos."""
    saida = []
    for linha in sep["linhas"]:
        chave = chave_da_linha(linha)
        lotes = disponiveis(apresentacoes[linha["apresentacao_id"]], quando, extra)
        for d in lotes:
            d["digitado"] = post.get(f"lote_{chave}_{d['lote_id']}", "")
        saida.append({"linha": linha, "chave": chave, "disponiveis": lotes})
    return saida
