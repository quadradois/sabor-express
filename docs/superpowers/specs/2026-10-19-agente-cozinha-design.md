# Design — Sabor Express como agente de cozinha

**Data:** 19/10/2026 · **Status:** aprovado pelo proprietário em 19/10/2026
**Substitui em parte:** PRD v1.0 (`docs/prd/02-prd.md`), quanto à forma de operar. As regras de domínio continuam valendo.
**Base:** PVD v1.1 · PRD v1.0 · decisões DEC-F2-001 a 047 (`docs/prd/01-registro-decisoes.md`) · `docs/arquitetura/01-viabilidade-jarvis.md` · `docs/arquitetura/02-conceito-agente-primeiro.md`

---

## 1. Intenção

O proprietário não quer "um sistema de gestão com um assistente". Ele quer **um agente de cozinha que é o sistema**. O agente trabalha sozinho e conduz a produção, as compras e os avisos. Fala com o dono por tela e Telegram e, depois do MVP, por voz (o "Jarvis da cozinha", nome ainda a definir).

As telas e o banco de dados deixam de ser o produto. Eles passam a ser **o caderno do agente** e **a janela do dono** para acompanhar e decidir.

**Por quê:**
1. Durante o preparo, a tela fica de lado, e um agente pode acompanhar a cozinha onde a tela não alcança.
2. O dono quer tirar digitação e burocracia do dia a dia: o agente prepara, e ele confere.
3. O dono quer uma "ficha técnica viva", que conversa e ensina, em vez de uma receita estática.

**É um projeto pessoal e pequeno.** Simples e eficiente. Não pode virar um ERP de cozinha cheio de regras.

## 2. Objetivos

- **G1.** O dono diz "50 coxinhas de frango de 150 g" e recebe a receita escalada em cascata pelas sub-receitas, na ordem de preparo, com o que falta no estoque.
- **G2.** O agente conduz um preparo etapa por etapa (instrução, ponto de checagem, cronômetro, pesagem) e registra consumo, quantidade boa e perdas sem redigitação.
- **G3.** O dono manda a foto de um cupom e o agente lê, associa os itens e apresenta a compra para conferência.
- **G4.** O agente trabalha por conta própria: resumo da manhã, validades, encomendas, contas a vencer e sugestões de ajuste de ficha a partir do rendimento real.
- **G5.** Estoque, lotes, custos e contas permanecem corretos e rastreáveis, conforme as regras do PRD v1.0.
- **G6.** Depois do MVP, a voz é acrescentada como **mais um canal** do mesmo agente, sem refazer o núcleo.

## 3. Fora do escopo do MVP

- Voz. Ela vem depois do MVP, mas o desenho já a prevê (§6.5).
- Mais de um usuário e perfis de acesso. O modelo registra autor e canal, sem login por pessoa.
- O agente comprar, pedir a fornecedor, pagar ou movimentar dinheiro. **Ele só registra.**
- Integração com balança. Vem depois; o campo de peso fica pronto para receber leituras.
- Tudo o que o PVD §8 e o PRD §4 já excluem (fiscal, contabilidade, WhatsApp e outros).

## 4. Anti-objetivos: falha mesmo que funcione

- **A1. O agente gravar algo fora das regras.** Por exemplo, deixar o estoque negativo, reescrever o histórico ou aplicar uma compra lida errada sem conferência.
- **A2. O agente dizer que fez algo que não foi gravado.** Sucesso só depois de o núcleo confirmar (PRD RN-39).
- **A3. A IA calcular quantidades ou custos.** Escala de receita, custos, saldos e rendimentos são **cálculo determinístico no núcleo**. O modelo nunca faz essas contas: ele chama a ferramenta que calcula.
- **A4. Burocracia.** Confirmações, campos e telas que não protegem dinheiro, estoque ou histórico.
- **A5. Excesso de sugestões.** O agente não reoferece o que foi recusado nem sugere o que já está resolvido.
- **A6. A operação parar quando a IA cai.** O núcleo e os formulários manuais funcionam sem o agente.

## 5. Restrições

- Rede local, com um computador central na cozinha ou no escritório. SQLite acessado só pelo serviço central (PVD §7).
- **A internet da cozinha é estável** (confirmado pelo dono em 19/10/2026). O agente pode usar um modelo de IA em nuvem.
- Um único usuário, o dono. Interface em pt-BR.
- Todas as regras de domínio do PRD v1.0 continuam valendo, incluindo RN-01 a RN-40, os estados do §11 e as decisões DEC-F2-001 a 047, exceto o que este documento revisa (§10).

