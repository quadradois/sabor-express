"""Ferramentas do agente no padrão MCP (voz, Telegram e texto usam as mesmas).

Cada ferramenta é uma função síncrona comum, registrada com um decorador que
diz o tipo dela. O decorador cuida do que é igual para todas: rodar o ORM fora
do loop async (sync_to_async) e devolver erro de entrada como
{"erro": "..."} em vez de exceção. `criar_servidor()` monta o FastMCP a partir
do registro.

As de escrita (`@escrita(nivel)`) seguem a alçada aprovada pelo dono:
nível 1 grava direto e devolve `dito` (o que foi feito); nível 2 não grava,
devolve `confirmar` + `proposta_id` e só `confirmar_proposta` executa; o nível
3 ("nunca") não tem ferramenta e o núcleo recusa. Toda gravação passa por
`nucleo.operacoes.executar` com canal="agente". A lógica está em
`agente/acoes.py`, `agente/compras.py`, `agente/decisoes.py`, `agente/vendas.py` e
`agente/propostas.py`.
"""

import functools
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Required, TypedDict

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import acoes, compras, consultas, decisoes, vendas
from .consultas import ConsultaInvalida
from nucleo.operacoes import RegraViolada

INSTRUCOES = (
    "Ferramentas da cozinha do Sabor Express. O sistema faz todas as contas: "
    "nunca calcule quantidades, saldos ou custos por conta própria; use o campo "
    "'texto' das quantidades ao falar. Se vier 'erro', explique ao usuário; se vier "
    "'opcoes', pergunte qual delas ele quis dizer. "
    "Ao gravar: se vier 'dito', fale essa frase (já foi feito). Se vier 'confirmar', NADA foi "
    "gravado ainda: leia o texto de 'confirmar' em voz alta e espere a resposta; só chame "
    "confirmar_proposta com o 'proposta_id' depois de o usuário dizer sim. Se ele disser não ou "
    "mudar o pedido, chame recusar_proposta. Nunca confirme por conta própria. "
    "Se vier 'repetida', a mesma chamada já tinha sido feita há instantes e não foi gravada de novo. "
    "Dinheiro: o sistema nunca paga nada; registrar_pagamento só anota que o dono pagou. "
    "Valores falados chegam em reais (ex.: 90 ou 12.5). "
    "Caixa de decisões: cada item tem um número (decisao_id), que é o que o dono diz (\"aprova a doze\"); "
    "aprovar uma decisão sempre passa pelo 'confirmar'; recusar exige o motivo dito pelo dono. "
    "Vendas e encomendas: passe produto, apresentação e cliente pelo nome falado; o preço é sempre o da tabela "
    "(nunca diga um preço que não veio do sistema). registrar_recebimento só anota que o cliente pagou."
)

AUTOR = "agente-mcp"
CANAL = "agente"


@dataclass(frozen=True)
class Ferramenta:
    func: Callable[..., dict]
    anotacoes: ToolAnnotations
    nivel: int = 0  # 0 leitura; 1 faz e repete; 2 repete e espera o sim

    @property
    def nome(self):
        return self.func.__name__


REGISTRO: list[Ferramenta] = []


def _rodar(func):
    """Chamada síncrona protegida: conexões frescas e erro de regra virando dict."""
    @functools.wraps(func)
    def _sync(*args, **kwargs):
        close_old_connections()
        try:
            return func(*args, **kwargs)
        except ConsultaInvalida as e:
            return e.como_dict()
        except RegraViolada as e:
            return {"erro": str(e)}
        finally:
            close_old_connections()

    @functools.wraps(func)
    async def _async(*args, **kwargs) -> dict[str, Any]:
        return await sync_to_async(_sync, thread_sensitive=True)(*args, **kwargs)
    return _async


def leitura(func):
    """Ferramenta de consulta: não grava nada e pode ser repetida à vontade."""
    REGISTRO.append(Ferramenta(func, ToolAnnotations(readOnlyHint=True, idempotentHint=True,
                                                     openWorldHint=False)))
    return func


def escrita(nivel: int):
    """Ferramenta que grava. Nível 1 executa e devolve 'dito'; nível 2 só propõe (ver propostas.py)."""
    def registrar(func):
        REGISTRO.append(Ferramenta(func, ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                         idempotentHint=False, openWorldHint=False), nivel))
        return func
    return registrar


def _sem_refs(schema: dict) -> dict:
    """Esquema com os `$defs` embutidos: o Gemini não resolve `$ref` nas declarações de função."""
    defs = schema.get("$defs", {})

    def troca(no):
        if isinstance(no, dict):
            if "$ref" in no:
                return troca(defs[no["$ref"].rsplit("/", 1)[-1]])
            return {k: troca(v) for k, v in no.items() if k != "$defs"}
        if isinstance(no, list):
            return [troca(v) for v in no]
        return no
    return troca(schema)


def criar_servidor() -> FastMCP:
    mcp = FastMCP("sabor-express", instructions=INSTRUCOES, log_level="WARNING")
    for f in REGISTRO:
        mcp.add_tool(_rodar(f.func), name=f.nome, description=inspect.cleandoc(f.func.__doc__),
                     annotations=f.anotacoes)
        tool = mcp._tool_manager.get_tool(f.nome)
        tool.parameters = _sem_refs(tool.parameters)
    return mcp


