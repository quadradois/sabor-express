"""Ações de escrita do agente, independentes de transporte.

Nível 1 ("faz e repete"): grava direto pelo núcleo e devolve, além dos dados,
`dito` — a frase curta do que foi feito, com as quantidades formatadas pelo
sistema. Nível 2 ("repete e espera o sim"): só monta a proposta
(`agente.propostas`); quem grava é a confirmação.

Tudo chega pelo nome falado: produto, ingrediente, lote e cronômetro são
resolvidos aqui (ambíguo → `ConsultaInvalida` com `opcoes`). Nenhuma conta de
negócio: conversões de unidade, validades e saldos vêm do núcleo.
"""

import hashlib
import json
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Sum
from django.utils import timezone

from cadastros.models import Item
from cadastros.unidades import fator
from estoque.etiquetas import registrar_impressao
from estoque.models import ESTADOS, FORMAS, Lote, Movimento
from fichas.models import Ficha
from nucleo.models import RegistroOperacao
from producao import servicos as producao
from producao.models import Producao
from web.templatetags.formato import minutos as fmt_min
from web.templatetags.formato import quantidade as fmt_qtd

from . import propostas
from .consultas import ConsultaInvalida, _filtrar, _inteiro, _normal, escolher, resolver_produto

# Duas chamadas iguais dentro desta janela são a mesma (o modelo repetiu a chamada).
JANELA_REPETICAO = timedelta(seconds=6)

_SINONIMOS_ESTADO = {"fresc": "fresco", "resfri": "resfriado", "gelad": "resfriado",
                     "congel": "congelado", "freez": "congelado"}
_SINONIMOS_FORMA = {"cru": "cru", "frit": "frito", "frita": "frito"}


# --- entradas faladas ------------------------------------------------------

def _decimal(valor, nome) -> Decimal:
    try:
        return Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ConsultaInvalida(f"'{nome}' precisa ser um número.") from None


def _data(valor, nome) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        raise ConsultaInvalida(f"'{nome}' precisa ser uma data AAAA-MM-DD.") from None


def _escolha(valor, sinonimos, validos, nome):
    v = _normal(valor or "")
    for prefixo, chave in sinonimos.items():
        if v.startswith(prefixo):
            return chave
    raise ConsultaInvalida(f"'{nome}' deve ser um destes: {', '.join(validos)}.")


def _estado(valor, nome="conservacao"):
    return _escolha(valor, _SINONIMOS_ESTADO, [e for e, _ in ESTADOS], nome)


def _forma(valor):
    return _escolha(valor, _SINONIMOS_FORMA, [f for f, _ in FORMAS], "forma")


def _data_br(d) -> str:
    return date.fromisoformat(str(d)).strftime("%d/%m/%Y") if d else "sem validade"