## 6. Desenho

### 6.1 As peças

```
      Canais:   tela web (LAN)   ·   Telegram   ·   voz (pós-MVP)
                          │ mensagens / toques
               ┌──────────▼───────────┐
               │   AGENTE DA COZINHA   │  modelo de IA em nuvem
               │  skills (Markdown)    │  conversa, decide, propõe
               │  fila de tarefas      │  trabalha sozinho
               └──────────┬───────────┘
                          │ ferramentas (MCP)
               ┌──────────▼───────────┐
               │   NÚCLEO DE REGRAS    │  único caminho de gravação
               │  cálculo + validação  │  aplica / sugere / recusa
               └──────────┬───────────┘
                          ▼
                    SQLite + arquivos
```

- **Núcleo de regras:** as operações de domínio do PRD (compras, recebimento, estoque, fichas, produção, vendas, custos e financeiro), os cálculos e as validações. **É o único lugar que grava.** Telas, Telegram e agente chamam as mesmas operações (PRD RF-EXT-01 a 03).
- **Ferramentas do agente:** uma camada fina sobre as operações do núcleo, exposta no padrão MCP. Por isso, qualquer agente ou canal de voz futuro pode usá-las.
- **Agente:** modelo de IA com ferramentas, um conjunto de **skills** em Markdown versionadas no repositório (como trabalhar na cozinha, como ler cupom, alçada, tom de conversa) e **uma única memória de conversa**, compartilhada por todos os canais (decisão do construtor: há um usuário só, e o dono pode começar no Telegram e continuar na tela).
- **Fila de tarefas:** registros com data de vencimento (`due_at`). Um agendador simples entrega ao agente o que venceu e não decide nada; o agente pode agendar as próprias revisões e informa o motivo. É o padrão do trycompai/crm.

### 6.2 Alçada: o que o agente pode fazer

Regra única: **o que o dono mandou, o agente faz e repete o que entendeu. O que o agente leu ou deduziu, ele mostra antes de gravar.**

| Nível | Quando | Exemplos | Efeito |
|---|---|---|---|
| **Faz direto** | Comando explícito do dono | "Vendi 2 caixas pro João a prazo"; "paguei o boleto do Atacadão"; "pesei 355 g de requeijão"; "próxima etapa"; "congela 200 do lote de hoje"; imprimir etiqueta | Grava e responde com o que entendeu (ex.: "2 caixas para João, R$ 80, vence dia 30") |
| **Mostra e espera o "ok"** | Iniciativa ou leitura do agente | Compra lida de cupom; ajuste de ficha; registrar sobra como perda; plano de produção; ajuste de estoque; conciliação de consumo pendente | Cria uma **proposta** na caixa de decisões. Grava só com a confirmação |
| **Só avisa** | Trabalho proativo | Resumo da manhã, validade, estoque baixo, contas a vencer | Mensagem, sem gravação |
| **Nunca** | — | Apagar ou reescrever histórico; estoque negativo fora da exceção do PRD; alterar produção concluída (só por ajuste visível); comprar, pagar ou movimentar dinheiro | O núcleo recusa |

- **Ambiguidade:** se o agente não tem certeza do que o dono quis dizer (qual cliente, qual lote, qual produto), **pergunta antes**. Não escolhe sozinho.
- **Alçada ajustável:** o dono pode promover um tipo de proposta para "faz direto" com escopo limitado. Exemplo: "compras do fornecedor X abaixo de R$ 200". A alçada é configuração, sem reprogramar.
- **O nível "Nunca" é garantido pelo núcleo,** não pelo prompt.

### 6.3 Ficha técnica viva

O que muda em relação ao PRD (FIC e OP):

