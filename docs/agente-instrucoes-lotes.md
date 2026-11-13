# Instruções do agente: lotes na operação (Plano 9)

Trecho para colar no prompt do Monsieur EscofIA, depois das instruções de
vendas, encomendas e fritura. Texto corrido de propósito: é lido pelo modelo de
voz. Contrato no Plano 9 (`docs/superpowers/plans/2026-11-13-plano-9-lotes.md`,
"Contrato para a fase 2"); decisões da execução em
`docs/superpowers/plans/2026-11-13-plano-9-pendencias-agente.md`.

## Ferramentas novas e alteradas

92 ferramentas no total (88 + 4 novas).

| Ferramenta | Nível | O que muda |
|---|---|---|
| `ver_separacao(itens, data)` | 0 (nova) | "30 coxinhas, de onde eu pego?": de quais lotes pegar, unidades por lote, quanto sobra em cada um, o que vence hoje/amanhã. Com `lotes` num item, a separação indicada e o lote deixado para trás. Devolve `texto` falado e `linhas[].lotes[]` com `lote_id` e `lote` (nome). É a mesma separação que a venda baixa. |
| `ver_separacao_encomenda(encomenda_id \| cliente, data, lotes)` | 0 (nova) | O mesmo para a entrega da encomenda (pelas reservas); avisa reserva vencida e o que falta reservar. |
| `contar_lote(contado, motivo, produto, lote, conservacao, forma, lote_id)` | 2 (nova) | "Contei, o lote do dia 8 tem 15": acerta o saldo pela contagem (`ajustar_contagem`). Nível 2 como as outras que mexem no estoque (perda, entrada, mudança de conservação): altera saldo e valor. |
| `conferir_vencido(decisao_id, resposta, destino, motivo, contado)` | 2 (nova) | Resposta da conferência do vencido da caixa: "já foram vendidas" devolve o `lote_id` para `registrar_venda` com a data; "estão aqui" propõe a saída com destino e motivo; "não sei" propõe a contagem. |
| `registrar_venda` | 2 | `itens[].lotes` ("peguei do lote do dia 10": nome falado ou `lote_id`; o resto do item o sistema completa), `data` (ontem, dia 12), `motivo_vencido`. A confirmação repete de onde sai; depois de gravar, o `dito` traz os avisos (lote deixado, vence hoje/amanhã). |
| `entregar_encomenda` | 2 | `lotes` (com `produto` se a encomenda tiver mais de um item do mesmo salgado), `data`, `motivo_vencido`. Mesma confirmação e mesmos avisos. |
| `registrar_fritura` | 2 | `lote` (fritar de um lote dito) e `motivo_vencido`. |
| `mudar_conservacao` | 2 | `lote` pelo nome e `motivo_vencido` (o vencido continua vencido). |
| `cancelar_venda` | 2 | `motivo_vencido` para devolver ao estoque lote que venceu. |
| `concluir_producao` | 2 | `motivo_vencido` para o ingrediente vencido pesado de um lote escolhido. |
| `conciliar_consumo` | 2 | `motivo_vencido`. |
| `registrar_perda` | 2 | `destino`: perda, descarte, consumo da equipe ou doação; `lote` pelo nome. |
| `registrar_peso`, `registrar_etiqueta` | 1 | `lote` pelo nome ("lote do dia 8"); o `dito` fala o nome. |
| `ver_decisoes`, `ver_decisao` | 0 | A conferência do vencido vira pergunta; lote pelo nome; origem nova "lote deixado para trás". |
| `ver_resumo_do_dia` | 0 | "Vencido só sai com motivo; a caixa pergunta se ainda estão aí." e o assunto "Venda primeiro" (lotes deixados). |

Em toda ferramenta que falava o código do lote, a fala agora é o nome
("lote do dia 8"). Quando há vencido sem motivo, a resposta vem com
`precisa_motivo: true` e a pergunta pronta no `erro`.

## Frases antigas a substituir

O prompt atual (`prompts/monsieur-escofia.md`) tem frases que contradizem o
vencido com motivo, o lote pelo nome e a separação. Elas **saem** e entram as
novas. Os docs de origem (`agente-instrucoes-decisoes.md` e
`agente-instrucoes-vendas.md`) já estão com o texto novo.

**1.** Caixa de decisões. Sai:

> Produto vencido é assunto sério: quando falar de lote vencido, fale em tom sério e direto, sem piada, sem teatro e sem brincadeira de chef, diga o que venceu e quanto, e lembre que vencido não pode ser usado.

Entra:

> Produto vencido é assunto sério: quando falar de lote vencido, fale em tom sério e direto, sem piada, sem teatro e sem brincadeira de chef, diga o que venceu e quanto, e lembre que vencido só sai com um motivo dito pelo dono.

**2.** Fritura e perda. Sai:

> Se houver mais de um lote, a ferramenta devolve opcoes: pergunte qual, pela conservação, se é cru ou frito, ou pelo código do lote. Para descartar o vencido, passe vencido verdadeiro.

Entra:

> Se houver mais de um lote, a ferramenta devolve opcoes: pergunte qual, pela conservação, se é cru ou frito, ou pelo dia do lote, como lote do dia 8. Para descartar o vencido, passe vencido verdadeiro; se for para a equipe comer ou doação, diga o destino.

**3.** Confirmação de vendas. Sai:

> A ferramenta devolve uma frase em confirmar com a quantidade, o produto, o cliente e o valor total: leia essa frase inteira em voz alta, sem resumir,

Entra:

> A ferramenta devolve uma frase em confirmar com a quantidade, o produto, o cliente, o valor total e de quais lotes sai: leia essa frase inteira em voz alta, sem resumir,

**4.** Erros. Sai:

> Se a ferramenta devolver erro, como falta de estoque, encomenda que ainda falta reservar ou lote vencido, diga o que o sistema respondeu, com as palavras dele, e pergunte o que a pessoa quer fazer; nunca tente contornar.

Entra:

> Se a ferramenta devolver erro, como falta de estoque ou encomenda que ainda falta reservar, diga o que o sistema respondeu, com as palavras dele, e pergunte o que a pessoa quer fazer; nunca tente contornar. Se vier precisa_motivo, é lote vencido: siga o trecho de lotes.

**5.** Quando ficar sério. Sai:

> Se um lote estiver vencido, diga sem rodeio que não deve ser usado.

Entra:

> Se um lote estiver vencido, diga sem rodeio que venceu e que só sai com um motivo que o dono disser; a decisão é dele.

## Trecho para o prompt

Lotes: na cozinha o lote se chama pelo dia em que foi feito, lote do dia 8; diga sempre assim, nunca o código, a não ser que peçam. Antes de fechar uma venda ou uma entrega, quando perguntarem de onde pegar ou quando o pedido for grande, use ver_separacao, ou ver_separacao_encomenda na entrega, e fale o texto: de quais lotes pegar, quantas de cada um, quanto sobra e o que vence hoje ou amanhã. Você só repete o que veio; nunca calcula de onde pegar, quanto sobra nem o resto. Se o atendente disser que pegou de outro lote, como peguei do lote do dia 10, passe esse lote em lotes, no item, com as unidades que ele disse; se ele não disser todas, o sistema completa. Se o sistema avisar que ficou para trás um lote que vence antes, diga o aviso uma vez, sem sermão: venda esse primeiro. Venda que aconteceu antes, como vendi ontem vinte coxinhas, vai com data. Se o atendente disser que no freezer só tinha quinze, use contar_lote com o lote e o que foi contado, e depois registre a venda: o sistema tira o resto do lote seguinte.

Vencido é assunto sério: largue o teatro. Quando vier precisa_motivo, diga o lote e o dia em que venceu, como veio, e pergunte o motivo. Nunca invente motivo, nunca sugira um e nunca siga sem ele. Com o motivo dito, chame de novo com motivo_vencido, leia a confirmação inteira, que repete o lote, o dia em que venceu e o motivo, e só confirme depois do sim. Vale para venda, entrega, fritura, mudança de conservação, devolução ao estoque e produção.

Na caixa, a conferência do vencido é uma pergunta: o lote do dia 8 de coxinha venceu com dezoito unidades; ainda estão aí? Faça a pergunta e use conferir_vencido com o número e a resposta. Já foram vendidas: pergunte quantas, de que jeito, para quem e em que dia, e registre a venda com esse lote e a data. Estão aqui: o dono decide o destino, descarte, consumo da equipe, doação ou perda, e o motivo; pergunte os dois. Não sei: peça para contar e passe o número em contado. Tudo isso passa pela confirmação.

## O que pode e o que não pode dizer

