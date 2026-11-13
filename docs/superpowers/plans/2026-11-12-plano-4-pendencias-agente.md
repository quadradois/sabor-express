# Plano 4, fase 2b — pendências das ferramentas do agente

O que ficou de fora ou depende de outra fase, achado ao ligar a caixa de
decisões, o resumo do dia, o histórico e o backup ao servidor MCP
(`agente/decisoes.py`). Nenhum modelo, serviço ou regra do núcleo mudou; tudo
usa o "Contrato para a fase 2" de `2026-11-12-plano-4-decisoes.md`.

## Núcleo (pedir à coordenação)

- **Texto das decisões não é todo falável.** Os geradores
  (`decisoes/geradores.py`) escrevem datas como "11/11", dinheiro como
  "R$ 100,00" e, para lote sem código, "no lote sem lote" (o `codigo` de
  `estoque.servicos.porcoes` vem "sem lote"). O agente fala o texto da decisão
  como está — é o que o dono aprova —, então a voz lê "onze barra onze" e
  "baixar do lote sem lote". Sugestão: os geradores usarem datas faladas
  ("amanhã", "em 11 de novembro") e omitirem o código quando não houver; a tela
  também ganha.
- **`resumo_do_dia()["totais"]["operacoes_hoje"]` conta a rotina.** Cada rodada
  de `rotina_diaria` grava uma operação por gerador mais a de expirar (dez por
  rodada; de hora em hora, mais de cem por dia). O agente fala só o que não é
  do canal `sistema` (contando pelo `historico_operacoes`); a tela "Hoje" vai
  ter o mesmo problema. Sugestão: o resumo separar `operacoes_hoje` sem a
  rotina.
- **Backup fora do resumo do dia.** `resumo_do_dia` não traz o backup
  (RF-ADM-06 ficou "para depois do backup", que já entrou). O agente junta por
  conta própria: com backup atrasado ou ausente (`backup.situacao.situacao_backup`),
  o resumo falado ganha um assunto sério logo depois do vencido. Sugestão: o
  núcleo pôr `backup` no `resumo_do_dia` para a tela e o agente lerem o mesmo.

## Decisões a confirmar com o dono

- Alçada seguida do plano (Q5): `aprovar_decisao` é nível 2 (repete e espera o
  "sim"); `dar_ciencia` e `recusar_decisao` são nível 1 (gravam na hora e
  repetem). Mudar é trocar o `@escrita(n)` em `agente/ferramentas.py`.
- O número falado é o `decisao_id` ("número 12"), não a posição na lista ("a
  primeira"): o dono disse que quer poder dizer "aprova a doze", e a posição
  muda quando a rotina roda no meio da conversa. O risco de "doze" ouvido como
  "dois" é coberto pelo "Confirma?" com o texto da decisão (nível 2); na
  ciência e na recusa (nível 1), o `dito` repete o texto do item.
- O resumo do dia e a caixa falam no máximo três assuntos/itens por vez e
  oferecem o resto (`MAX_FALADOS = 3` em `agente/decisoes.py`).

## Para depois

- **Operações novas da caixa.** O "Confirma?" de `aprovar_decisao` descreve o
  efeito só de `conciliar_consumo` (`agente.decisoes._efeito`). Quando o Plano 5
  acrescentar a compra lida de cupom em `decisoes.servicos.OPERACOES`, incluir
  a frase do efeito ali (sem ela, o "Confirma?" lê só o texto da decisão).
- **Decisões já decididas pela voz.** `ver_decisoes` só lê as pendentes; "o que
  eu recusei esta semana?" responde pelo `ver_historico(operacao="recusada")`
  ou, decisão por decisão, pelo `ver_decisao`. Se o dono pedir, uma opção
  `situacao` em `ver_decisoes` usa `decisoes(situacao=None)`.
- **O agente não cria itens na caixa.** `criar_decisao` com origem `agente`
  (ex.: "me lembra de ver o freezer") não tem ferramenta; entra se o dono pedir.
- **Opcional da Task 12, não feito:** `agente.consultas.estoque` e `validades`
  ainda comparam o saldo bruto; passar a usar `estoque.servicos.disponivel` e
  `porcoes` mudaria respostas de ferramentas já testadas por voz — fica para
  uma rodada com teste por voz.
- `ver_historico` filtra autor e operação em Python sobre o período inteiro
  (`historico_operacoes(limite=None)`). Suficiente para uma cozinha; rever se o
  período "mes" ficar lento.
- Validar no Gemini Live que o número dito por extenso ("doze") chega como
  inteiro em `decisao_id`.
