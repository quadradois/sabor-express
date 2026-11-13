"""Telas da caixa de decisões, do resumo do dia ("Hoje") e do histórico de operações.
Só chamam serviços e consultas do núcleo."""
from datetime import date
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from backup.situacao import situacao_backup
from decisoes import consultas as dc
from decisoes import servicos as ds
from decisoes.models import Decisao
from estoque.models import DESTINOS_PERDA
from nucleo.models import RegistroOperacao
from nucleo.operacoes import RegraViolada

ORIGENS = {
    "lotes_vencidos": "Lote vencido", "lotes_vencendo": "Lote vencendo", "estoque_baixo": "Estoque baixo",
    "contas_vencidas": "Conta vencida", "contas_a_vencer": "Conta a vencer",
    "recebimento_atrasado": "Compra que não chegou", "consumo_pendente": "Consumo pendente",
    "avisos_ajuste": "Aviso de ajuste", "ficha_rendimento": "Sugestão de ficha", "agente": "Pedido do agente",
    "encomenda_sem_estoque": "Encomenda sem estoque", "receber_vencidas": "Cliente atrasado",
    "sobras_fritas": "Sobra de frito", "lotes_deixados": "Lote deixado para trás",
}
SITUACOES = {"pendente": "Pendentes", "decididas": "Decididas", "aprovada": "Aprovadas", "recusada": "Recusadas",
             "expirada": "Expiradas", "sem_efeito": "Sem efeito"}
POR_PAGINA = 30


def _links(d):
    """Links para a tela de origem, a partir dos `detalhes` da decisão."""
    det = d["detalhes"] or {}
    links = []
    if det.get("lote_id"):
        links.append(("Ver lote", ("lote", det["lote_id"])))
    if d["origem"] == "encomenda_sem_estoque" and det.get("encomenda_id"):
        links.append(("Ver encomenda", ("encomenda", det["encomenda_id"])))
    elif d["origem"] == "sobras_fritas":
        links.append(("Ver sobras", ("sobras",)))
    if det.get("tipo") == "receber":  # parcela a receber: não é conta a pagar
        links.append(("Ver contas a receber", ("receber",)))
    elif det.get("compra_id"):
        links.append(("Ver compra", ("compra", det["compra_id"])))
    elif det.get("conta_id"):
        links.append(("Ver contas", ("contas",)))
    if det.get("pendente_id"):
        links.append(("Ver consumos pendentes", ("consumos",)))
    if det.get("aviso_id"):
        links.append(("Ver avisos de ajuste", ("avisos",)))
    if det.get("producao_id"):
        links.append(("Ver produção", ("producao", det["producao_id"])))
    elif det.get("produto_id") and det.get("producoes"):
        links.append(("Ver produções", ("producoes",)))
    return links


def _conferencia(d, next_url):
    """Os três caminhos da conferência do vencido (`detalhes.conferencia`): já saiu, está aqui, não sei."""
    det = d["detalhes"] or {}
    conf = det.get("conferencia")
    if d["origem"] != "lotes_vencidos" or not conf or not det.get("lote_id"):
        return None
    base = {"lote": det["lote_id"], "estado": det.get("estado", "")}
    contar = f"{reverse('contar_lote', args=[det['lote_id']])}?{urlencode({'estado': det.get('estado', ''), 'next': next_url})}"
    if conf["ja_saiu"]["servico"] == "registrar_venda":
        ja_saiu = f"{reverse('vender')}?{urlencode({**base, 'data_venda': str(det.get('validade') or '')})}"
    else:  # ingrediente: o que "já foi usado" se conta
        ja_saiu = contar
    return {"nome": det.get("nome", ""), "ja_saiu_url": ja_saiu, "ja_saiu_rotulo": conf["ja_saiu"]["resposta"].capitalize(),
            "contar_url": contar, "lote_id": det["lote_id"], "estado": det.get("estado", ""),
            "saldo": det.get("saldo", 0), "destinos": DESTINOS_PERDA}


def _enriquecer(d, next_url="/decisoes/"):
    d["conferencia"] = _conferencia(d, next_url)
    d["origem_rotulo"] = ORIGENS.get(d["origem"], d["origem"].replace("_", " ").capitalize())
    d["links"] = _links(d)
    d["situacao_rotulo"] = dict(Decisao.SITUACOES).get(d["situacao"], d["situacao"])
    return d