def _reais(v) -> str:
    q = Decimal(str(v)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return "R$ " + f"{q:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def producao_alvo(producao_id=None) -> Producao:
    """A produção pedida; sem id, a única em andamento."""
    qs = Producao.objects.select_related("produto")
    if producao_id is not None:
        p = qs.filter(id=_inteiro(producao_id, "producao_id")).first()
        if p is None:
            raise ConsultaInvalida("Produção não encontrada.", 404)
        return p  # se já foi encerrada, quem recusa é o núcleo
    andamento = list(qs.filter(status="andamento").order_by("iniciada_em"))
    if len(andamento) == 1:
        return andamento[0]
    if not andamento:
        raise ConsultaInvalida("Nenhuma produção em andamento.", 404)
    raise ConsultaInvalida("Há mais de uma produção em andamento; diga qual (producao_id).", 409,
                           opcoes=[f"Produção {p.id}: {p.unidades} {p.produto.nome}" for p in andamento])


def _linha(p, nome):
    linhas = list(p.linhas.select_related("item"))
    repetidos = {l.item_id for l in linhas if sum(m.item_id == l.item_id for m in linhas) > 1}
    rotulo = lambda l: f"{l.item.nome} ({l.bloco})" if l.item_id in repetidos else l.item.nome
    return escolher(linhas, nome, oque="ingrediente nesta produção", rotulo=rotulo)


def resolver_porcao(produto, estado="", codigo=""):
    """(lote, estado, saldo) de um item pelo nome, entre as porções com saldo."""
    itens = _filtrar(Item.objects.filter(ativo=True), produto)
    if not (produto or "").strip() or not itens:
        raise ConsultaInvalida(f"Nenhum item com o nome '{produto}'.", 404)
    exatos = [i for i in itens if _normal(i.nome) == _normal(produto)]
    qs = (Movimento.objects.filter(item__in=exatos or itens).values("lote", "estado")
          .annotate(s=Sum("quantidade")).filter(s__gt=0).order_by("lote", "estado"))
    if estado:
        qs = qs.filter(estado=estado)
    lotes = Lote.objects.select_related("item").in_bulk({p["lote"] for p in qs})
    porcoes = [(lotes[p["lote"]], p["estado"], p["s"]) for p in qs]
    if codigo:
        porcoes = [x for x in porcoes if _normal(codigo) in _normal(x[0].codigo)]
    if len(porcoes) == 1:
        return porcoes[0]
    onde = f" em {estado}" if estado else ""
    if not porcoes:
        raise ConsultaInvalida(f"Nenhum lote de '{produto}' com saldo{onde}.", 404)
    raise ConsultaInvalida(f"Mais de um lote de '{produto}' com saldo{onde}; diga o código ou a conservação.", 409,
                           opcoes=[f"{l.item.nome} lote {l.codigo or 'sem código'}, {e or '-'}, "
                                   f"{fmt_qtd(s, l.item.unidade_base)}" for l, e, s in porcoes])


# --- nível 1: faz e repete -------------------------------------------------

def _uma_vez(acao, assinatura: dict, fazer):
    """Executa `fazer(chave)` salvo se a mesma chamada deu certo há menos de JANELA_REPETICAO.

    A chave é "agente:<ação>:<hash da chamada>:<único>". O hash junta o nome da
    ação e os argumentos já resolvidos; o sufixo único deixa a mesma chamada
    valer de novo depois da janela. Devolve (resultado, repetida).
    """
    h = hashlib.sha256(json.dumps([acao, assinatura], sort_keys=True, cls=DjangoJSONEncoder).encode()).hexdigest()[:16]
    prefixo = f"agente:{acao}:{h}:"
    anterior = (RegistroOperacao.objects
                .filter(chave__startswith=prefixo, status="sucesso", criado_em__gte=timezone.now() - JANELA_REPETICAO)
                .order_by("-id").first())
    if anterior:
        return anterior.resultado, True
    return fazer(prefixo + uuid.uuid4().hex), False


def _feito(dito, resultado, repetida, **extra):
    return {"dito": dito, **extra, "resultado": resultado, **({"repetida": True} if repetida else {})}


def descrever_etapa(p) -> str:
    if p.etapa_atual == 0:
        return "Mise en place: pese os ingredientes."
    if p.etapa_atual >= p.fechamento:
        return "Fechamento: diga quantas unidades ficaram boas, as perdas e a conservação."
    e = p.etapas[p.etapa_atual - 1]
    t = f"Etapa {p.etapa_atual} de {len(p.etapas)}, {e['bloco']}: {e['instrucao'].rstrip('.')}"
    if e.get("tempo_seg"):
        t += f" ({fmt_min(e['tempo_seg'])} min)"
    if e.get("ponto"):
        t += f". Ponto: {e['ponto'].rstrip('.')}"
    return t + "."


def _falta_pesar(p) -> str:
    faltam = [l.item.nome for l in p.linhas.select_related("item").filter(usado__isnull=True)]
    return f"Falta pesar: {', '.join(faltam)}." if faltam else "Tudo pesado."


def registrar_peso(*, item, quantidade, unidade="", lote="", producao_id=None, autor, canal):
    p = producao_alvo(producao_id)
    l = _linha(p, item)
    usado = _decimal(quantidade, "quantidade")
    if unidade:
        usado = (usado * fator(l.item, unidade)[1]).quantize(Decimal("0.001"), ROUND_HALF_UP)
    lote_obj = None
    if lote:
        lote_obj = escolher(Lote.objects.filter(item=l.item), lote, oque=f"lote de '{l.item.nome}'",
                            rotulo=lambda x: x.codigo or "sem código")
    lote_id = lote_obj.id if lote_obj else None
    r, rep = _uma_vez("registrar_peso", {"linha": l.id, "usado": usado, "lote": lote_id}, lambda chave: producao.registrar_peso(
        linha_id=l.id, usado=usado, lote_id=lote_id, autor=autor, canal=canal, chave=chave))
    dito = f"{l.item.nome}: {fmt_qtd(Decimal(r['usado']), l.item.unidade_base)} registrado"
    if lote_obj:
        dito += f", lote {lote_obj.codigo or 'sem código'}"
    return _feito(f"{dito}. {_falta_pesar(p)}", r, rep, producao_id=p.id)


def usar_previsto(*, item="", producao_id=None, autor, canal):
    p = producao_alvo(producao_id)
    if item:
        l = _linha(p, item)
        r, rep = _uma_vez("usar_previsto", {"linha": l.id}, lambda chave: producao.registrar_peso(
            linha_id=l.id, usado=None, autor=autor, canal=canal, chave=chave))
        dito = f"{l.item.nome}: previsto de {fmt_qtd(Decimal(r['usado']), l.item.unidade_base)} registrado."
    else:
        r, rep = _uma_vez("usar_previsto", {"producao": p.id}, lambda chave: producao.usar_previsto_restantes(
            producao_id=p.id, autor=autor, canal=canal, chave=chave))
        n = r["linhas"]
        dito = (f"Previsto registrado em {n} ingrediente{'s' if n > 1 else ''}." if n
                else "Nada a marcar: tudo já estava pesado.")
    return _feito(f"{dito} {_falta_pesar(p)}", r, rep, producao_id=p.id)


def _ir(p, indice, acao, assinatura, autor, canal):
    r, rep = _uma_vez(acao, assinatura, lambda chave: producao.ir_para_etapa(
        producao_id=p.id, indice=indice, autor=autor, canal=canal, chave=chave))
    p.refresh_from_db()
    return _feito(descrever_etapa(p), r, rep, producao_id=p.id)


def proxima_etapa(*, producao_id=None, autor, canal):
    p = producao_alvo(producao_id)
    # sem a etapa de origem na assinatura: repetida na janela, a 2ª chamada não avança outra vez
    return _ir(p, p.etapa_atual + 1, "proxima_etapa", {"producao": p.id}, autor, canal)


def ir_para_etapa(*, etapa, producao_id=None, autor, canal):
    p = producao_alvo(producao_id)
    etapa = _inteiro(etapa, "etapa")
    return _ir(p, etapa, "ir_para_etapa", {"producao": p.id, "etapa": etapa}, autor, canal)


def iniciar_cronometro(*, minutos=None, nome="", producao_id=None, autor, canal):
    p = producao_alvo(producao_id)
    e = p.etapas[p.etapa_atual - 1] if 1 <= p.etapa_atual <= len(p.etapas) else {}
    if minutos:
        segundos = int((_decimal(minutos, "minutos") * 60).to_integral_value(ROUND_HALF_UP))
    elif e.get("tempo_seg"):
        segundos = e["tempo_seg"]
    else:
        raise ConsultaInvalida("Diga quantos minutos: esta etapa não tem tempo definido.")
    nome = (nome or "").strip() or e.get("instrucao", "") or "Cronômetro"
    nome = nome[:120]
    r, rep = _uma_vez("iniciar_cronometro", {"producao": p.id, "nome": nome, "segundos": segundos},
                      lambda chave: producao.iniciar_cronometro(producao_id=p.id, nome=nome, segundos=segundos,
                                                                autor=autor, canal=canal, chave=chave))
    return _feito(f"Cronômetro de {fmt_min(segundos)} min ligado: {nome.rstrip('.')}.", r, rep, producao_id=p.id)


def parar_cronometro(*, nome="", producao_id=None, autor, canal):
    p = producao_alvo(producao_id)
    rodando = list(p.cronometros.filter(parado_em__isnull=True).order_by("fim"))
    if not rodando:
        raise ConsultaInvalida("Nenhum cronômetro ligado nesta produção.", 404)
    c = escolher(rodando, nome or "", oque="cronômetro ligado")
    r, rep = _uma_vez("parar_cronometro", {"cronometro": c.id}, lambda chave: producao.parar_cronometro(
        cronometro_id=c.id, autor=autor, canal=canal, chave=chave))
    return _feito(f"Cronômetro desligado: {c.nome.rstrip('.')}.", r, rep, producao_id=p.id)


def registrar_etiqueta(*, produto, conservacao="", copias=None, lote="", autor, canal):
    estado = _estado(conservacao) if conservacao else ""
    l, estado, saldo = resolver_porcao(produto, estado, lote)
    copias = _inteiro(copias, "copias") if copias else int(saldo)
    r, rep = _uma_vez("registrar_etiqueta", {"lote": l.id, "estado": estado, "copias": copias},
                      lambda chave: registrar_impressao(lote_id=l.id, estado=estado, copias=copias,
                                                        autor=autor, canal=canal, chave=chave))
    tipo = "Reimpressão" if r["reimpressao"] else "Impressão"
    dito = (f"{tipo} de {copias} etiqueta{'s' if copias > 1 else ''} registrada: {l.item.nome}, "
            f"lote {l.codigo or 'sem código'}, {estado}.")
    return _feito(dito, r, rep, lote_id=l.id)


# --- nível 2: monta a proposta ---------------------------------------------

def _proposta(operacao, parametros, resumir, autor, canal):
    p = propostas.propor(operacao, parametros, resumir, autor=autor, canal=canal)
    return {"confirmar": f"{p.resumo}. Confirma?", "proposta_id": p.id,
            "expira_em": timezone.localtime(p.expira_em).isoformat(timespec="seconds")}


def propor_iniciar_producao(*, produto, unidades, forma="cru", autor, canal):
    prod = resolver_produto(produto)
    unidades, forma = _inteiro(unidades, "unidades"), _forma(forma)
    return _proposta("iniciar_producao", {"produto_id": prod.id, "unidades": unidades, "forma": forma},
                     lambda r: f"Iniciar a produção de {unidades} {prod.nome}, {forma}", autor, canal)


def propor_concluir_producao(*, quantidade_boa, conservacao, perdas=0, motivo_perdas="", anotacao="",
                             validade="", justificativa="", producao_id=None, autor, canal):
    p = producao_alvo(producao_id)
    boa, perdas = _inteiro(quantidade_boa, "quantidade_boa"), _inteiro(perdas or 0, "perdas")
    estado = _estado(conservacao)
    parametros = {"producao_id": p.id, "quantidade_boa": boa, "perdas": perdas, "perda_motivo": motivo_perdas,
                  "estado": estado, "validade_manual": _data(validade, "validade"), "justificativa": justificativa,
                  "anotacao": anotacao, "confirmar_perda_total": boa == 0}

    def resumir(r):
        t = f"Concluir a produção {p.id} de {p.unidades} {p.produto.nome}: "
        perda = f"{perdas} perdida{'s' if perdas > 1 else ''} ({motivo_perdas.strip()})" if perdas else ""
        if boa == 0:
            return t + "PERDA TOTAL, nenhuma unidade boa" + (f", {perda}" if perda else "")
        lote = Lote.objects.get(id=r["lote_id"])
        return (t + f"{boa} boa{'s' if boa > 1 else ''}" + (f", {perda}" if perda else "")
                + f", {estado}, validade {_data_br(lote.validade)}")

    return _proposta("concluir_producao", parametros, resumir, autor, canal)


def propor_cancelar_producao(*, motivo, producao_id=None, autor, canal):
    p = producao_alvo(producao_id)
    return _proposta("cancelar_producao", {"producao_id": p.id, "motivo": motivo},
                     lambda r: f"Cancelar a produção {p.id} de {p.unidades} {p.produto.nome} (motivo: {motivo.strip()})",
                     autor, canal)


def propor_mudar_conservacao(*, produto, para, quantidade=None, de="", lote="", validade="", justificativa="",
                             autor, canal):
    para = _estado(para, "para")
    l, de, saldo = resolver_porcao(produto, _estado(de, "de") if de else "", lote)
    q = _inteiro(quantidade, "quantidade") if quantidade else int(saldo)
    parametros = {"lote_id": l.id, "quantidade": q, "de": de, "para": para,
                  "validade_manual": _data(validade, "validade"), "justificativa": justificativa}

    def resumir(r):
        manual = " (informada)" if r["validade_manual"] else ""
        return (f"Passar {fmt_qtd(Decimal(q), l.item.unidade_base)} de {l.item.nome}, lote {l.codigo or 'sem código'}, "
                f"de {de} para {para}, validade {_data_br(r['validade'])}{manual}")

    return _proposta("transferir_estado", parametros, resumir, autor, canal)


def propor_entrada_estoque(*, item, quantidade, unidade, custo_total, motivo, validade="", lote="", autor, canal):
    i = escolher(Item.objects.filter(ativo=True).order_by("nome"), item, oque="item")
    parametros = {"item_id": i.id, "quantidade": _decimal(quantidade, "quantidade"), "unidade": unidade,
                  "custo_total": _decimal(custo_total, "custo_total"), "motivo": motivo, "lote_codigo": lote,
                  "validade": _data(validade, "validade")}

    def resumir(r):
        t = f"Entrada de {fmt_qtd(Decimal(r['quantidade_base']), i.unidade_base)} de {i.nome} por {_reais(custo_total)}"
        if parametros["validade"]:
            t += f", validade {_data_br(parametros['validade'])}"
        return t + f" (motivo: {motivo.strip()})"

    return _proposta("entrada_manual", parametros, resumir, autor, canal)


def propor_criar_tamanho(*, salgado, peso_g, oleo_por_unidade=None, autor, canal):
    ficha = escolher(Ficha.objects.filter(tipo="produto").order_by("nome"), salgado, oque="salgado")
    oleo = _decimal(oleo_por_unidade, "oleo_por_unidade") if oleo_por_unidade is not None else None
    parametros = {"ficha_id": ficha.id, "peso_g": _decimal(peso_g, "peso_g"), "oleo_ref_un": oleo}
    return _proposta("criar_tamanho", parametros,
                     lambda r: f"Criar o tamanho {r['nome']}" + (f", óleo de {_reais(oleo)} por unidade frita" if oleo else ""),
                     autor, canal)


def _depois(p) -> str:
    if p.operacao == "iniciar_producao":
        prod = Producao.objects.get(id=p.resultado["producao_id"])
        return f" É a produção {prod.id}. {descrever_etapa(prod)} {_falta_pesar(prod)}"
    return ""


def confirmar(proposta_id, *, autor):
    p = propostas.confirmar(_inteiro(proposta_id, "proposta_id"), autor=autor)
    return {"dito": f"Feito: {p.resumo}.{_depois(p)}", "proposta_id": p.id, "resultado": p.resultado}


def recusar(proposta_id, *, autor):
    p = propostas.recusar(_inteiro(proposta_id, "proposta_id"), autor=autor)
    return {"dito": f"Certo, não gravei nada: {p.resumo}.", "proposta_id": p.id}