# --- consultas -------------------------------------------------------------

@leitura
def consultar_estoque(busca: str = "") -> dict:
    """Saldo atual de ingredientes e produtos, com o estoque mínimo e se está abaixo dele.
    Use 'busca' com parte do nome (ex.: "farinha"); vazio lista tudo."""
    return consultas.estoque(busca)


@leitura
def ver_validades(dias: int = 3) -> dict:
    """Lotes com estoque que vencem nos próximos 'dias' dias (e os já vencidos), do mais urgente ao menos."""
    return consultas.validades(dias)


@leitura
def buscar_produtos(busca: str = "") -> dict:
    """Produtos vendidos (salgados por tamanho), com peso da unidade e quantas unidades há em estoque.
    Use 'busca' com parte do nome; vazio lista todos."""
    return consultas.produtos(busca)


@leitura
def calcular_receita(produto: str, unidades: int) -> dict:
    """Quanto de cada ingrediente é preciso para produzir 'unidades' de um produto, quanto falta
    no estoque e se dá para produzir. 'produto' é o nome falado (ex.: "coxinha 25 g")."""
    p = consultas.resolver_produto(produto)
    return consultas.receita(p.id, unidades)


@leitura
def ver_producoes(status: str = "andamento") -> dict:
    """Lista as produções (as 20 mais recentes). 'status': andamento, concluida, cancelada ou todas."""
    return consultas.producoes(status)


@leitura
def buscar_fornecedores(busca: str = "") -> dict:
    """Fornecedores cadastrados (nome, contato, se está ativo). 'busca' com parte do nome; vazio lista todos."""
    return compras.buscar_fornecedores(busca)


@leitura
def ver_compras_em_aberto(fornecedor: str = "") -> dict:
    """Compras que ainda esperam entrega (toda ou parte), com o que falta de cada item. 'fornecedor' filtra pelo nome."""
    return compras.ver_compras_em_aberto(fornecedor)


@leitura
def ver_falta_receber(fornecedor: str = "", item: str = "") -> dict:
    """Itens comprados que ainda não chegaram, com quantidade e há quantos dias. Filtros pelo nome falado."""
    return compras.ver_falta_receber(fornecedor, item)


@leitura
def ver_compra(compra_id: int) -> dict:
    """Detalhe de uma compra: itens, o que chegou e o que falta, parcelas da conta e avisos de ajuste."""
    return compras.ver_compra(compra_id)


@leitura
def ver_contas(situacao: str = "todas", dias: int = 7, fornecedor: str = "") -> dict:
    """Contas a pagar em aberto, com o total já somado. 'situacao': todas, vencidas ou a_vencer
    (a_vencer = vencem de hoje até daqui a 'dias' dias). 'fornecedor' filtra pelo nome."""
    return compras.ver_contas(situacao, dias, fornecedor)


@leitura
def ver_divida_fornecedores(fornecedor: str = "") -> dict:
    """Quanto se deve a cada fornecedor (e quanto já venceu), do maior para o menor, com o total geral.
    Com 'fornecedor' ("quanto devo ao Atacadão?"), só ele e a parcela mais antiga."""
    return compras.ver_divida_fornecedores(fornecedor)


@leitura
def ver_avisos_de_ajuste() -> dict:
    """Avisos em aberto para ajustar uma conta (item não entregue, devolução): o valor da conta não muda sozinho."""
    return compras.ver_avisos_de_ajuste()


@leitura
def ver_consumos_pendentes(item: str = "") -> dict:
    """Ingredientes usados em produção sem estoque, à espera de conciliar com um lote, e se já há lote que cubra."""
    return compras.ver_consumos_pendentes(item)


@leitura
def ultimo_preco(item: str) -> dict:
    """Quanto custou um item na última compra (por quilo, litro ou unidade, com frete e desconto rateados)."""
    return compras.ultimo_preco(item)


@leitura
def ver_producao(producao_id: int) -> dict:
    """Detalhes de uma produção: etapa atual, o que falta pesar, cronômetros rodando, perdas e custo."""
    return consultas.producao(producao_id)


@leitura
def ver_resumo_do_dia() -> dict:
    """"Como está o dia?", "alguma novidade?": o retrato do dia (vencidos, estoque baixo, contas, compras a chegar,
    produções, caixa de decisões, backup atrasado). O 'texto' traz os totais e os três assuntos mais urgentes."""
    return decisoes.ver_resumo_do_dia()


@leitura
def ver_decisoes(tipo: str = "", origem: str = "") -> dict:
    """"O que tem para decidir?": itens pendentes da caixa, cada um com o número para o dono citar. Decisões para
    aprovar vêm antes dos avisos. 'tipo': decisao, aviso ou vazio (todos). 'origem' filtra pelo assunto falado
    (ex.: "vencido", "contas", "estoque baixo", "consumo pendente", "ficha")."""
    return decisoes.ver_decisoes(tipo, origem)