@login_required
def caixa(request):
    if request.method == "POST":
        post = request.POST
        try:
            chave = post.get("chave")
            if not chave:
                raise RegraViolada("Formulário sem chave: recarregue a página e tente de novo.")
            try:
                decisao_id = int(post.get("decisao"))
            except (TypeError, ValueError):
                raise RegraViolada("Decisão não encontrada.")
            kw = {"autor": request.user.username, "canal": "web", "chave": chave}
            if post.get("acao") == "recusar":
                ds.recusar_decisao(decisao_id=decisao_id, motivo=post.get("motivo", ""), **kw)
                messages.success(request, "Decisão recusada.")
            else:
                r = ds.aprovar_decisao(decisao_id=decisao_id, **kw)
                messages.success(request, "Ciente. Anotado." if r["tipo"] == "aviso" else "Decisão aprovada e executada.")
        except RegraViolada as e:
            messages.error(request, str(e))
        destino = request.POST.get("next", "")
        return redirect(destino if destino.startswith("/decisoes/") else "caixa")
    filtro = request.GET.get("situacao", "pendente")
    if filtro not in SITUACOES:
        filtro = "pendente"
    if filtro == "pendente":
        itens = dc.decisoes()
    elif filtro == "decididas":
        itens = [d for d in dc.decisoes(situacao=None) if d["situacao"] != "pendente"]
    else:
        itens = dc.decisoes(situacao=filtro)
    itens = [_enriquecer(d, request.get_full_path()) for d in itens]
    return render(request, "web/caixa.html", {
        "itens": itens, "filtro": filtro, "situacoes": SITUACOES,
        "next": request.get_full_path(),
        "decisoes": [d for d in itens if d["tipo"] == "decisao"], "avisos": [d for d in itens if d["tipo"] == "aviso"]})


@login_required
def hoje(request):
    resumo = dc.resumo_do_dia()
    backup = situacao_backup()
    caixa_itens = [_enriquecer(d, reverse("caixa")) for d in resumo["decisoes"]]
    return render(request, "web/inicio.html", {
        "r": resumo, "t": resumo["totais"], "backup": backup, "caixa": caixa_itens[:5],
        "sem_estoque": set(resumo["encomendas"]["sem_estoque"]),
        "atrasadas": set(resumo["a_chegar"]["atrasadas"]), "custo_pendente": resumo["producoes"]["custo_pendente"]})


def _data(txt):
    try:
        return date.fromisoformat((txt or "").strip()) if (txt or "").strip() else None
    except ValueError:
        return False


@login_required
def historico(request):
    g = request.GET
    de, ate = _data(g.get("de")), _data(g.get("ate"))
    if "de" not in g and "ate" not in g:
        de = ate = timezone.localdate()
    if de is False or ate is False:
        messages.error(request, "Data inválida: use o formato AAAA-MM-DD.")
        de = None if de is False else de
        ate = None if ate is False else ate
    status = g.get("status", "") if g.get("status", "") in ("sucesso", "erro") else ""
    nome = g.get("nome", "") if g.get("nome", "") in dc.ROTULOS else ""
    itens = dc.historico_operacoes(de=de, ate=ate, autor=g.get("autor", "").strip(), canal=g.get("canal", "").strip(),
                                   nome=nome, status=status, limite=None)
    pagina = Paginator(itens, POR_PAGINA).get_page(g.get("pagina"))
    filtros = g.copy()
    filtros.pop("pagina", None)
    return render(request, "web/historico.html", {
        "pagina": pagina, "total": len(itens), "rotulos": sorted(dc.ROTULOS.items(), key=lambda kv: kv[1]),
        "autores": sorted(set(RegistroOperacao.objects.values_list("autor", flat=True))),
        "canais": sorted(set(RegistroOperacao.objects.values_list("canal", flat=True))),
        "f": {"de": de.isoformat() if de else "", "ate": ate.isoformat() if ate else "",
              "autor": g.get("autor", ""), "canal": g.get("canal", ""), "nome": nome, "status": status},
        "query": filtros.urlencode()})