1. **Escala por objetivo:** o pedido informa **produto, quantidade de unidades e peso por unidade** (ex.: 50 × 150 g = 7,5 kg). A ficha do produto final guarda a **proporção** de cada componente (ex.: massa 60%, recheio 33%, empanamento 7%) e o rendimento das sub-receitas. O núcleo calcula em cascata até os ingredientes.
2. **Etapas:** cada ficha tem etapas ordenadas. Cada etapa tem instrução curta, tempo (opcional), ponto de checagem (opcional) e foto ou vídeo curto (opcional).
3. **Saída aprovada pelo dono:** **um bloco por preparação, na ordem de fazer**, com os ingredientes escalados, a marcação "separado" e o indicador de estoque (tem / falta X). Esboço aprovado em 19/10/2026.
4. **Aprendizado por estatística, não por IA:** depois de cada produção, o núcleo compara o rendimento real com o previsto nas últimas N produções. Se a diferença for consistente, o agente **propõe** o ajuste.
5. **Preparações são etapas, não estoque (decisão do dono, 19/10/2026):** massa, recheio e empanamento são **sempre feitos na hora**, dentro do mesmo preparo. Não há massa pronta ou congelada em estoque. Por isso, o pedido gera **uma única produção**, que baixa os ingredientes das preparações direto e gera **um único lote** do produto final, vinculado aos lotes dos ingredientes. As preparações aparecem como blocos/etapas do preparo (componente teórico, PVD §5.5). A RN-12 do PRD continua valendo só se, no futuro, uma preparação passar a ser estocada.
6. **Forma final no pedido:** o pedido informa se as unidades terminam **cruas** (para congelar ou guardar) ou **fritas**. Se fritas, a fritura é a última etapa do mesmo preparo: consome o óleo pela referência (DEC-F2-023) e o lote nasce frito. A fritura de lotes crus já guardados continua pelo registro rápido (PRD RF-FRI-01).
7. **Um produto por tamanho (decisão do dono, 19/10/2026):** a receita é a mesma, mas "Coxinha 150 g" e "Coxinha festa 25 g" são produtos separados no estoque, no preço e nas encomendas. Se o pedido pede um tamanho que não existe, o agente oferece criá-lo com um toque, usando a mesma ficha.
8. **Ajuste da ficha** feito pelo dono cria uma nova versão automaticamente (PRD RN-14), sem fluxo de aprovação separado.
9. **Referência de peso (decisão do construtor):** o peso por unidade do pedido é o do salgado **montado e cru**, antes de fritar, assar ou congelar. Fichas de produto final usam **proporção** por componente; fichas de preparação (massa, recheio) mantêm **quantidades e rendimento absolutos**, como no PRD.

### 6.4 Preparo guiado (na tela no MVP; por voz depois)

- A **produção em andamento é estado do servidor**: etapa atual, cronômetros ativos e pesos registrados. Tela, Telegram e voz enxergam o mesmo estado, e é possível trocar de canal no meio do preparo.
- **Fluxo:** o pedido gera a receita escalada. Depois vem o mise en place, onde cada ingrediente pode ser pesado ou marcado com "usei o previsto". Em seguida, as etapas (instrução, ponto, cronômetro). Por fim, o fechamento: quantidade boa, perdas com motivo, sobras e um "como foi?" com campo livre.
- O peso registrado no mise en place **é** o consumo real da OP (substitui a correção no fim, PRD RF-OP-03). O lote é escolhido automaticamente pela validade mais próxima (PRD RN-18), sem aparecer na tela.
- **Cronômetros:** vários ao mesmo tempo, com alarme sonoro e visual, que continuam correndo quando a tela muda de etapa.
- **Tela de cozinha:** botões grandes, uma tarefa por tela, tela que não apaga durante o preparo.
- **Sem faixa de tolerância de peso** e sem escolha de lote na tela (pedido de simplicidade).
- **Troca de lote (decisão do construtor):** se o cozinheiro usou outro lote, ele corrige pela conversa ("usei o frango do lote B") ou no fechamento. A troca fica registrada (PRD RN-18) e a rastreabilidade continua garantida.

### 6.5 Canais

| Canal | MVP | Uso |
|---|---|---|
| Tela web (LAN, responsiva) | Sim | Caixa de decisões, conversa, preparo guiado, consultas, formulários de plano B |
| Telegram (bot privado) | Sim | Fotos de cupom, conversa, avisos proativos, confirmações rápidas |
| Voz | Não (pós-MVP) | Mesmo agente, mesma memória e mesmas ferramentas. Peças de voz (fala para texto, texto para fala, palavra de ativação) de projetos como `omnigentx/jarvis` ou equivalentes, a escolher depois de testar português e ruído |

### 6.6 Telas

1. **Caixa de decisões:** o que o agente preparou e espera um "ok". Aprovar, corrigir e aprovar, ou recusar com um toque. É a tela inicial.
2. **Conversa:** chat com o agente, com o histórico do que ele fez e por quê.
3. **Hoje:** resumo do dia (produções, encomendas, validades, contas). Substitui o painel do PRD RF-REL-01.
4. **Preparo:** a ficha viva e o modo guiado.
5. **Consultas:** estoque e lotes, fichas, custos, contas e relatórios do PRD §16.
6. **Formulários manuais:** os lançamentos do PRD, para quando o agente estiver fora do ar ou errar.

