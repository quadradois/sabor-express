# Plano 9 — pendências e decisões da execução (fase 2b, ferramentas MCP do agente)

Branch `claude/plano9-agente`. Tasks 15–18 do plano
(`2026-11-13-plano-9-lotes.md`). 92 ferramentas MCP (88 + 4). Testes novos em
`tests/test_mcp_agente_lotes.py`; trecho do prompt, frases a trocar e roteiro
de teste por voz em `docs/agente-instrucoes-lotes.md`.

## O que foi feito

| Ferramenta | Nível | Mudança |
|---|---|---|
| `ver_separacao` | 0 | nova → `separacao_venda` |
| `ver_separacao_encomenda` | 0 | nova → `separacao_encomenda` |
| `contar_lote` | 2 | nova → `ajustar_contagem` (registrada em `OPERACOES`) |
| `conferir_vencido` | 2 | nova → `registrar_perda` / `ajustar_contagem`; "já foram vendidas" devolve o `lote_id` para a venda |
| `registrar_venda`, `entregar_encomenda` | 2 | + `lotes`, `data`, `motivo_vencido`; confirmação com a separação; `dito` com os avisos |
| `registrar_fritura` | 2 | + `lote` (nome falado), `motivo_vencido` |
| `mudar_conservacao` | 2 | + `motivo_vencido`; `lote` pelo nome |
| `cancelar_venda`, `concluir_producao`, `conciliar_consumo` | 2 | + `motivo_vencido` |
| `registrar_perda` | 2 | + `destino` (perda, descarte, consumo da equipe, doação); `lote` pelo nome |
| `registrar_peso`, `registrar_etiqueta` | 1 | `lote` pelo nome; o `dito` fala o nome |
| `ver_decisoes`, `ver_decisao`, `dar_ciencia`, `recusar_decisao`, `aprovar_decisao` | 0/1/2 | conferência do vencido dita como pergunta; lote pelo nome no texto das decisões de validade; origem nova `lotes_deixados` ("lote deixado para trás") |
| `ver_resumo_do_dia` | 0 | "Vencido só sai com motivo; a caixa pergunta se ainda estão aí." e o assunto `lotes_deixados` ("Venda primeiro: ...") |

## Decisões

- **Níveis mantidos.** Todas as ferramentas de venda, entrega, fritura, perda,
  conservação, cancelamento, conclusão e conciliação já eram nível 2; com
  `motivo_vencido` continuam nível 2 (a confirmação repete lote, dia em que
  venceu e motivo).
- **`contar_lote` é nível 2**, como `registrar_perda` e `entrada_estoque`:
  altera saldo e valor do estoque e pode liberar reserva de encomenda.
- **Conferência por `conferir_vencido` (uma ferramenta) em vez de três
  caminhos soltos.** Com ela o modelo usa só o número da decisão que acabou de
  ler e a resposta do dono; não precisa ir buscar `lote_id`/estado em
  `ver_decisao` nem resolver o lote pelo nome. "Estão aqui" e "não sei" viram a
  proposta na mesma chamada. "Já foram vendidas" não grava: devolve o
  `lote_id` e o que perguntar (quantas, de que jeito, para quem, em que dia),
  porque a venda precisa de apresentação, preço e cliente — vai por
  `registrar_venda` com `lotes` e `data`. Para ingrediente, "já foram usadas"
  vira contagem (como no `detalhes.conferencia` do núcleo). A decisão também é
  dita como pergunta em `ver_decisoes`/`ver_decisao`, a partir de `detalhes`.
- **Motivo de contagem na conferência**: sem motivo dito, vai
  "conferência do vencido (número N)" — descreve o fato, não é motivo de
  vencido. `contar_lote` direto exige o motivo dito.
- **Vencido sem motivo** volta como `{"erro": ..., "precisa_motivo": true}`
  com o lote, o dia em que venceu (falado) e "Pergunte o motivo ao dono (nunca
  invente)". Na venda e na entrega isso vem da separação (antes de simular);
  nas outras, da recusa do núcleo ("informe o motivo") convertida em fala.