@leitura
def ver_decisao(decisao_id: int) -> dict:
    """Uma decisão da caixa em detalhe, pelo número: o texto, desde quando está lá, quem decidiu e o motivo."""
    return decisoes.ver_decisao(decisao_id)


@leitura
def ver_historico(periodo: str = "hoje", autor: str = "", canal: str = "", operacao: str = "",
                  so_erros: bool = False) -> dict:
    """"O que foi feito hoje?": operações gravadas no sistema, das mais recentes. 'periodo': hoje, ontem, semana,
    mes ou AAAA-MM-DD. 'autor' (quem fez), 'canal' (voz, tela ou sistema; sem canal, a rotina automática fica de
    fora) e 'operacao' (ex.: "compra", "pagamento", "produção") filtram. 'so_erros' mostra as tentativas recusadas."""
    return decisoes.ver_historico(periodo, autor, canal, operacao, so_erros)


@leitura
def ver_backup() -> dict:
    """"Quando foi o último backup?": data e hora do último backup, quantos há guardados e se está atrasado."""
    return decisoes.ver_backup()

# vendas, encomendas, fritura e contas a receber (Plano 6)

@leitura
def ver_precos(produto: str = "") -> dict:
    """"Quanto custa a caixa de coxinha?": tabela de preços (varejo e atacado) de cada jeito de vender — unidade,
    caixa com 25... em cada forma (cru/frito) e conservação — e quantas dá para vender agora. 'produto' filtra."""
    return vendas.ver_precos(produto)


@leitura
def ver_estoque_para_venda(produto: str = "") -> dict:
    """"Quanta coxinha tem para vender?": salgados prontos por forma e conservação, com o livre para vender, o
    reservado para encomendas e o vencido. 'produto' filtra pelo nome."""
    return vendas.ver_estoque_para_venda(produto)


@leitura
def buscar_clientes(busca: str = "") -> dict:
    """Clientes cadastrados (nome, contato, se está ativo). 'busca' com parte do nome; vazio lista todos."""
    return vendas.buscar_clientes(busca)


@leitura
def ver_vendas(periodo: str = "hoje", cliente: str = "") -> dict:
    """"Quanto vendi hoje?": vendas do período com os totais já somados (total, recebido na hora por forma de
    pagamento, a prazo, por produto). 'periodo': hoje, ontem, semana, mes ou AAAA-MM-DD. 'cliente' filtra."""
    return vendas.ver_vendas(periodo, cliente)


@leitura
def ver_encomendas(dia: str = "", cliente: str = "") -> dict:
    """"O que tem de encomenda amanhã?": encomendas em aberto (prontas ou faltando reservar), por dia de entrega.
    'dia': hoje, amanhã, um dia da semana, semana (próximos 7 dias) ou AAAA-MM-DD; vazio = todas as em aberto,
    inclusive as atrasadas. 'cliente' filtra pelo nome."""
    return vendas.ver_encomendas(dia, cliente)


@leitura
def ver_encomenda(encomenda_id: int) -> dict:
    """Uma encomenda em detalhe, pelo número: itens, o que está reservado e o que falta, total, sinal e situação."""
    return vendas.ver_encomenda(encomenda_id)


@leitura
def ver_necessidade_producao(dias: int = 3) -> dict:
    """"O que falta produzir?": para as encomendas em aberto até daqui a 'dias' dias, o que falta por produto,
    quanto já está no estoque livre (dá para reservar) e quanto produzir. Não cria produção."""
    return vendas.ver_necessidade_producao(dias)


@leitura
def ver_a_receber(cliente: str = "", situacao: str = "todas", dias: int = 7) -> dict:
    """"Quanto o João deve?", "quem está devendo?": contas a receber de clientes (fiado, venda a prazo, saldo de
    encomenda), com totais já somados. Com 'cliente', só ele e a parcela mais antiga. 'situacao': todas, vencidas
    ou a_vencer (nos próximos 'dias' dias)."""
    return vendas.ver_a_receber(cliente, situacao, dias)


@leitura
def ver_sobras() -> dict:
    """"Sobrou frito?": salgados fritos ainda no estoque (sobras do balcão), de quando são e quanto de cada."""
    return vendas.ver_sobras()


# --- nível 1: faz e repete -------------------------------------------------
# Sem producao_id, valem para a única produção em andamento.

@escrita(1)
def registrar_peso(item: str, quantidade: float, unidade: str = "", lote: str = "",
                   producao_id: int | None = None) -> dict:
    """Registra quanto foi usado de um ingrediente no preparo (ex.: item "requeijão", quantidade 355).
    'unidade' (g, kg, mL, L, un) é opcional; sem ela vale a unidade do ingrediente. 'lote' é o código, se citado."""
    return acoes.registrar_peso(item=item, quantidade=quantidade, unidade=unidade, lote=lote,
                                producao_id=producao_id, autor=AUTOR, canal=CANAL)


@escrita(1)
def usar_previsto(item: str = "", producao_id: int | None = None) -> dict:
    """Marca "usei o previsto": num ingrediente (item) ou, sem item, em todos os que faltam pesar."""
    return acoes.usar_previsto(item=item, producao_id=producao_id, autor=AUTOR, canal=CANAL)


