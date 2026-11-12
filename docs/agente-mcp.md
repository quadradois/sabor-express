# Servidor MCP do agente

O agente (voz, Telegram, texto) conversa com o Sabor Express por um servidor
[MCP](https://modelcontextprotocol.io) que roda **dentro** do projeto. As
ferramentas ficam em `agente/ferramentas.py`; a lógica das consultas, em
`agente/consultas.py` (a mesma que a API REST provisória `/api/agente/` usa);
a das gravações, em `agente/acoes.py` e `agente/propostas.py`.
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

Erros voltam como `{"erro": "mensagem"}`; com ambiguidade (dois produtos,
ingrediente em dois blocos, duas produções em andamento, dois lotes) vem também
`"opcoes": [...]` para o agente perguntar qual. Quantidades vêm como
`{"valor", "unidade", "texto"}` — o `texto` é o que se fala ("1,2 kg").

A busca por nome ignora maiúsculas e acentos e casa quando **cada palavra dita**
aparece no nome ("farinha empanamento" casa "Farinha de trigo (Empanamento)").
Nome idêntico a uma opção ganha das parciais. Onde há `producao_id` opcional,
omitir vale para **a única** produção em andamento.

### Alçada

As ferramentas seguem a alçada aprovada pelo dono (design §6.2). Todas as
gravações passam por `nucleo.operacoes.executar` com `canal="agente"` e
`autor="agente-mcp"`, ficando na trilha de auditoria.

| Nível | Efeito | Devolve |
|---|---|---|
| 0 — consulta | não grava | os dados |
| 1 — faz e repete | grava na hora | `dito` (frase do que foi feito, já formatada) + `resultado` |
| 2 — repete e espera o sim | **não grava**; cria uma proposta | `confirmar` (frase terminando em "Confirma?") + `proposta_id` + `expira_em` |
| 3 — nunca | não existe ferramenta; o núcleo recusa | `{"erro": ...}` |

| Ferramenta | Nível | Parâmetros | O que faz |
|---|---|---|---|
| `consultar_estoque` | 0 | `busca=""` | itens ativos com saldo, mínimo e `abaixo_do_minimo` |
| `ver_validades` | 0 | `dias=3` | lotes com estoque vencendo até hoje+`dias` (inclui vencidos) |
| `buscar_produtos` | 0 | `busca=""` | produtos com peso da unidade e saldo em unidades |
| `calcular_receita` | 0 | `produto`, `unidades` | ingredientes necessários, falta e `da_para_produzir` |
| `ver_producoes` | 0 | `status="andamento"` | até 20 produções, mais recentes primeiro |
| `ver_producao` | 0 | `producao_id` | etapa atual, falta pesar, cronômetros, perdas, custo |
| `registrar_peso` | 1 | `item`, `quantidade`, `unidade=""`, `lote=""`, `producao_id?` | peso usado de um ingrediente ("Requeijão: 355 g registrado. Falta pesar: ...") |
| `usar_previsto` | 1 | `item=""`, `producao_id?` | "usei o previsto" num ingrediente ou em todos os que faltam |
| `proxima_etapa` | 1 | `producao_id?` | avança e lê a etapa nova |
| `ir_para_etapa` | 1 | `etapa`, `producao_id?` | vai para a etapa N (0 = pesagem) |
| `iniciar_cronometro` | 1 | `minutos?`, `nome=""`, `producao_id?` | liga cronômetro; sem minutos usa o tempo da etapa |
| `parar_cronometro` | 1 | `nome=""`, `producao_id?` | desliga o cronômetro (pelo nome, se houver vários) |
| `registrar_etiqueta` | 1 | `produto`, `conservacao=""`, `copias?`, `lote=""` | registra impressão de etiquetas (sem cópias: uma por unidade) |
| `iniciar_producao` | 2 | `produto`, `unidades`, `forma="cru"` | propõe iniciar a produção |
| `concluir_producao` | 2 | `quantidade_boa`, `conservacao`, `perdas=0`, `motivo_perdas=""`, `anotacao=""`, `validade=""`, `justificativa=""`, `producao_id?` | propõe concluir (com 0 boas, a proposta é a confirmação da perda total) |
| `cancelar_producao` | 2 | `motivo`, `producao_id?` | propõe cancelar |
| `mudar_conservacao` | 2 | `produto`, `para`, `quantidade?`, `de=""`, `lote=""`, `validade=""`, `justificativa=""` | propõe mudar a conservação (sem quantidade: o lote todo) |
| `entrada_estoque` | 2 | `item`, `quantidade`, `unidade`, `custo_total`, `motivo`, `validade=""`, `lote=""` | propõe entrada manual com valor |
| `criar_tamanho` | 2 | `salgado`, `peso_g`, `oleo_por_unidade?` | propõe criar um tamanho novo de um salgado |
| `confirmar_proposta` | 2 | `proposta_id` | **grava** a proposta — só depois do "sim" falado |
| `recusar_proposta` | 2 | `proposta_id` | descarta a proposta sem gravar |

Conservação aceita `fresco`, `resfriado` (ou "geladeira") e `congelado` (ou
"freezer"); forma, `cru` ou `frito`. Datas em `AAAA-MM-DD`.

### Fluxo de proposta (nível 2)

```
usuário: "começa 10 bolinhas"
agente → iniciar_producao(produto="bolinha", unidades=10)
       ← {"confirmar": "Iniciar a produção de 10 Bolinha 100 g, cru. Confirma?", "proposta_id": 7, ...}
agente: lê o "confirmar" em voz alta
usuário: "sim"
agente → confirmar_proposta(proposta_id=7)
       ← {"dito": "Feito: Iniciar a produção ... É a produção 12. Mise en place: ...", "resultado": {...}}
```

- **A confirmação está na estrutura:** a ferramenta de nível 2 nunca grava. Ela
  cria uma `agente.Proposta` pendente (quem propôs, canal, operação,
  parâmetros, resumo, validade) e só `confirmar_proposta` executa.
- **Validação antes de perguntar:** a operação é **simulada** pelo núcleo numa
  transação desfeita no fim. Toda recusa de regra (falta estoque, produção
  encerrada, sem critério de validade...) volta como `erro` já na proposta, e o
  resumo traz valores calculados pelo núcleo (validade nova, nome do tamanho).
  A simulação não deixa rastro.
- **Validade curta:** 5 minutos (`agente.propostas.VALIDADE`). Depois disso a
  proposta vira `expirada` e confirmar devolve erro ("peça de novo").
- **Confirmar duas vezes não duplica:** a execução usa a chave da proposta
  (`proposta:<uuid>`) em `executar`; a segunda chamada devolve o mesmo
  resultado. Recusada ou expirada → erro. Confirmada não pode ser recusada.
- **Se o núcleo recusar na confirmação** (o estado mudou desde a proposta), a
  proposta continua pendente com o `erro` anotado, e a recusa fica na trilha.
- As propostas aparecem no admin (só leitura). São a base da futura caixa de
  decisões (Plano 4), que poderá confirmar pela tela com `agente.propostas.confirmar`.

### Chamadas repetidas (nível 1)

Modelos às vezes repetem a mesma chamada (chamadas paralelas, nova tentativa).
Cada gravação de nível 1 usa a chave `agente:<ação>:<hash>:<único>`, em que o
hash junta a ação e os argumentos **já resolvidos** (linha do preparo, gramas
na unidade base, lote, cronômetro...). Se a mesma chamada deu certo há menos de
**6 segundos** (`agente.acoes.JANELA_REPETICAO`), nada é gravado de novo: volta
o resultado anterior com `"repetida": true`. Depois da janela, o mesmo pedido
vale de novo — "próxima etapa" dita duas vezes avança duas vezes, porque entre
um pedido e outro o agente fala a etapa (mais que a janela).

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
