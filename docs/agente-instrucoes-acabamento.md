# Instruções do agente: acabamento (frito ou assado) e as três categorias

Trecho para colar no prompt do Monsieur EscofIA, depois das instruções de
vendas, de custos e de lotes. Texto corrido de propósito: é lido pelo modelo de
voz. Vem do Plano 10
([`2026-11-16-plano-10-acabamento.md`](superpowers/plans/2026-11-16-plano-10-acabamento.md)).

## Trecho para o prompt

Acabamento e categorias: cada tipo de salgado tem um acabamento, frito ou assado. Coxinha é frita, esfirra é assada, e isso vale para todos os tamanhos daquele salgado. Todo salgado é vendido de um de dois jeitos: congelado, que é o cru que o cliente termina em casa, ou já pronto, frito ou assado conforme o acabamento dele. Por isso, na conversa só existem três categorias: congelado, frito e assado. Nunca diga cru congelado nem frito fresco; diga só congelado, frito ou assado, do jeito que o sistema devolve. Quando a pessoa disser a categoria, passe em forma exatamente a palavra dita, congelado, frito ou assado, e não precisa passar conservação. Se a pessoa disser cru numa venda, é o congelado.

Você não precisa saber de cabeça qual salgado é frito e qual é assado: o sistema sabe. Se alguém pedir esfirra frita e a esfirra for assada, a ferramenta devolve um erro dizendo que esfirra é assado, não frito, com as opções do que há para vender. Diga isso com as palavras do sistema, leia as opções de forma curta e pergunte qual a pessoa quer; nunca troque por conta própria frito por assado, nem assado por frito.

Quando alguém disser assei quarenta esfirras, trinta e oito boas, duas queimaram, use a mesma ferramenta da fritura, registrar_fritura, com o produto, a quantidade, as boas e o motivo das perdas. O sistema decide sozinho se é fritar ou assar, pelo acabamento do salgado, e a confirmação já vem com o verbo certo. Leia a frase inteira e espere o sim, como em toda fritura. O assado não gasta óleo, então o custo do assado não tem óleo; não comente isso se ninguém perguntar. Quando perguntarem o que sobrou de frito ou de assado, use ver_sobras. Quando perguntarem o custo, ver_custo já diz frito ou assado conforme o salgado.

Na produção, se o dono disser que o salgado já sai pronto, passe em forma frito ou assado como ele falou; se disser que é para congelar ou guardar cru, passe cru. Se o sistema responder que aquele salgado é do outro acabamento, pergunte se a produção é para guardar cru ou se já sai pronto, com as opções que vieram. Ao criar um tamanho novo, a confirmação diz o acabamento do salgado; leia como veio. Você não consegue mudar o acabamento de um salgado pela voz: se o dono pedir, diga que isso se muda pela tela, em Custos, na parte de acabamento, óleo e indiretos.

## Trechos dos outros documentos que mudam

Os documentos de instruções já estão corrigidos neste PR. No prompt que está
no ar, troque estas frases:

Em vendas ([`agente-instrucoes-vendas.md`](agente-instrucoes-vendas.md)):

- De: "a forma, cru ou frito, e a conservação; o cliente vai pelo nome."
  Para: "a categoria, que vai em forma: congelado, frito ou assado; o cliente
  vai pelo nome."
- De: "Quando alguém disser fritei quarenta coxinhas, trinta e oito boas, duas
  estouraram, chame registrar_fritura com o produto, a quantidade frita, as
  boas e o motivo das perdas;" Para: "Quando alguém disser fritei quarenta
  coxinhas, trinta e oito boas, duas estouraram, ou assei quarenta esfirras,
  chame registrar_fritura com o produto, a quantidade frita ou assada, as boas
  e o motivo das perdas;"
- De: "Quando perguntarem o que sobrou de frito, use ver_sobras." Para:
  "Quando perguntarem o que sobrou de frito ou de assado, use ver_sobras."
- De: "pergunte qual, pela conservação, se é cru ou frito, ou pelo dia do
  lote" Para: "pergunte qual, se é congelado, frito ou assado, ou pelo dia do
  lote". A mesma frase aparece no trecho de lotes
  ([`agente-instrucoes-lotes.md`](agente-instrucoes-lotes.md)).

Em custos ([`agente-instrucoes-custos.md`](agente-instrucoes-custos.md)):

- De: "diga cru e frito como vierem" Para: "diga cru e frito, ou assado, como
  vierem".

A frase "Se ele perguntar de qual conservação saiu o cru, pergunte à pessoa",
da fritura, continua valendo: é a única hora em que a conservação do cru entra
na conversa, quando há cru na geladeira e no freezer ao mesmo tempo.

## Roteiro de teste por voz

Antes (no banco de **teste**, nunca no `db.sqlite3` real), pela tela:

- **Salgados:** Coxinha 150 g (acabamento frito) e Esfirra 100 g. Em Custos →
  "Acabamento (frito ou assado), óleo e indiretos", marque a Esfirra como
  **assado**.
- **Validade:** critério de 1 dia para o assado fresco da Esfirra.
- **Preços da Esfirra 100 g:** "unidade", congelado (cru, congelado), 3 reais;
  "unidade assada", assado (assado, fresco), 5 reais.
- **Estoque:** um lote de Esfirra 100 g congelado com 50 unidades e um de
  Coxinha 150 g congelado. Backup em dia.

| # | O dono fala | Esperado |
|---|---|---|
| 1 | "Quais os preços da esfirra?" | `ver_precos`: "unidade de Esfirra 100 g, congelado, 3 reais, dá para vender 50 agora; unidade assada de Esfirra 100 g, assado, 5 reais, dá para vender 0 agora". Não fala "cru congelado" nem "fresco". |
| 2 | "Assei quarenta esfirras, trinta e oito boas, duas queimaram." | `registrar_fritura`: "Assar 40 unidades de Esfirra 100 g do lote ..., congelado, ...: 38 boas e 2 perdidas (queimaram). Custo de ... por unidade assada; o assado fica fresco e vale até amanhã. Confirma?" e **espera** o sim. |
| 3 | "O que sobrou de assado?" | `ver_sobras`: "Sobras assadas: 38 unidades. 38 unidades de Esfirra 100 g assadas hoje." |
| 4 | "Vendi duas esfirras assadas." | `registrar_venda`: "Vender 2 unidades assadas de Esfirra 100 g, assado, a 5 reais cada. Total 10 reais, à vista. Sai do lote do dia ..., que vence amanhã. Confirma?"; grava só com o sim. |
| 5 | "Vendi duas esfirras fritas." | Não grava nada. Diz o erro do sistema, "Esfirra é assado, não frito", lê as duas opções (congelado e assado) e pergunta qual. Não troca sozinho. |
| 6 | "Vendi cinco esfirras congeladas." | `registrar_venda`: "Vender 5 unidades de Esfirra 100 g, congelado, a 3 reais cada. Total 15 reais ...". Sem "cru". |
| 7 | "Quanto me custa uma esfirra?" e "e uma coxinha?" | `ver_custo`: na esfirra, "... cru; assado custa o mesmo, o forno não soma óleo"; na coxinha, o frito continua com o óleo. |
| 8 | "Fritei dez coxinhas." | `registrar_fritura`: "Fritar 10 unidades de Coxinha 150 g ...: 10 boas. Custo de ... por unidade frita; o frito fica fresco ... Confirma?". A mesma ferramenta, com o verbo certo. |
