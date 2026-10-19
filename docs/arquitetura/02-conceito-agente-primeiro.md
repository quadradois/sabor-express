# Conceito "agente primeiro" — leitura do trycompai/crm aplicada ao Sabor Express

**Data:** 19/10/2026 · **Status:** proposta para discussão
**Fonte:** `trycompai/crm` (commit `6d4793d`): README, `docs/agent.md` e `apps/agent/agent/tools/record_fact.ts`
**Relação:** refina a análise de `01-viabilidade-jarvis.md`. A pergunta deixa de ser "Jarvis sistema × usuário" e passa a ser "o produto é desenhado em torno do agente?".

## 1. O conceito do CRM, em uma frase

> "The agent is not a feature of the CRM; the CRM is where the agent keeps its notes."

Na tradução livre: o agente não é uma funcionalidade do CRM; o CRM é onde o agente guarda as anotações dele. O agente é o trabalhador principal, e o banco de dados e as telas existem para ele registrar o que fez e para o humano acompanhar e decidir.

## 2. Como o CRM faz isso (os mecanismos que importam)

| Mecanismo | Como funciona lá | Por que importa |
|---|---|---|
| **Trabalha sozinho** | Tem implantação própria, uma fila de tarefas com data (`dueAt`) e um agendador que "não decide nada", só entrega o que venceu. O agente marca as próprias revisões (`schedule_recheck`) e diz o motivo | O agente não espera pedido: ele tem uma agenda de trabalho |
| **A inteligência mora só no agente** | "Intelligence never lives in the API": a API só relata o que aconteceu, e o agente decide o que isso significa | Evita duas cópias da mesma lógica que divergem |
| **Um único caminho de gravação, com regras em código** | `lib/facts.ts` é o único lugar que grava. O código, não o modelo, decide o que é aplicado e o que vira sugestão. O código também garante: nunca sobrescrever o humano, nunca reoferecer o que foi recusado, nunca gravar sem fonte | **O agente é livre para propor e limitado para gravar.** As salvaguardas não dependem do prompt |
| **Evidência, não confiança** | As ferramentas não aceitam "nota de certeza" do modelo. Elas recebem o que foi **observado**, e o código dá o peso. Evidência forte grava; evidência fraca vira sugestão para o humano | O modelo não se autoavalia |
| **Habilidades em texto** | Skills em arquivos Markdown versionados, como regras de evidência e limites de dados | O "manual de trabalho" do agente é legível e editável |
| **Você vê ele trabalhar** | Cada registro tem uma aba "Agente" com os passos dados, o que foi descartado e por quê, e as perguntas que ele deixou para o humano | Transparência e confiança |
| **Tudo opcional** | Sem chaves externas, ele continua funcionando com o que tem e avisa o que está desligado | Degrada sem quebrar |
| **Orçamento** | Cada sessão tem um limite de chamadas pagas; acabar o orçamento é um fim normal | Custo previsível |

## 3. Tradução para o Sabor Express

O produto deixa de ser "um sistema com telas, que um dia ganha um assistente" e passa a ser **um agente de cozinha com um caderno organizado** (o banco), **um conjunto de regras que ele não consegue furar** (o núcleo) e **vários canais para falar com você** (tela, Telegram e, depois, voz).

```
              Canais:  tela  ·  Telegram  ·  voz (depois)
                                │
                     ┌──────────▼──────────┐
                     │   AGENTE DA COZINHA  │  decide, propõe, conversa,
                     │  (skills + fila de   │  trabalha por conta própria
                     │      tarefas)        │
                     └──────────┬──────────┘
                                │ ferramentas
                     ┌──────────▼──────────┐
                     │  NÚCLEO DE REGRAS    │  único caminho de gravação:
                     │  (estoque, custo,    │  aplica, transforma em sugestão
                     │   dinheiro, fichas)  │  ou recusa, por regra em código
                     └──────────┬──────────┘
                                ▼
                         banco (SQLite)
```

