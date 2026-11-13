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

`iniciar_producao` e `concluir_producao` aceitam também `justificativa_falta`:
com ela, a produção começa (ou fecha) mesmo faltando estoque, e o que faltar
vira **consumo pendente** de conciliar (o "Confirma?" da conclusão diz quanto).

Conservação aceita `fresco`, `resfriado` (ou "geladeira") e `congelado` (ou
"freezer"); forma, `cru` ou `frito`. Datas em `AAAA-MM-DD`.

### Compras, recebimento e contas a pagar

Lógica em `agente/compras.py` (Plano 3, fase 2b). Tudo chega pelo **nome
falado** — fornecedor e item — e o sistema acha a compra, a linha, a parcela ou
o lote; com mais de um candidato volta `opcoes` (com o número para a próxima
chamada: `compra_id`, `parcela_id`, `lote_id`...). As consultas devolvem
`texto` pronto para falar, com dinheiro por extenso ("12 reais e 50
centavos"), datas faladas ("hoje", "em 12 de dezembro") e **totais já
somados**; os números vêm também como `{"valor", "texto"}`.

**O sistema nunca paga nada:** `registrar_pagamento` só anota que o dono pagou.
Tudo que mexe com dinheiro ou com entrada/baixa de estoque é nível 2.

| Ferramenta | Nível | Parâmetros | O que faz |
|---|---|---|---|
| `buscar_fornecedores` | 0 | `busca=""` | fornecedores (nome, contato, ativo) |
| `ver_compras_em_aberto` | 0 | `fornecedor=""` | compras esperando entrega e o que falta de cada uma |
| `ver_falta_receber` | 0 | `fornecedor=""`, `item=""` | itens que não chegaram, com a idade em dias |
| `ver_compra` | 0 | `compra_id` | itens (chegou/falta/não entregue), parcelas e avisos |
| `ver_contas` | 0 | `situacao="todas"` (`vencidas`, `a_vencer`), `dias=7`, `fornecedor=""` | parcelas em aberto com `total` e `vencido` somados |
| `ver_divida_fornecedores` | 0 | `fornecedor=""` | quanto se deve a cada um, quanto venceu, total geral; com fornecedor, a parcela mais antiga |
| `ver_avisos_de_ajuste` | 0 | — | avisos em aberto (não entregue, devolução) |
| `ver_consumos_pendentes` | 0 | `item=""` | o que foi usado sem estoque e se já há lote para conciliar |
| `ultimo_preco` | 0 | `item` | custo da última compra por quilo/litro/unidade (com rateio) |
| `cadastrar_fornecedor` | 1 | `nome`, `contato=""`, `documento=""` | cadastra (recusa nome repetido, mesmo com outra caixa ou sem acento) |
| `resolver_aviso` | 1 | `observacao`, `aviso_id?` | anota o que foi feito com o aviso; sem id, o único aberto |
| `registrar_compra` | 2 | `fornecedor`, `itens=[{item, quantidade, unidade, valor, validade?, lote?}]`, `condicao` (`a_vista`/`a_prazo`), `total?`, `prazo_dias?`, `vencimento=""`, `parcelas=1`, `intervalo_dias=30`, `data_compra=""`, `forma_pagamento=""`, `frete=0`, `desconto=0`, `documento=""`, `justificativa=""`, `ja_recebido=false` | lança e aprova a compra e a conta; sem `total`, soma itens + frete − desconto; a prazo exige `prazo_dias` ou `vencimento` (as parcelas são divididas pelo sistema); `ja_recebido` dá entrada no estoque junto |
| `receber_compra` | 2 | `fornecedor=""`, `item=""`, `quantidade?`, `unidade=""`, `validade=""`, `lote=""`, `compra_id?`, `itens?=[{item, quantidade?, unidade?, validade?, lote?}]` | acha a compra em aberto pelo fornecedor/item; sem quantidade recebe o que falta; sem item, tudo o que falta da compra |
| `encerrar_pendencia` | 2 | `motivo`, `fornecedor=""`, `item=""`, `compra_id?` | o resto não vem; a conta não muda, gera aviso |
| `registrar_pagamento` | 2 | `fornecedor=""`, `valor?`, `data_pagamento=""`, `forma=""`, `compra_id?`, `parcela_id?`, `juros=0`, `multa=0`, `desconto=0`, `motivo_diferenca=""` | anota o pagamento; parcelas da mesma compra → a mais antiga; de compras diferentes → o `valor` igual ao saldo desfaz, senão `opcoes`; sem valor, o saldo todo |
| `estornar_pagamento` | 2 | `motivo`, `fornecedor=""`, `pagamento_id?` | desfaz um pagamento anotado |
| `estornar_recebimento` | 2 | `motivo`, `fornecedor=""`, `item=""`, `compra_id?`, `recebimento_id?` | desfaz um recebimento (só se o lote não foi usado) |
| `cancelar_compra` | 2 | `motivo`, `compra_id?`, `fornecedor=""` | cancela compra sem recebimento nem pagamento (pelo fornecedor, só as sem recebimento são candidatas) |
| `devolver_ao_fornecedor` | 2 | `item`, `quantidade`, `motivo`, `unidade=""`, `fornecedor=""`, `compra_id?`, `lote_id?` | baixa de lote vindo de compra + aviso de ajuste |
| `receber_bonificacao` | 2 | `item`, `quantidade`, `unidade`, `motivo`, `validade=""`, `lote=""`, `fornecedor=""`, `compra_id?` | entrada a custo zero |
| `conciliar_consumo` | 2 | `item=""`, `pendente_id?`, `lote_id?` | liga o consumo pendente a um lote (sem lote: o que vence primeiro com saldo) e fecha o custo |

Unidades faladas: "quilo(s)" → kg, "grama(s)" → g, "litro(s)" → L,
"mililitro(s)" → mL, "unidade(s)" → un; outras (saco, caixa) precisam da
conversão cadastrada no item (o núcleo recusa: "Cadastre o fator de 'saco'...").

O "Confirma?" de cada proposta traz itens, quantidades, total, condição e
vencimentos, e os **alertas de duplicata** do núcleo ("Atenção: Possível
duplicata: a compra 3 é do mesmo fornecedor, na mesma data e com o mesmo
total"). Depois de confirmar um recebimento ou bonificação, o `dito` avisa se
há consumo pendente que pode ser conciliado com o que entrou.

```
usuário: "comprei 20 quilos de farinha por 90 reais no Atacadão, pago em 30 dias"
agente → registrar_compra(fornecedor="Atacadão", condicao="a_prazo", prazo_dias=30,
                          itens=[{"item": "farinha", "quantidade": 20, "unidade": "kg", "valor": 90}])
       ← {"confirmar": "Lançar compra do fornecedor Atacadão, hoje: 20 kg de Farinha de trigo por 90 reais.
                        Total 90 reais, a prazo, vence em 12 de dezembro. Confirma?", "proposta_id": 21, ...}
usuário: "chegaram 8 dos 10 quilos de farinha do Atacadão"
agente → receber_compra(fornecedor="Atacadão", item="farinha", quantidade=8, unidade="kg")
       ← {"confirmar": "Receber da compra 5, fornecedor Atacadão: 8 kg de Farinha de trigo.
                        Fica faltando 2 kg de Farinha de trigo. Confirma?", ...}
usuário: "quanto devo ao Atacadão?"
agente → ver_divida_fornecedores(fornecedor="Atacadão")
       ← {"texto": "Com o fornecedor Atacadão, você deve 90 reais em 1 parcela, nada vencido. A mais antiga: ..."}
```

"Comprei e já chegou" (`ja_recebido`) é uma proposta só, executada como duas
operações do núcleo (`registrar_compra` com a chave da proposta e
`receber_compra` com a chave + `:receber`): se o recebimento for recusado na
confirmação, a compra fica lançada, a proposta continua pendente com o erro, e
confirmar de novo só refaz o recebimento.

O trecho para o prompt do agente e um roteiro de teste por voz estão em
[`agente-instrucoes-compras.md`](agente-instrucoes-compras.md).

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
