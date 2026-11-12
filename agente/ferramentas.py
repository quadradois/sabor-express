"""Ferramentas do agente no padrão MCP (voz, Telegram e texto usam as mesmas).

Cada ferramenta é uma função síncrona comum, registrada com um decorador que
diz o tipo dela. O decorador cuida do que é igual para todas: rodar o ORM fora
do loop async (sync_to_async) e devolver erro de entrada como
{"erro": "..."} em vez de exceção. `criar_servidor()` monta o FastMCP a partir
do registro.

Só há consultas (`@leitura`) por enquanto. As ferramentas de escrita entram com
um decorador `@escrita` irmão, que vai chamar `nucleo.operacoes.executar` com
canal="agente" e a chave de idempotência; o registro e o servidor não mudam.
"""

import functools
import inspect
from dataclasses import dataclass
from typing import Any, Callable

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import consultas
from .consultas import ConsultaInvalida
from nucleo.operacoes import RegraViolada

INSTRUCOES = (
    "Ferramentas da cozinha do Sabor Express. O sistema faz todas as contas: "
    "nunca calcule quantidades, saldos ou custos por conta própria; use o campo "
    "'texto' das quantidades ao falar. Se vier 'erro', explique ao usuário; se vier "
    "'opcoes', pergunte qual delas ele quis dizer."
)


@dataclass(frozen=True)
class Ferramenta:
    func: Callable[..., dict]
    anotacoes: ToolAnnotations

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
