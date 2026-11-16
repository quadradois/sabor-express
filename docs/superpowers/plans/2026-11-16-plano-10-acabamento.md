# Plano 10 — Acabamento (frito ou assado) e três categorias de venda

Data: 2026-11-16. Branch `claude/acabamento`.

## O que foi decidido

Cada **tipo** de salgado tem um acabamento: frito (coxinha) ou assado
(esfirra). Todo salgado é vendido congelado (cru, para o cliente terminar em
casa) ou já finalizado. Na fala do Chef e nas telas só existem três
categorias: **Congelado**, **Frito** e **Assado**. "Cru congelado" e "frito
fresco" saem de cena.

## O que foi feito

**Acabamento por tipo.** O campo `acabamento` ("frito" ou "assado", padrão
"frito") ficou na **ficha** (`fichas.Ficha`), que é o tipo do salgado: todos os
tamanhos (os itens produto) apontam para ela, então o acabamento vale para a
coxinha de 25 g e para a de 150 g de uma vez. Edita-se em Custos →
"Acabamento (frito ou assado), óleo e indiretos" (`web/referencias`) e no admin
da ficha. A troca passa pelo serviço `cadastros.servicos.definir_acabamento` e
é recusada enquanto houver, no acabamento antigo, lote com saldo, preço ativo
na tabela ou produção em andamento.

**Forma "assado".** Entrou em `estoque.models.FORMAS`. Tudo o que valia para
"frito" vale para "assado": lote, apresentação, critério de validade,
produção, reserva, venda, encomenda, perda, etiqueta, sobras. A trava é uma
só, `estoque.categorias.checar_forma`: salgado frito não tem lote, preço,
produção nem validade "assado", e vice-versa; o erro diz o acabamento
("'Esfirra 100 g' é assado, não frito: o acabamento desse salgado é assado.
Use cru ou assado."). O assado **não soma óleo** no custo.

**Finalização.** `registrar_fritura` (serviço e ferramenta, mesmo nome, 95
ferramentas no total) frita ou assa conforme o acabamento do salgado. A tela
chama-se "Finalização (fritar ou assar)" e o botão diz Fritar ou Assar.
`iniciar_producao` e `concluir_producao` aceitam "assado"; a última etapa da
produção diz "Asse as N unidades." O lote assado tem código `AAMMDD-A<n>` (o
frito continua `F`).

**Três categorias.** Função única `estoque.categorias.categoria(forma,
estado)`, usada pelo agente, pelos `str()` dos modelos, pelas etiquetas e
pelos templates (filtro `categoria`). Na entrada por voz, "congelado" ou
"cru" é o cru congelado, "frito" é o frito fresco, "assado" é o assado fresco.
Pedir o acabamento errado devolve `ConsultaInvalida` com `opcoes`.

**Testes.** `tests/test_acabamento.py` (serviços e telas) e
`tests/test_mcp_agente_acabamento.py` (voz). Os testes existentes que
conferiam "cru congelado" e "frito fresco" passaram a conferir "congelado" e
"frito", sem perder nenhuma verificação.

**Migrações.** `fichas/0004_acabamento` (campo novo, padrão frito),
`estoque/0008_acabamento`, `producao/0005_acabamento` e
`vendas/0005_acabamento` (só as escolhas de forma ganham "assado"). Nenhuma
mexe em dado existente: tudo o que já existe continua frito.

## Decisões tomadas no caminho

- Os nomes internos ficaram: `registrar_fritura`, modelo `Fritura`, endereço
  `/fritura`, `sobras_fritas`. Mudar o nome quebraria o prompt e os atalhos;
  só o que se lê e o que se ouve mudou.
- O que não é de venda continua dito por extenso: cru na geladeira é
  "resfriado", frito que foi para o freezer é "frito congelado". As operações
  de conservação (mudar de fresco para congelado) continuam falando em
  conservação, porque é disso que tratam.
- Na produção, a confirmação ainda diz "cru" ("Iniciar a produção de 10
  Esfirra 100 g, cru"), porque ali ainda não se sabe se vai para o freezer.
- No formulário de preço, forma e conservação continuam em dois campos, com um
  lembrete das três categorias.
- Correção achada nos testes: a trava de troca de acabamento olhava o saldo do
  lote sem a conservação e nunca disparava; passou a somar os movimentos por
  lote e conservação.

## Pendências

- **Mudar o acabamento pela voz.** Não há ferramenta para isso (criar uma
  passaria de 95). Hoje é pela tela. `criar_tamanho` só **diz** o acabamento
  na confirmação.
- **Criar um tipo novo de salgado já como assado.** O tipo nasce frito; quem
  cria marca assado na tela antes de produzir.
- **Prompt do agente.** O trecho novo e as frases a trocar estão em
  [`docs/agente-instrucoes-acabamento.md`](../../agente-instrucoes-acabamento.md);
  falta colar no Monsieur EscofIA e fazer o teste por voz (roteiro no mesmo
  arquivo).
- **Dados no ar.** Depois do merge, rodar `migrate` e marcar na tela quais
  salgados são assados. Se já houver algum salgado assado cadastrado com lote
  ou preço "frito", a troca será recusada até esse estoque sair e esse preço
  ser inativado.

## Dúvidas para o dono

1. Existe salgado que se vende dos dois jeitos, frito **e** assado (por
   exemplo, um pastel de forno e um frito do mesmo recheio)? Hoje cada tipo
   tem um acabamento só; seriam dois tipos separados.
2. O assado gasta alguma coisa que valha a pena contar, como o óleo no frito
   (gás do forno, gema para pincelar)? Hoje o assado custa o mesmo que o cru.
3. O que já está pronto e vai para a geladeira ou para o freezer (frito
   congelado, assado resfriado) se vende? Hoje isso aparece por extenso e fora
   das três categorias.
4. O cru que está na geladeira (resfriado) pode ser vendido como "congelado"?
   Hoje não: congelado é só o que está no freezer.
5. Quer poder dizer ao Chef "a esfirra é assada" para ele marcar sozinho? Isso
   pede uma ferramenta nova de voz.