@escrita(1)
def proxima_etapa(producao_id: int | None = None) -> dict:
    """Avança o preparo para a próxima etapa e diz qual é."""
    return acoes.proxima_etapa(producao_id=producao_id, autor=AUTOR, canal=CANAL)


@escrita(1)
def ir_para_etapa(etapa: int, producao_id: int | None = None) -> dict:
    """Vai para a etapa de número 'etapa' do preparo (0 = pesagem dos ingredientes)."""
    return acoes.ir_para_etapa(etapa=etapa, producao_id=producao_id, autor=AUTOR, canal=CANAL)


@escrita(1)
def iniciar_cronometro(minutos: float | None = None, nome: str = "", producao_id: int | None = None) -> dict:
    """Liga um cronômetro do preparo. Sem 'minutos', usa o tempo da etapa atual."""
    return acoes.iniciar_cronometro(minutos=minutos, nome=nome, producao_id=producao_id, autor=AUTOR, canal=CANAL)


@escrita(1)
def parar_cronometro(nome: str = "", producao_id: int | None = None) -> dict:
    """Desliga um cronômetro ligado (pelo nome, se houver mais de um)."""
    return acoes.parar_cronometro(nome=nome, producao_id=producao_id, autor=AUTOR, canal=CANAL)


@escrita(1)
def registrar_etiqueta(produto: str, conservacao: str = "", copias: int | None = None, lote: str = "") -> dict:
    """Registra a impressão de etiquetas de um lote com estoque. 'conservacao': fresco, resfriado ou congelado.
    Sem 'copias', uma por unidade. 'lote' é o código, se houver mais de um."""
    return acoes.registrar_etiqueta(produto=produto, conservacao=conservacao, copias=copias, lote=lote,
                                    autor=AUTOR, canal=CANAL)


@escrita(1)
def cadastrar_fornecedor(nome: str, contato: str = "", documento: str = "") -> dict:
    """Cadastra um fornecedor novo. Só o nome é obrigatório; 'contato' (telefone) e 'documento' (CNPJ/CPF) se ditos."""
    return compras.cadastrar_fornecedor(nome=nome, contato=contato, documento=documento, autor=AUTOR, canal=CANAL)


@escrita(1)
def resolver_aviso(observacao: str, aviso_id: int | None = None) -> dict:
    """Anota o que o dono fez com um aviso de ajuste (ex.: "o fornecedor abateu no boleto").
    Sem 'aviso_id', vale para o único aviso em aberto."""
    return compras.resolver_aviso(observacao=observacao, aviso_id=aviso_id, autor=AUTOR, canal=CANAL)


@escrita(1)
def dar_ciencia(decisao_id: int) -> dict:
    """Dá ciência a um AVISO da caixa (o dono disse "ciente", "já vi", "ok" para um aviso): sai da caixa.
    Não serve para decisão com operação (use aprovar_decisao)."""
    return decisoes.dar_ciencia(decisao_id=decisao_id, autor=AUTOR, canal=CANAL)


@escrita(1)
def recusar_decisao(decisao_id: int, motivo: str) -> dict:
    """Recusa uma decisão da caixa com o motivo dito pelo dono (ex.: "vou comprar amanhã"). Motivo obrigatório:
    sem ele, pergunte por quê. Aviso não se recusa (use dar_ciencia)."""
    return decisoes.recusar_decisao(decisao_id=decisao_id, motivo=motivo, autor=AUTOR, canal=CANAL)


@escrita(1)
def cadastrar_cliente(nome: str, contato: str = "") -> dict:
    """Cadastra um cliente novo (quem compra fiado ou encomenda). Só o nome é obrigatório; 'contato' (telefone,
    endereço) se dito. Nome repetido, mesmo com outra caixa ou sem acento, é recusado."""
    return vendas.cadastrar_cliente(nome=nome, contato=contato, autor=AUTOR, canal=CANAL)


@escrita(1)
def completar_reserva(encomenda_id: int | None = None, cliente: str = "") -> dict:
    """Reserva para uma encomenda o que entrou no estoque ("reserva a encomenda do João"): separa o que houver,
    sem tirar nada do estoque, e troca a reserva de lote que venceria antes da entrega. Acha a encomenda em
    aberto pelo cliente ou pelo número."""
    return vendas.completar_reserva(encomenda_id=encomenda_id, cliente=cliente, autor=AUTOR, canal=CANAL)


# --- nível 2: repete e espera o sim ----------------------------------------
# Não gravam: devolvem 'confirmar' (para ler em voz alta) e 'proposta_id'.

@escrita(2)
def iniciar_producao(produto: str, unidades: int, forma: str = "cru", justificativa_falta: str = "") -> dict:
    """Propõe iniciar uma produção ('forma': cru ou frito). Não grava: pede confirmação.
    Se faltar estoque e o dono quiser começar assim mesmo, passe 'justificativa_falta' com o motivo
    (ex.: "farinha chega à tarde"): o que faltar fica como consumo pendente de conciliar."""
    return acoes.propor_iniciar_producao(produto=produto, unidades=unidades, forma=forma,
                                         justificativa_falta=justificativa_falta, autor=AUTOR, canal=CANAL)


