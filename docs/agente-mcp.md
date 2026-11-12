# Servidor MCP do agente

O agente (voz, Telegram, texto) conversa com o Sabor Express por um servidor
[MCP](https://modelcontextprotocol.io) que roda **dentro** do projeto. As
ferramentas ficam em `agente/ferramentas.py`; a lógica das consultas, em
`agente/consultas.py` (a mesma que a API REST provisória `/api/agente/` usa).
O sistema faz todas as contas; o modelo só escolhe a ferramenta e fala o
resultado.

## Iniciar

Transporte **stdio**: o cliente inicia o processo e fala com ele por
stdin/stdout. Não há porta nem token — quem consegue rodar o comando já tem
acesso à máquina.

```bash
uv run python manage.py mcp_agente
```

Rodado à mão ele fica parado esperando o protocolo no stdin (Ctrl+C sai). O
stdout é exclusivo do protocolo; logs saem no stderr. O banco é o do
`settings` (o `db.sqlite3` do checkout em `cwd`).

## Ferramentas

Todas são só leitura. Erros voltam como `{"erro": "mensagem"}`; quantidades
vêm como `{"valor", "unidade", "texto"}` — o `texto` é o que se fala ("1,2 kg").

| Ferramenta | Parâmetros | Devolve |
|---|---|---|
| `consultar_estoque` | `busca: str = ""` | itens ativos com saldo, mínimo e `abaixo_do_minimo` |
| `ver_validades` | `dias: int = 3` | lotes com estoque vencendo até hoje+`dias` (inclui vencidos) |
| `buscar_produtos` | `busca: str = ""` | produtos com peso da unidade e saldo em unidades |
| `calcular_receita` | `produto: str`, `unidades: int` | ingredientes necessários, falta e `da_para_produzir` |
| `ver_producoes` | `status: str = "andamento"` (`andamento`, `concluida`, `cancelada`, `todas`) | até 20 produções, mais recentes primeiro |
| `ver_producao` | `producao_id: int` | etapa atual, falta pesar, cronômetros, perdas, custo |

A busca ignora maiúsculas e acentos e casa por trecho do nome. Em
`calcular_receita` o produto precisa casar com **exatamente um** produto (ou
ter o nome idêntico a um deles); com vários, volta
`{"erro": ..., "opcoes": ["Coxinha 25 g", "Coxinha 50 g"]}` para o agente
perguntar qual.

## Configurar um cliente stdio

Pipecat (`MCPClient`) ou o SDK `mcp` em Python:

```python
from mcp import StdioServerParameters

parametros = StdioServerParameters(
    command="/home/quadradois/.local/bin/uv",
    args=["run", "--quiet", "python", "manage.py", "mcp_agente"],
    cwd="/home/quadradois/Sabor-Express",
    env={"SABOR_DEBUG": "1"},
)
```

- `cwd`: raiz do checkout cujo `db.sqlite3` deve ser lido.
- `env`: o SDK junta este dict com um ambiente mínimo (`HOME`, `PATH`...). Em
  produção (`SABOR_DEBUG=0`) passe também `SABOR_SECRET_KEY`. O
  `SABOR_AGENTE_TOKEN` não é usado pelo MCP.

Equivalente em JSON (Claude Desktop, Claude Code e afins):

```json
{
  "mcpServers": {
    "sabor-express": {
      "command": "/home/quadradois/.local/bin/uv",
      "args": ["run", "--quiet", "python", "manage.py", "mcp_agente"],
      "cwd": "/home/quadradois/Sabor-Express",
      "env": {"SABOR_DEBUG": "1"}
    }
  }
}
```

## Próxima etapa: escrita

Ferramentas que gravam (iniciar produção, registrar peso, concluir...) entram
em `agente/ferramentas.py` com um decorador `@escrita` ao lado de `@leitura`,
chamando `nucleo.operacoes.executar` com `canal="agente"` e chave de
idempotência. O registro e `criar_servidor()` não mudam.