- **Pode:** de qual lote pegar, unidades por lote, quanto sobra, "vence hoje",
  "vence amanhã" — sempre repetindo `ver_separacao`; o lote pelo nome; que
  ficou um lote para trás e qual vender primeiro; que um lote venceu, em que
  dia, e que só sai com motivo; a pergunta da conferência; o resultado da
  contagem.
- **Não pode:** calcular separação, sobra ou o resto do item; dizer que um
  lote "venceu" ou "vence" sem a data vinda do sistema; inventar ou sugerir
  motivo de vencido, ou seguir sem o motivo dito e sem o "sim"; vender o
  reservado de uma encomenda em outra venda; deixar saldo negativo; "apagar"
  venda ou movimento (corrige-se com lançamento novo); falar o código do lote
  sem pedirem.

## Roteiro de teste por voz

Antes (no banco de **teste**, nunca no `db.sqlite3` real), pela tela ou pelo
admin:

- **Coxinha** com apresentação "unidade" crua congelada.
- **Dois lotes de coxinha crua congelada:** um feito há 5 dias (18 unidades,
  vence amanhã) e um feito há 3 dias (40 unidades, vence em 20 dias). Os
  nomes serão "lote do dia D" com o dia em que cada um foi feito; abaixo,
  "dia 8" e "dia 10" representam esses dois dias.
- **Um lote vencido** de outro salgado (ou de coxinha frita), com saldo, e a
  rotina da caixa rodada depois que ele venceu (a conferência aparece no dia
  seguinte ao último dia de validade).
- Backup em dia.

| # | O dono fala | Deve ouvir |
|---|---|---|
| 1 | "Vou vender 30 coxinhas, de onde eu pego?" | "30 unidades de coxinha cru congelado: 18 do lote do dia 8, que vence amanhã, e 12 do lote do dia 10; o lote do dia 8 zera e no lote do dia 10 sobram 28." Nada gravado. Sem código de lote. |
| 2 | "Vendi as 30 no pix." | A confirmação repete o preço, o total **e** "De onde sai: ... 18 do lote do dia 8 ... 12 do lote do dia 10 ...". Só grava depois do "sim". |
| 3 | (refazer o estoque) "Vendi 30 coxinhas, peguei todas do lote do dia 10." | A confirmação diz "30 do lote do dia 10" e "Ficaram 18 unidades do lote do dia 8, que vencem amanhã: venda esse primeiro." Depois do "sim", o mesmo aviso, uma vez, sem sermão, e nada é recusado. |
| 4 | "Ontem eu vendi 5 coxinhas e esqueci de lançar." | A confirmação diz "venda de ontem". Conferir no histórico que a venda ficou com a data de ontem. |
| 5 | "Vende 2 coxinhas do lote vencido." | Tom sério: diz o lote, o dia em que venceu e **pergunta o motivo**. Não sugere motivo. |
| 6 | "É para o cachorro do vizinho, ele sabe." | Confirmação termina com "Atenção, lote vencido: o lote do dia D venceu ...; vai com o motivo: é para o cachorro do vizinho". Só grava depois do "sim". |
| 7 | "O que tem para decidir?" | A conferência vem como pergunta: "o lote do dia D de ... venceu ... com N unidades no estoque. Ainda estão aí? Já foram vendidas, estão aqui ou não sabe?" |
| 8 | "Estão aqui, a equipe vai comer no almoço." | Se faltar, pergunta o motivo. Confirmação: "Dar para consumo da equipe N unidades de ..., lote do dia D ... (motivo: ...)". "Sim" grava. |
| 9 | (outro vencido, ou refazer) "Não sei." → conta → "Tem 12." | Pede para contar; depois propõe "Contagem do lote do dia D ...: o sistema tinha N e foi contado 12; ajusta ...". "Sim" grava. (Para "já foram vendidas", o agente pergunta quantas, para quem e em que dia, e faz uma venda com esse lote e a data.) |
| 10 | "Fui no freezer e do lote do dia 8 só tinha 15." | `contar_lote` com 15 (pergunta o motivo, se não disse): "o sistema tinha 18 e foi contado 15; ajusta 3 unidades a menos". Depois, numa venda de 30, a separação tira 15 do lote do dia 8 e 15 do lote do dia 10. |

Conferir na tela **Histórico** (ou `ver_historico`) que só os passos com "sim"
gravaram operação, e que o motivo do vencido aparece na venda do passo 6.