@escrita(2)
def concluir_producao(quantidade_boa: int, conservacao: str, perdas: int = 0, motivo_perdas: str = "",
                      anotacao: str = "", validade: str = "", justificativa: str = "",
                      justificativa_falta: str = "", producao_id: int | None = None) -> dict:
    """Propõe concluir a produção: unidades boas, perdas com motivo e conservação (fresco, resfriado, congelado).
    'validade' (AAAA-MM-DD) e 'justificativa' só se o sistema pedir. 'justificativa_falta': motivo para concluir
    sem estoque do que foi usado (vira consumo pendente). Não grava: pede confirmação."""
    return acoes.propor_concluir_producao(quantidade_boa=quantidade_boa, conservacao=conservacao, perdas=perdas,
                                          motivo_perdas=motivo_perdas, anotacao=anotacao, validade=validade,
                                          justificativa=justificativa, justificativa_falta=justificativa_falta,
                                          producao_id=producao_id, autor=AUTOR, canal=CANAL)


@escrita(2)
def cancelar_producao(motivo: str, producao_id: int | None = None) -> dict:
    """Propõe cancelar a produção em andamento, com o motivo. Não grava: pede confirmação."""
    return acoes.propor_cancelar_producao(motivo=motivo, producao_id=producao_id, autor=AUTOR, canal=CANAL)


@escrita(2)
def mudar_conservacao(produto: str, para: str, quantidade: int | None = None, de: str = "", lote: str = "",
                      validade: str = "", justificativa: str = "") -> dict:
    """Propõe mudar a conservação de um lote (ex.: de resfriado 'para' congelado). Sem 'quantidade', o lote todo.
    'validade' (AAAA-MM-DD) e 'justificativa' só se o sistema pedir. Não grava: pede confirmação."""
    return acoes.propor_mudar_conservacao(produto=produto, para=para, quantidade=quantidade, de=de, lote=lote,
                                          validade=validade, justificativa=justificativa, autor=AUTOR, canal=CANAL)


@escrita(2)
def entrada_estoque(item: str, quantidade: float, unidade: str, custo_total: float, motivo: str,
                    validade: str = "", lote: str = "") -> dict:
    """Propõe dar entrada manual no estoque (ex.: 2 kg de farinha, custo total 10 reais, motivo compra).
    'validade' AAAA-MM-DD. Não grava: pede confirmação."""
    return acoes.propor_entrada_estoque(item=item, quantidade=quantidade, unidade=unidade, custo_total=custo_total,
                                        motivo=motivo, validade=validade, lote=lote, autor=AUTOR, canal=CANAL)


@escrita(2)
def criar_tamanho(salgado: str, peso_g: float, oleo_por_unidade: float | None = None) -> dict:
    """Propõe criar um tamanho novo de um salgado (ex.: coxinha de 25 g). Não grava: pede confirmação."""
    return acoes.propor_criar_tamanho(salgado=salgado, peso_g=peso_g, oleo_por_unidade=oleo_por_unidade,
                                      autor=AUTOR, canal=CANAL)


# compras, recebimento e contas a pagar

class ItemCompra(TypedDict, total=False):
    item: Required[str]
    quantidade: Required[float]
    unidade: Required[str]  # kg, g, L, mL, un ou a unidade de compra cadastrada (saco, caixa)
    valor: Required[float]  # valor total deste item em reais
    validade: str  # AAAA-MM-DD, só com ja_recebido
    lote: str


class ItemRecebido(TypedDict, total=False):
    item: Required[str]
    quantidade: float  # sem quantidade: tudo o que falta
    unidade: str
    validade: str  # AAAA-MM-DD
    lote: str


@escrita(2)
def registrar_compra(fornecedor: str, itens: list[ItemCompra], condicao: str, total: float | None = None,
                     prazo_dias: int | None = None, vencimento: str = "", parcelas: int = 1, intervalo_dias: int = 30,
                     data_compra: str = "", forma_pagamento: str = "", frete: float = 0, desconto: float = 0,
                     documento: str = "", justificativa: str = "", ja_recebido: bool = False) -> dict:
    """Propõe lançar uma compra ("comprei 20 kg de farinha por 90 reais no Atacadão, pago em 30 dias").
    'itens': cada um com item, quantidade, unidade e valor (total do item, em reais). 'condicao': a_vista ou a_prazo.
    A prazo, diga 'prazo_dias' (dias a partir da compra) ou 'vencimento' (AAAA-MM-DD) e, se dividido, 'parcelas'.
    Sem 'total', vale a soma dos itens + frete − desconto. 'data_compra' vazia = hoje. 'ja_recebido' = a mercadoria
    já chegou e entra no estoque junto (validade por item, se o item controla). Não grava: pede confirmação."""
    return compras.propor_registrar_compra(
        fornecedor=fornecedor, itens=itens, condicao=condicao, total=total, prazo_dias=prazo_dias,
        vencimento=vencimento, parcelas=parcelas, intervalo_dias=intervalo_dias, data_compra=data_compra,
        forma_pagamento=forma_pagamento, frete=frete, desconto=desconto, documento=documento,
        justificativa=justificativa, ja_recebido=ja_recebido, autor=AUTOR, canal=CANAL)