### O que o agente faria sozinho, pela fila de tarefas

| Gatilho | Trabalho do agente | Resultado |
|---|---|---|
| Chegou foto de cupom (Telegram) | Lê, associa os itens às fichas, confere o total | Compra **sugerida** para você aprovar com um toque |
| Todo dia de manhã | Olha validades, encomendas da semana e estoque | "Hoje: 3 lotes vencem amanhã; a encomenda de sábado precisa de 40 coxinhas; falta requeijão" |
| Encomenda confirmada | Calcula a necessidade, monta o plano de produção e a lista de compras | Plano **sugerido** |
| Produção concluída | Compara o rendimento real com o previsto nas últimas produções | "A massa vem rendendo 4% menos. Ajusto a ficha?" |
| Conta perto do vencimento | — | Aviso |

### O que o núcleo garante, por mais que o agente erre

As regras do PRD v1.0 não se perdem. **Elas viram exatamente esse caminho único de gravação:**

- **Aplica direto** (baixo risco, você já confirmou ao falar ou tocar): registrar peso durante o preparo, avançar etapa, cronômetro, imprimir etiqueta.
- **Vira sugestão para você aprovar** (mexe em estoque ou dinheiro por iniciativa do agente): compra lida de cupom, ajuste de ficha, ajuste de estoque, plano de produção, lançamento de despesa.
- **Recusa sempre:** saldo negativo fora da exceção, alterar lote concluído, apagar histórico, pagamento por iniciativa do agente.

### Como as telas mudam

Em vez de formulários para preencher, as telas principais passam a ser:

1. **Caixa de decisões:** o que o agente preparou e espera o seu "sim" (compras, planos, ajustes).
2. **Conversa:** por texto ou, mais tarde, por voz, com o mesmo agente.
3. **Consulta:** estoque, fichas, custos e contas.
4. **Formulários manuais** como plano B, para quando o agente estiver fora ou errar.

Isso **reduz** o trabalho de digitação, o que combina com "simples e eficiente".

## 4. E o Jarvis?

Neste conceito, o **Jarvis não é um usuário do sistema: ele é a voz do agente.** O agente é um só (mesma memória, mesmas skills, mesma fila de tarefas), e voz, Telegram e tela são canais dele. Projetos como `omnigentx/jarvis` passam a ser **fornecedores de peças de voz** (fala para texto, texto para fala, palavra de ativação), não a base do produto.

## 5. O que não copiar do CRM

- A stack (TypeScript, Next, Nest, Postgres e a nuvem da Vercel). O PVD define LAN e SQLite, e o conceito independe da stack.
- O escopo de pesquisa na web sobre pessoas. O domínio aqui é cozinha.
- A escala (fila com concorrência entre vários despachantes). Aqui é um agente, uma cozinha.

## 6. Custos e riscos do conceito

| Risco | Mitigação |
|---|---|
| O agente depende de um modelo de IA (internet e custo por uso) | Núcleo e formulários funcionam sem ele. Orçamento por tarefa. Modelo local como opção |
| O agente erra | Caminho único de gravação: tudo o que é arriscado vira sugestão, e o código decide, não o prompt |
| Excesso de sugestões vira ruído | Regra do CRM: não reoferecer o que foi recusado e não sugerir o que já está resolvido |
| Escopo do MVP cresce | Começar com um agente de texto e poucos trabalhos (cupom, resumo do dia, ficha viva); voz depois |

## 7. Impacto nos documentos aprovados

- **DEC-F2-002** (IA e voz fora do MVP) precisaria ser revista: o agente entra no MVP; a voz continua depois.
- O **PRD v1.0** mantém as regras, mas os requisitos de tela e de automação mudam de "formulário + automação pontual" para "agente propõe, você decide". Isso pede uma versão nova do PRD, sem perder as regras.