Em cada registro (lote, compra, produção): **o que o agente fez e por quê**, como na aba "Agente" do trycompai/crm.

### 6.7 Trabalhos proativos do MVP

| Tarefa | Quando | Resultado |
|---|---|---|
| Resumo da manhã | Diário, em horário configurável | Mensagem com produções, encomendas, validades, estoque baixo e contas |
| Ler cupom | Ao chegar o documento | Proposta de compra |
| Necessidade de produção | Ao confirmar uma encomenda | Proposta de plano de produção |
| Revisão de rendimento | Ao concluir uma produção | Proposta de ajuste de ficha, quando houver desvio consistente |
| Sobras do dia | Fim do expediente, em horário configurável | Pergunta sobre o destino dos fritos que sobraram (PRD RF-FRI-03) |

### 6.8 Quando a IA falha

- Modelo indisponível ou sem internet: o agente aparece como "fora do ar" na tela. A fila de tarefas acumula e é retomada depois. Telas, formulários e núcleo funcionam normalmente.
- **Orçamento de uso:** um limite configurável de chamadas ao modelo por dia ou por tarefa. Atingir o limite encerra a tarefa normalmente e avisa. Isso controla o custo.
- Leitura de cupom ruim: vira uma proposta com os campos incertos destacados (PRD RN-10). Nunca é gravada direto.

## 7. Escolhas técnicas (decisão do construtor-arquiteto, aceitas pelo dono por delegação)

- **Python** no núcleo e no agente.
- **SQLite** com acesso exclusivo do serviço central.
- **Ferramentas no padrão MCP.**
- **Modelo de IA em nuvem**: família Claude da Anthropic, chamada via SDK oficial. O modelo exato por tarefa fica a cargo do construtor, equilibrando custo e qualidade; por exemplo, um modelo menor para resumos e um maior para leitura de cupom e conversa.
- **Bot do Telegram** pela API oficial, com comunicação de saída (PVD §7).
- **Não usar como base** os repositórios `trycompai/crm` nem `omnigentx/jarvis`. Aproveitar os **padrões** do CRM (fila de tarefas, caminho único de gravação, skills em Markdown, rastro do agente) e, depois, as **peças de voz** do Jarvis ou equivalentes. Justificativa nos dois documentos em `docs/arquitetura/`.

## 8. Deixado ao construtor

- Framework web e de telas (sugestão inicial: Django com htmx, ou equivalente simples).
- SDK de agente e forma de rodar o servidor MCP.
- Esquema físico do banco, desenho da fila de tarefas e da memória de conversa.
- Organização das skills em Markdown.
- Modelos de IA por tarefa e valores padrão de orçamento.
- Divisão em entregas. Referência: PRD §19, que agora precisa incluir o agente desde a primeira entrega utilizável.

## 9. Pendências que continuam abertas

- **REG-01, REG-02 e REG-03** (contador e vigilância sanitária), conforme o PRD §18.
- **PR-03** (impressora), **PR-04** (recuperação de senha) e **PR-05** (hardware).
- Nome do agente.

## 10. Revisões nas decisões aprovadas

| Decisão | Antes | Agora |
|---|---|---|
| DEC-F2-002 | IA e voz fora do MVP | **O agente entra no MVP** (texto: tela e Telegram). A voz continua fora do MVP |
| PRD RF-REL-01 | Painel com indicadores | Tela "Hoje" mais caixa de decisões |
| PRD RF-OP-03 | Consumo corrigido na conclusão | Consumo vem da pesagem no preparo guiado ("usei o previsto" como atalho) |
| PRD RF-FIC-01/02 | Ficha com componentes e rendimento | Mais proporção por componente, escala por quantidade × peso unitário e etapas com tempo, ponto e mídia |
| PRD RF-OP-01/05, RN-12 | Preparações podem ser produzidas e estocadas | Preparações feitas na hora são etapas da produção do produto final; um preparo gera um lote |
| PRD RF-CAD-03/04 | Produto com apresentações | Um produto por tamanho, compartilhando a ficha |
| PRD §14 | Só extensibilidade para IA | Agente como forma principal de operação, com alçada (§6.2) |

Essas revisões geram a **versão 2.0 do PRD**, que fica a cargo do construtor depois da aprovação deste design.