@escrita(2)
def receber_compra(fornecedor: str = "", item: str = "", quantidade: float | None = None, unidade: str = "",
                   validade: str = "", lote: str = "", compra_id: int | None = None,
                   itens: list[ItemRecebido] | None = None) -> dict:
    """Propõe dar entrada no estoque do que chegou de uma compra ("chegaram 8 dos 10 kg de farinha do Atacadão").
    Acha a compra em aberto pelo fornecedor e/ou item. Sem 'quantidade', recebe tudo o que falta; sem item,
    tudo o que falta da compra. Vários itens com quantidades diferentes: use 'itens'. 'validade' AAAA-MM-DD
    (obrigatória para item que controla validade). Não grava: pede confirmação."""
    return compras.propor_receber_compra(fornecedor=fornecedor, item=item, quantidade=quantidade, unidade=unidade,
                                         validade=validade, lote=lote, compra_id=compra_id, itens=itens,
                                         autor=AUTOR, canal=CANAL)


@escrita(2)
def encerrar_pendencia(motivo: str, fornecedor: str = "", item: str = "", compra_id: int | None = None) -> dict:
    """Propõe encerrar o que falta entregar de uma compra (o fornecedor não vai mandar o resto). Sem 'item',
    encerra tudo o que falta da compra. A conta não muda; gera um aviso de ajuste. Não grava: pede confirmação."""
    return compras.propor_encerrar_pendencia(motivo=motivo, fornecedor=fornecedor, item=item, compra_id=compra_id,
                                             autor=AUTOR, canal=CANAL)


@escrita(2)
def registrar_pagamento(fornecedor: str = "", valor: float | None = None, data_pagamento: str = "", forma: str = "",
                        compra_id: int | None = None, parcela_id: int | None = None, juros: float = 0,
                        multa: float = 0, desconto: float = 0, motivo_diferenca: str = "") -> dict:
    """Propõe ANOTAR que o dono pagou uma conta ("paguei o boleto do Atacadão"); o sistema não paga nada.
    Acha a parcela pelo fornecedor (a mais antiga da compra). 'valor' = quanto abate da parcela, sem juros
    (vazio = o saldo todo). Juros, multa ou desconto (só um) com 'motivo_diferenca'. 'data_pagamento' vazia = hoje.
    Não grava: pede confirmação."""
    return compras.propor_registrar_pagamento(
        fornecedor=fornecedor, valor=valor, data_pagamento=data_pagamento, forma=forma, compra_id=compra_id,
        parcela_id=parcela_id, juros=juros, multa=multa, desconto=desconto, motivo_diferenca=motivo_diferenca,
        autor=AUTOR, canal=CANAL)


@escrita(2)
def estornar_pagamento(motivo: str, fornecedor: str = "", pagamento_id: int | None = None) -> dict:
    """Propõe desfazer um pagamento anotado errado (a parcela volta a ficar em aberto). Não grava: pede confirmação."""
    return compras.propor_estornar_pagamento(motivo=motivo, fornecedor=fornecedor, pagamento_id=pagamento_id,
                                             autor=AUTOR, canal=CANAL)


@escrita(2)
def estornar_recebimento(motivo: str, fornecedor: str = "", item: str = "", compra_id: int | None = None,
                         recebimento_id: int | None = None) -> dict:
    """Propõe desfazer um recebimento lançado errado (sai do estoque e volta a faltar). Só se nada do lote foi usado.
    Não grava: pede confirmação."""
    return compras.propor_estornar_recebimento(motivo=motivo, fornecedor=fornecedor, item=item, compra_id=compra_id,
                                               recebimento_id=recebimento_id, autor=AUTOR, canal=CANAL)


@escrita(2)
def cancelar_compra(motivo: str, compra_id: int | None = None, fornecedor: str = "") -> dict:
    """Propõe cancelar uma compra lançada errado (só sem recebimento e sem pagamento; cancela a conta junto).
    Não grava: pede confirmação."""
    return compras.propor_cancelar_compra(motivo=motivo, compra_id=compra_id, fornecedor=fornecedor,
                                          autor=AUTOR, canal=CANAL)


@escrita(2)
def devolver_ao_fornecedor(item: str, quantidade: float, motivo: str, unidade: str = "", fornecedor: str = "",
                           compra_id: int | None = None, lote_id: int | None = None) -> dict:
    """Propõe devolver ao fornecedor parte de um lote que veio de compra (sai do estoque; gera aviso de ajuste
    na conta). Não grava: pede confirmação."""
    return compras.propor_devolver_ao_fornecedor(item=item, quantidade=quantidade, motivo=motivo, unidade=unidade,
                                                 fornecedor=fornecedor, compra_id=compra_id, lote_id=lote_id,
                                                 autor=AUTOR, canal=CANAL)


