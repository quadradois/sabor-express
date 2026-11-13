"""Geradores da caixa de decisões: cada um olha o estado atual e devolve o que deveria estar na caixa.

Os geradores só leem (usam as consultas que já existem); quem grava é `servicos.sincronizar`, uma
operação do núcleo por gerador. Rodar de novo não duplica nada (ver `Decisao.assunto`).
`rodar_rotina` é o que o comando `manage.py rotina_diaria` chama.
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from cadastros.models import Item
from compras.consultas import compras_em_aberto
from estoque.servicos import alocar_porcoes, consumos_pendentes, itens_abaixo_do_minimo, porcoes, validade_porcao
from financeiro.consultas import avisos_de_ajuste, contas_a_vencer, contas_vencidas, receber_vencidas
from producao.models import LinhaPreparo, Producao
from vendas.consultas import encomendas, sobras_fritas
from vendas.models import Reserva
from web.templatetags.formato import dinheiro, quantidade

from .consultas import DIAS_ENCOMENDAS, DIAS_RECEBIMENTO, DIAS_VALIDADE
from .servicos import expirar_decisoes, sincronizar

DIAS_CONTAS = 3  # a caixa avisa a conta que vence em até 3 dias (o resumo mostra a semana)
VALIDADE_DECISAO = timedelta(days=7)  # decisão com operação expira e é gerada de novo, com números novos
# sugestão de ficha (critério conservador): as últimas N produções concluídas da versão atual da ficha,
# todas desviando para o mesmo lado em mais que o limite
FICHA_PRODUCOES = 5
FICHA_DESVIO_RENDIMENTO = Decimal("0.05")  # rendimento real = boas ÷ planejadas (PRD), fora de 95%–105%
FICHA_DESVIO_INGREDIENTE = Decimal("0.10")  # usado ÷ previsto de um ingrediente, fora de 90%–110%


def _data(d):
    return f"{d:%d/%m}"


def _quando(dias):
    return {0: "hoje", 1: "amanhã"}.get(dias, f"em {dias} dias")


def _estado(e):
    return f", {e}" if e else ""


def _pct(r: Decimal) -> str:
    return f"{(r * 100).quantize(Decimal('1'), ROUND_HALF_UP)}%"


def lotes_vencidos(hoje):
    return [{"assunto": f"lote_vencido:{p['lote_id']}:{p['estado']}",
             "texto": f"{p['item']} venceu em {_data(p['validade'])}: {quantidade(p['saldo'], p['unidade_base'])} "
                      f"no lote {p['codigo']}{_estado(p['estado'])}. Lote vencido só pode ser descartado.",
             "detalhes": p}
            for p in porcoes(ate=hoje - timedelta(days=1), hoje=hoje)]


def lotes_vencendo(hoje):
    return [{"assunto": f"lote_vencendo:{p['lote_id']}:{p['estado']}:{p['validade']}",
             "texto": f"{p['item']} vence {_quando(p['dias'])} ({_data(p['validade'])}): "
                      f"{quantidade(p['saldo'], p['unidade_base'])} no lote {p['codigo']}{_estado(p['estado'])}.",
             "detalhes": p}
            for p in porcoes(ate=hoje + timedelta(days=DIAS_VALIDADE), hoje=hoje) if not p["vencido"]]


def estoque_baixo(hoje):
    return [{"assunto": f"estoque_baixo:{i['item_id']}",
             "texto": f"{i['item']} está abaixo do mínimo: tem {quantidade(i['disponivel'], i['unidade_base'])}, "
                      f"o mínimo é {quantidade(i['minimo'], i['unidade_base'])}.",
             "detalhes": i}
            for i in itens_abaixo_do_minimo(hoje=hoje)]


def _conta(p):
    quem = p["fornecedor"] or p["descricao"]
    return f"{quem}, parcela {p['numero']} de {p['de']}, {dinheiro(p['saldo'])}"


def contas_vencidas_(hoje):
    return [{"assunto": f"conta_vencida:{p['parcela_id']}",
             "texto": f"Conta vencida: {_conta(p)}, venceu em {_data(p['vencimento'])}.", "detalhes": p}
            for p in contas_vencidas(hoje=hoje)]


def contas_a_vencer_(hoje):
    return [{"assunto": f"conta_a_vencer:{p['parcela_id']}",
             "texto": f"Conta a pagar {_quando(p['dias'])} ({_data(p['vencimento'])}): {_conta(p)}.", "detalhes": p}
            for p in contas_a_vencer(dias=DIAS_CONTAS, hoje=hoje)]


def recebimento_atrasado(hoje):
    saida = []
    for c in compras_em_aberto():
        dias = (hoje - c["data"]).days
        if dias < DIAS_RECEBIMENTO:
            continue
        falta = ", ".join(f"{l['item']} ({quantidade(l['pendente'], l['unidade_base'])})" for l in c["pendentes"])
        saida.append({"assunto": f"recebimento_atrasado:{c['compra_id']}",
                      "texto": f"A compra do {c['fornecedor']} de {_data(c['data'])} ainda não chegou toda, "
                               f"há {dias} dias. Falta: {falta}. Receba ou encerre a pendência.",
                      "detalhes": c})
    return saida


def consumo_pendente(hoje):
    """Com um lote que cubra a quantidade toda (o de validade mais próxima), propõe conciliar (design §6.2:
    conciliação espera o "ok"). Sem lote, só avisa."""
    saida, expira = [], timezone.now() + VALIDADE_DECISAO
    for c in consumos_pendentes():
        q = quantidade(c["quantidade"], c["unidade_base"])
        if c["lotes_possiveis"]:
            l = c["lotes_possiveis"][0]
            saida.append({"assunto": f"conciliar:{c['pendente_id']}:{l['lote_id']}",
                          "texto": f"Consumo pendente de {q} de {c['item']} (produção {c['producao_id']}): "
                                   f"baixar do lote {l['codigo']}, que tem {quantidade(l['saldo'], c['unidade_base'])}?",
                          "operacao": "conciliar_consumo",
                          "parametros": {"pendente_id": c["pendente_id"], "lote_id": l["lote_id"]},
                          "detalhes": c, "expira_em": expira})
        else:
            saida.append({"assunto": f"consumo_pendente:{c['pendente_id']}",
                          "texto": f"Consumo pendente de {q} de {c['item']} (produção {c['producao_id']}) "
                                   f"ainda sem lote que cubra. O custo da produção segue pendente.",
                          "detalhes": c})
    return saida


def avisos_ajuste(hoje):
    return [{"assunto": f"aviso_ajuste:{a['aviso_id']}",
             "texto": f"{a['texto']} Diga o que foi feito com o fornecedor para resolver o aviso.", "detalhes": a}
            for a in avisos_de_ajuste()]


def _razao(a, b) -> Decimal:
    return (Decimal(a) / Decimal(b)).quantize(Decimal("0.001"), ROUND_HALF_UP)


def _mesmo_lado(razoes, limite) -> bool:
    return all(r < 1 - limite for r in razoes) or all(r > 1 + limite for r in razoes)


def ficha_rendimento(hoje):
    """Sugestão de revisar a ficha (design §6.3.4, só sugere): as últimas FICHA_PRODUCOES produções concluídas
    do produto, na versão atual da ficha, desviaram todas para o mesmo lado no rendimento (boas ÷ planejadas)
    ou no uso de um ingrediente (usado ÷ previsto). Uma produção diferente quebra a sequência."""
    saida = []
    for produto in Item.objects.filter(tipo="produto", ativo=True).select_related("ficha").order_by("nome"):
        versao = produto.ficha.versoes.last()
        if versao is None:
            continue
        prods = list(Producao.objects.filter(produto=produto, versao=versao, status="concluida")
                     .order_by("-encerrada_em", "-id")[:FICHA_PRODUCOES])
        if len(prods) < FICHA_PRODUCOES:
            continue
        rend = [_razao(p.quantidade_boa, p.unidades) for p in prods]
        achados, detalhes_itens = [], []
        if _mesmo_lado(rend, FICHA_DESVIO_RENDIMENTO):
            achados.append(f"renderam em média {_pct(sum(rend) / len(rend))} das unidades planejadas")
        consumo = {}  # item -> [razão por produção]
        for p in prods:
            por_item = {}
            for l in LinhaPreparo.objects.filter(producao=p).select_related("item"):
                prev, usado = por_item.get(l.item, (Decimal("0"), Decimal("0")))
                por_item[l.item] = (prev + l.previsto, usado + (l.usado or 0))
            for item, (prev, usado) in por_item.items():
                if prev > 0:
                    consumo.setdefault(item, []).append(_razao(usado, prev))
        for item, razoes in sorted(consumo.items(), key=lambda x: x[0].nome):
            if len(razoes) == len(prods) and _mesmo_lado(razoes, FICHA_DESVIO_INGREDIENTE):
                media = sum(razoes) / len(razoes)
                achados.append(f"usaram em média {_pct(media)} do {item.nome} previsto")
                detalhes_itens.append({"item_id": item.id, "item": item.nome, "razoes": razoes,
                                       "media": media.quantize(Decimal("0.001"), ROUND_HALF_UP)})
        if not achados:
            continue
        saida.append({
            "assunto": f"ficha:{produto.id}:{versao.id}",
            "texto": f"Sugestão para a ficha de {produto.nome}: as últimas {len(prods)} produções "
                     + "; ".join(achados) + ". Se fizer sentido, revise a ficha (cria uma versão nova).",
            "detalhes": {"produto_id": produto.id, "ficha_id": produto.ficha_id, "versao": versao.numero,
                         "producoes": [{"producao_id": p.id, "unidades": p.unidades, "boas": p.quantidade_boa,
                                        "perdas": p.perdas, "rendimento": r} for p, r in zip(prods, rend)],
                         "rendimento_medio": (sum(rend) / len(rend)).quantize(Decimal("0.001"), ROUND_HALF_UP),
                         "ingredientes": detalhes_itens},
        })
    return saida


def _dia(e, hoje):
    dias = e["dias"]
    if dias < 0:
        return f"para {_data(e['entrega_data'])}, que já passou"
    return {0: "para hoje", 1: "para amanhã"}.get(dias, f"para {_data(e['entrega_data'])}")


def encomenda_sem_estoque(hoje):
    """Encomendas abertas até hoje + DIAS_ENCOMENDAS (e as atrasadas) com algo sem reserva ou reservado em
    lote que vence antes da entrega. Se há estoque livre que serve, propõe completar a reserva (RF-VEN-07:
    com confirmação, nunca sozinho); se não, avisa o que falta produzir."""
    saida, expira = [], timezone.now() + VALIDADE_DECISAO
    for e in encomendas(ate=hoje + timedelta(days=DIAS_ENCOMENDAS), hoje=hoje):
        limite = max(hoje, e["entrega_data"])
        faltas, cobre = [], Decimal("0")
        for i in e["itens"]:
            ruins = sum((r.quantidade for r in Reserva.objects.filter(item_encomenda_id=i["item_encomenda_id"],
                                                                      situacao="ativa").select_related("lote")
                         if (v := validade_porcao(r.lote, r.estado)) and v < limite), Decimal("0"))
            falta = i["falta"] + ruins
            if falta <= 0:
                continue
            alocacao, _ = alocar_porcoes(Item.objects.get(id=i["produto_id"]), falta, forma=i["forma"], estado=i["estado"], hoje=hoje,
                                         valida_ate=e["entrega_data"])
            cobre += sum((q for _, q in alocacao), Decimal("0"))
            faltas.append(f"{quantidade(falta, 'un')} de {i['produto']} {i['forma']} {i['estado']}")
        if not faltas:
            continue
        texto = f"Encomenda {e['encomenda_id']} de {e['cliente']} {_dia(e, hoje)}: falta reservar " + ", ".join(faltas)
        if cobre > 0:
            saida.append({"assunto": f"completar_reserva:{e['encomenda_id']}",
                          "texto": f"{texto}. Há {quantidade(cobre, 'un')} no estoque que servem: reservar agora?",
                          "operacao": "completar_reserva", "parametros": {"encomenda_id": e["encomenda_id"]},
                          "detalhes": e, "expira_em": expira})
        else:
            saida.append({"assunto": f"encomenda_sem_estoque:{e['encomenda_id']}",
                          "texto": f"{texto}. Não há estoque livre que sirva: é preciso produzir.",
                          "detalhes": e})
    return saida


def receber_vencidas_(hoje):
    return [{"assunto": f"receber_vencida:{p['parcela_id']}",
             "texto": f"{p['cliente'] or p['descricao']} está devendo {dinheiro(p['saldo'])} "
                      f"(parcela {p['numero']} de {p['de']}), que venceu em {_data(p['vencimento'])}.",
             "detalhes": p}
            for p in receber_vencidas(hoje=hoje)]


def sobras_fritas_(hoje):
    """Fritos de dias anteriores ainda com saldo (RF-FRI-03): pedem destino (perda ou outro permitido)."""
    return [{"assunto": f"sobra_frita:{p['lote_id']}:{p['estado']}",
             "texto": f"Sobraram {quantidade(p['saldo'], 'un')} de {p['item']} fritos em {_data(p['frito_em'])} "
                      f"(lote {p['codigo']}). Registre a perda ou o destino das sobras.",
             "detalhes": p}
            for p in sobras_fritas(hoje=hoje, ate_ontem=True)]


GERADORES = {
    "lotes_vencidos": lotes_vencidos,
    "lotes_vencendo": lotes_vencendo,
    "estoque_baixo": estoque_baixo,
    "contas_vencidas": contas_vencidas_,
    "contas_a_vencer": contas_a_vencer_,
    "recebimento_atrasado": recebimento_atrasado,
    "consumo_pendente": consumo_pendente,
    "avisos_ajuste": avisos_ajuste,
    "ficha_rendimento": ficha_rendimento,
    "encomenda_sem_estoque": encomenda_sem_estoque,
    "receber_vencidas": receber_vencidas_,
    "sobras_fritas": sobras_fritas_,
}


def rodar_rotina(*, hoje=None, autor="rotina", canal="sistema") -> dict:
    """Expira o que passou do prazo e roda cada gerador como uma operação própria: a falha de um
    não impede os outros (vai para o relatório e, se aconteceu ao gravar, para a trilha com status "erro")."""
    hoje = hoje or timezone.localdate()
    saida = {"hoje": hoje, "expiradas": expirar_decisoes(autor=autor, canal=canal)["expiradas"], "geradores": {}}
    for origem, gerar in GERADORES.items():
        try:
            saida["geradores"][origem] = sincronizar(origem=origem, itens=gerar(hoje), autor=autor, canal=canal)
        except Exception as e:  # noqa: BLE001 — a rotina segue; o erro vai para o relatório e para a trilha
            saida["geradores"][origem] = {"erro": str(e)}
    return saida