- **`motivo_vencido` só vai ao núcleo quando há vencido** na separação/porção
  (a trilha não guarda motivo à toa); sem vencido, é ignorado.
- **Confirmação repete a separação** ("De onde sai: ...") calculada pela
  consulta do núcleo com os mesmos itens, lotes e data — a mesma alocação da
  venda. Sem lote indicado, a venda continua sem `lotes` (FEFO na hora de
  confirmar): se o estoque mudar nos 5 minutos da proposta, a baixa pode
  diferir do que foi dito. Passar a alocação como `lotes` marcaria a linha
  como "lote indicado", o que não é verdade.
- **Lote falado** (`agente/lotes.py::resolver_lote`): aceita `lote_id`, nome
  ("lote do dia 8", "segundo lote do dia 8", "dia 28 de outubro"), só o número
  do dia ("10") e o código. Sem o mês, vale o dia mais recente com aquele
  número. Dois lotes no mesmo dia sem ordinal → recusa com `opcoes`.
  Candidatos: porções com saldo (na forma e conservação da apresentação, na
  venda; vencidas inclusive).
- **`data` falada** (hoje, ontem, anteontem, dia 12, 12 de novembro,
  AAAA-MM-DD) usa o mesmo leitor de datas das despesas (`passado=True`); data
  futura é recusada pelo núcleo.
- **`ver_separacao` devolve `texto`** (padrão das ferramentas de leitura), não
  `dito` (que é das de escrita nível 1).
- **Leitura da separação**: o `texto` fala o texto de cada linha e os avisos
  deixado, falta, só vencido e vencido sem motivo; "vence hoje/amanhã" já está
  na linha (não repete).
- **Destino da perda**: o verbo da confirmação segue o destino ("Descartar",
  "Dar para consumo da equipe", "Doar"); destino "perda" de lote vencido
  continua dizendo "Descartar" (como antes).
- O agente não bloqueia nada além do núcleo: deixado é aviso; `dar_ciencia` na
  conferência continua possível (o prompt pede `conferir_vencido`).

## Mudança fora de `agente/`, `tests/` e `docs/`

- `vendas/lotes.py`: concordância "Falta 1 un" / "Faltam 2 un" no texto da
  separação e no aviso `falta` (exceção autorizada), com teste
  (`test_concordancia_falta_um`). Nada mais no núcleo.

## Testes ajustados

Textos que falavam o código do lote ou a frase antiga:
`test_mcp_agente_vendas.py` (confirmações de venda/entrega com "De onde sai",
fritura e perda com "lote do dia N"), `test_mcp_agente_escrita.py` (etiqueta e
mudança de conservação; total de ferramentas), `test_mcp_agente_compras.py`
(conciliação "com o lote do dia N"), `test_mcp_agente_decisoes.py` (frase do
resumo; rótulo "conferência do vencido"), `test_mcp_agente_custos.py` e
`test_mcp_agente_despesas.py` (total de ferramentas: 92).

## Fica de fora / pendências

| Item | Por quê / quando |
|---|---|
| Aplicar o trecho e as 5 trocas de frase no prompt do Chef (`Monsieur Escofia/prompts/monsieur-escofia.md`) | Fora deste repositório; feito por quem cuida do prompt, a partir de `docs/agente-instrucoes-lotes.md` |
| Teste por voz (roteiro de 10 passos) | Precisa do dono |
| Contar lote **sem saldo** no sistema ("achei 5 de um lote zerado") | `contar_lote` só acha porções com saldo; dá para aceitar `lote_id` de porção zerada se o dono pedir |
| Venda sem lote indicado não "trava" a alocação dita na proposta | Ver decisão acima; rever se aparecer divergência |
| `conciliar_consumo` com vencido não tem teste próprio por voz | Usa o mesmo caminho genérico (`pedir_motivo`) coberto por fritura, conservação, devolução e produção |
| Saldo/conservação na data passada, conferência no último dia de validade (Q1) | Pendências do núcleo (fase 1), sem mudança aqui |