@escrita(2)
def receber_bonificacao(item: str, quantidade: float, unidade: str, motivo: str, validade: str = "", lote: str = "",
                        fornecedor: str = "", compra_id: int | None = None) -> dict:
    """Propõe dar entrada em mercadoria que veio sem cobrança (brinde, a mais do que foi comprado), a custo zero.
    Não grava: pede confirmação."""
    return compras.propor_receber_bonificacao(item=item, quantidade=quantidade, unidade=unidade, motivo=motivo,
                                              validade=validade, lote=lote, fornecedor=fornecedor,
                                              compra_id=compra_id, autor=AUTOR, canal=CANAL)


@escrita(2)
def conciliar_consumo(item: str = "", pendente_id: int | None = None, lote_id: int | None = None) -> dict:
    """Propõe ligar um consumo pendente (usado sem estoque) a um lote, fechando o custo. Sem 'lote_id', usa o lote
    que vence primeiro com saldo suficiente. Não grava: pede confirmação."""
    return compras.propor_conciliar_consumo(item=item, pendente_id=pendente_id, lote_id=lote_id,
                                            autor=AUTOR, canal=CANAL)


@escrita(2)
def aprovar_decisao(decisao_id: int) -> dict:
    """Propõe aprovar uma decisão da caixa pelo número ("aprova a doze"): a operação dela é simulada e o texto
    volta em 'confirmar' com os números. Não grava: só confirmar_proposta, depois do sim, executa (uma vez só)."""
    return decisoes.propor_aprovar_decisao(decisao_id=decisao_id, autor=AUTOR, canal=CANAL)


# vendas, encomendas, fritura, perda e contas a receber

class ItemVenda(TypedDict, total=False):
    produto: Required[str]  # o salgado como foi falado (ex.: "coxinha", "coxinha 150 g")
    quantidade: Required[int]  # quantas apresentações (duas caixas = 2)
    apresentacao: str  # unidade, caixa com 25, cento...
    forma: str  # cru ou frito
    conservacao: str  # fresco, resfriado ou congelado


@escrita(2)
def registrar_venda(itens: list[ItemVenda], cliente: str = "", condicao: str = "a_vista", forma_pagamento: str = "",
                    tabela: str = "varejo", prazo_dias: int | None = None, vencimento: str = "", parcelas: int = 1,
                    intervalo_dias: int = 30) -> dict:
    """Propõe registrar uma venda ("vendi duas caixas de coxinha congelada pro João, fiado"). 'itens': cada um com
    o produto falado, a quantidade e, se houver mais de um jeito de vender, a apresentação, a forma e a conservação.
    Preço: sempre o da tabela ('tabela' varejo ou atacado). Balcão não precisa de cliente; a prazo (fiado) precisa
    do cliente e de 'prazo_dias' ou 'vencimento' (AAAA-MM-DD). O estoque baixa pelo que vence primeiro.
    Não grava: pede confirmação."""
    return vendas.propor_registrar_venda(itens=itens, cliente=cliente, condicao=condicao,
                                         forma_pagamento=forma_pagamento, tabela=tabela, prazo_dias=prazo_dias,
                                         vencimento=vencimento, parcelas=parcelas, intervalo_dias=intervalo_dias,
                                         autor=AUTOR, canal=CANAL)


@escrita(2)
def cancelar_venda(motivo: str, venda_id: int | None = None, cliente: str = "", destino: str = "perda") -> dict:
    """Propõe cancelar uma venda inteira, com o motivo. Sem 'venda_id', acha pelo cliente (ou entre as de hoje).
    'destino' das unidades: perda (padrão) ou estoque (voltam ao estoque, se o lote não venceu). Cancela a conta a
    receber junto. Não grava: pede confirmação."""
    return vendas.propor_cancelar_venda(motivo=motivo, venda_id=venda_id, cliente=cliente, destino=destino,
                                        autor=AUTOR, canal=CANAL)


@escrita(2)
def criar_encomenda(cliente: str, dia: str, itens: list[ItemVenda], hora: str = "", modo: str = "retirada",
                    observacao: str = "", sinal: float = 0, sinal_forma: str = "", tabela: str = "varejo") -> dict:
    """Propõe uma encomenda ("encomenda do João pra sábado, três caixas de coxinha frita"). 'dia': hoje, amanhã,
    um dia da semana ou AAAA-MM-DD; 'hora' como 15:30, se combinada. 'modo': retirada ou entrega. 'sinal' em reais,
    se o cliente adiantou. Reserva o que já há no estoque e diz o que falta produzir. Não grava: pede confirmação."""
    return vendas.propor_criar_encomenda(cliente=cliente, dia=dia, itens=itens, hora=hora, modo=modo,
                                         observacao=observacao, sinal=sinal, sinal_forma=sinal_forma, tabela=tabela,
                                         autor=AUTOR, canal=CANAL)


@escrita(2)
def entregar_encomenda(encomenda_id: int | None = None, cliente: str = "", condicao: str = "a_vista",
                       forma_pagamento: str = "", prazo_dias: int | None = None, vencimento: str = "",
                       parcelas: int = 1, intervalo_dias: int = 30) -> dict:
    """Propõe entregar uma encomenda ("o João veio buscar a encomenda"): vira venda e baixa o estoque reservado.
    Acha a encomenda em aberto pelo cliente ou pelo número. O resto (total menos o sinal) é recebido à vista
    ('forma_pagamento') ou fica a prazo (com 'prazo_dias' ou 'vencimento'). Só com tudo reservado.
    Não grava: pede confirmação."""
    return vendas.propor_entregar_encomenda(encomenda_id=encomenda_id, cliente=cliente, condicao=condicao,
                                            forma_pagamento=forma_pagamento, prazo_dias=prazo_dias,
                                            vencimento=vencimento, parcelas=parcelas, intervalo_dias=intervalo_dias,
                                            autor=AUTOR, canal=CANAL)


