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
`agente/acoes.py` e `agente/propostas.py`.
"""

import functools
import inspect
from dataclasses import dataclass
from typing import Any, Callable

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import acoes, consultas
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
    "Se vier 'repetida', a mesma chamada já tinha sido feita há instantes e não foi gravada de novo."
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


def criar_servidor() -> FastMCP:
    mcp = FastMCP("sabor-express", instructions=INSTRUCOES, log_level="WARNING")
    for f in REGISTRO:
        mcp.add_tool(_rodar(f.func), name=f.nome, description=inspect.cleandoc(f.func.__doc__),
                     annotations=f.anotacoes)
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
def ver_producao(producao_id: int) -> dict:
    """Detalhes de uma produção: etapa atual, o que falta pesar, cronômetros rodando, perdas e custo."""
    return consultas.producao(producao_id)


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


# --- nível 2: repete e espera o sim ----------------------------------------
# Não gravam: devolvem 'confirmar' (para ler em voz alta) e 'proposta_id'.

@escrita(2)
def iniciar_producao(produto: str, unidades: int, forma: str = "cru") -> dict:
    """Propõe iniciar uma produção ('forma': cru ou frito). Não grava: pede confirmação."""
    return acoes.propor_iniciar_producao(produto=produto, unidades=unidades, forma=forma, autor=AUTOR, canal=CANAL)


@escrita(2)
def concluir_producao(quantidade_boa: int, conservacao: str, perdas: int = 0, motivo_perdas: str = "",
                      anotacao: str = "", validade: str = "", justificativa: str = "",
                      producao_id: int | None = None) -> dict:
    """Propõe concluir a produção: unidades boas, perdas com motivo e conservação (fresco, resfriado, congelado).
    'validade' (AAAA-MM-DD) e 'justificativa' só se o sistema pedir. Não grava: pede confirmação."""
    return acoes.propor_concluir_producao(quantidade_boa=quantidade_boa, conservacao=conservacao, perdas=perdas,
                                          motivo_perdas=motivo_perdas, anotacao=anotacao, validade=validade,
                                          justificativa=justificativa, producao_id=producao_id,
                                          autor=AUTOR, canal=CANAL)


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


@escrita(2)
def confirmar_proposta(proposta_id: int) -> dict:
    """Grava uma proposta. Só depois de o usuário dizer sim à frase de 'confirmar'."""
    return acoes.confirmar(proposta_id, autor=AUTOR)


@escrita(2)
def recusar_proposta(proposta_id: int) -> dict:
    """Descarta uma proposta sem gravar (o usuário disse não ou mudou o pedido)."""
    return acoes.recusar(proposta_id, autor=AUTOR)