@escrita(2)
def cancelar_encomenda(motivo: str, encomenda_id: int | None = None, cliente: str = "",
                       devolver_sinal: bool = True) -> dict:
    """Propõe cancelar uma encomenda antes da entrega, com o motivo: as reservas são liberadas. O sinal fica
    anotado como devolvido, salvo se o dono disser que fica com ele ('devolver_sinal' falso). Depois de entregue,
    cancela-se a venda. Não grava: pede confirmação."""
    return vendas.propor_cancelar_encomenda(motivo=motivo, encomenda_id=encomenda_id, cliente=cliente,
                                            devolver_sinal=devolver_sinal, autor=AUTOR, canal=CANAL)


@escrita(2)
def registrar_fritura(produto: str, quantidade: int, boas: int | None = None, motivo_perdas: str = "",
                      conservacao: str = "", destino: str = "fresco", validade: str = "",
                      justificativa: str = "") -> dict:
    """Propõe registrar uma fritura do balcão ("fritei 40 coxinhas, 38 boas, 2 estouraram"): o cru sai do lote que
    vence primeiro e vira um lote frito. Sem 'boas', todas ficaram boas; perdas pedem 'motivo_perdas'.
    'conservacao' do cru (se houver em mais de uma); 'destino' do frito (fresco). 'validade' (AAAA-MM-DD) e
    'justificativa' só se o sistema pedir. Não grava: pede confirmação."""
    return vendas.propor_registrar_fritura(produto=produto, quantidade=quantidade, boas=boas,
                                           motivo_perdas=motivo_perdas, conservacao=conservacao, destino=destino,
                                           validade=validade, justificativa=justificativa, autor=AUTOR, canal=CANAL)


@escrita(2)
def registrar_perda(produto: str, motivo: str, quantidade: float | None = None, unidade: str = "",
                    conservacao: str = "", forma: str = "", lote: str = "", vencido: bool = False) -> dict:
    """Propõe dar perda ou descartar ("joga fora 10 coxinhas fritas que caíram", "descarta o leite vencido"). Vale
    para salgado, ingrediente ou embalagem. Motivo obrigatório. Sem 'quantidade', o lote todo. 'conservacao',
    'forma' (cru/frito), 'lote' (código) e 'vencido' ajudam a achar o lote certo. Não grava: pede confirmação."""
    return vendas.propor_registrar_perda(produto=produto, motivo=motivo, quantidade=quantidade, unidade=unidade,
                                         conservacao=conservacao, forma=forma, lote=lote, vencido=vencido,
                                         autor=AUTOR, canal=CANAL)


@escrita(2)
def registrar_recebimento(cliente: str = "", valor: float | None = None, data_pagamento: str = "", forma: str = "",
                          venda_id: int | None = None, parcela_id: int | None = None, juros: float = 0,
                          multa: float = 0, desconto: float = 0, motivo_diferenca: str = "") -> dict:
    """Propõe ANOTAR que um cliente pagou o que devia ("o João pagou a conta dele", "a Maria pagou 50 reais");
    o sistema não cobra nada. Acha a parcela pelo cliente (a mais antiga da venda). 'valor' = quanto abate (vazio =
    o saldo todo). Juros, multa ou desconto (só um) com 'motivo_diferenca'. Não é mercadoria chegando
    (isso é receber_compra). Não grava: pede confirmação."""
    return vendas.propor_registrar_recebimento(
        cliente=cliente, valor=valor, data_pagamento=data_pagamento, forma=forma, venda_id=venda_id,
        parcela_id=parcela_id, juros=juros, multa=multa, desconto=desconto, motivo_diferenca=motivo_diferenca,
        autor=AUTOR, canal=CANAL)


@escrita(2)
def estornar_recebimento_cliente(motivo: str, cliente: str = "", pagamento_id: int | None = None) -> dict:
    """Propõe desfazer um recebimento de cliente anotado errado (a parcela volta a ficar em aberto).
    Não grava: pede confirmação."""
    return vendas.propor_estornar_recebimento_cliente(motivo=motivo, cliente=cliente, pagamento_id=pagamento_id,
                                                      autor=AUTOR, canal=CANAL)


@escrita(2)
def confirmar_proposta(proposta_id: int) -> dict:
    """Grava uma proposta. Só depois de o usuário dizer sim à frase de 'confirmar'."""
    return acoes.confirmar(proposta_id, autor=AUTOR)


@escrita(2)
def recusar_proposta(proposta_id: int) -> dict:
    """Descarta uma proposta sem gravar (o usuário disse não ou mudou o pedido)."""
    return acoes.recusar(proposta_id, autor=AUTOR)
