# Plano 8 — pendências e decisões da fase 2b (ferramentas do agente de voz)

Branch `claude/plano8-agente-despesas`. Onze ferramentas novas — sete de leitura (nível 0), uma de nível 1 e três
de nível 2 — em `agente/despesas.py` (despesas) e `agente/custos.py` (resultado, indireto real, estudo e simulação
de preço, ponto de equilíbrio), registradas em `agente/ferramentas.py` (88 no total). `ver_margem`,
`ver_margem_tabela`, `ver_relatorio`, `ver_resumo_do_dia`, `ver_decisoes` e `ver_contas` passaram a falar as
despesas e a margem com indiretos. 24 testes em `tests/test_mcp_agente_despesas.py`; suíte inteira verde (498);
`makemigrations --check` sem mudanças. Docs: `docs/agente-mcp.md`, `docs/agente-instrucoes-despesas.md` (trecho do
prompt, frases a substituir e roteiro de teste por voz), `docs/agente-instrucoes-custos.md` e
`docs/agente-instrucoes-vendas.md` (frases trocadas). Nada mudou em `financeiro/`, `custos/`, `vendas/`, `web/`
nem em modelos.

## Ferramentas

| Ferramenta | Nível | Núcleo |
|---|---|---|
| `ver_despesas(mes)` | 0 | `despesas_do_mes` + `despesas_periodo` (por categoria) |
| `ver_despesas_a_pagar(situacao)` | 0 | `despesas_em_aberto` |
| `ver_resultado(periodo)` | 0 | `relatorio_periodo` (`depois_das_despesas`) |
| `ver_indireto_real(mes)` | 0 | `indireto_real` |
| `ver_estudo_preco(produto, canal, tabela)` | 0 | `estudo_preco` |
| `simular_preco(produto, apresentacao, preco, sobra_pct, canal, ...)` | 0 | `simular_preco` |
| `ver_ponto_equilibrio(produto, apresentacao, canal, mes, ...)` | 0 | `ponto_equilibrio` |
| `informar_valor_despesa(nome, valor, mes)` | 1 | `informar_valor_despesa` |
| `pagar_despesa(nome, valor, data_pagamento, forma, mes, categoria)` | 2 | `pagar_despesa_do_mes`, `registrar_pagamento` (avulsa a pagar) ou `lancar_despesa(paga=True)` |
| `lancar_despesa(descricao, valor, categoria, vencimento, paga, ...)` | 2 | `lancar_despesa` |
| `cancelar_despesa(motivo, nome, mes, conta_id)` | 2 | `cancelar_despesa` |

## Decisões tomadas na execução

- **Alçada:** anotar pagamento, lançar e cancelar despesa são **nível 2** (proposta simulada + "Confirma?"), como
  pedido pela coordenação e como o pagamento de fornecedor; o contrato do plano dizia "nível 1 com confirmação",
  que na prática é o nível 2 deste sistema. `informar_valor_despesa` ficou **nível 1** (contrato): não movimenta
  dinheiro, se refaz falando de novo e o núcleo recusa mudar valor com pagamento anotado.
- **`pagar_despesa` decide sozinho entre mensal e avulsa:** primeiro procura despesa em aberto com o nome (mensal
  de qualquer mês até o atual, ou avulsa a pagar); na avulsa a pagar anota com `registrar_pagamento` (já existia
  na tabela de operações); só sem nada em aberto lança uma avulsa já paga. Se a mensal do mês já está paga, recusa
  (não lança em dobro) e pede para confirmar se é outra conta (`lancar_despesa(paga=True)`).
- **`lancar_despesa` recusa lançar como avulsa uma despesa mensal deste mês ainda em aberto** ("Internet de
  novembro já é uma despesa mensal, sem valor: diga o valor dela"), em vez de só avisar `parecidas` depois. Se o
  nome não casar e o núcleo devolver `parecidas`, o "Confirma?" avisa.
- **Nome falado:** a despesa casa por `nome + categoria` ("luz" → Energia), com trocas simples (luz, botijão,
  diarista, faxina, salário, DAS, wifi) e palavras de enchimento ignoradas ("conta de", "boleto do"). Categoria de
  avulsa pelo mesmo nome; sem categoria reconhecida, pergunta com `opcoes` (nunca cai em "Outras" sozinho).
- **Datas faladas:** "dia 20" vira o próximo dia 20 no vencimento e o último dia 20 no pagamento; pagamento em data
  futura é recusado. Na fala, vencimento "dia 10"/"amanhã"/"dia 2 de dezembro" e o mês "Energia de novembro".
- **Resultado:** `ver_relatorio` abre com "tudo estimado." (antes: "tudo estimado e antes das despesas.") e ganhou
  a frase do resultado depois das despesas no fim; a linha "Resultado estimado, antes das despesas" e o "O
  resultado não desconta ..." continuam. Sem nenhuma despesa lançada no período, **não fala número** depois das
  despesas (seria igual ao antes e enganaria). Com despesa sem valor: "Ainda incompleto: falta o valor de X; o
  resultado de verdade é menor que este." Mensais ainda sem pagamento anotado são ditas ("pelo valor lançado").
  `ver_resultado` é a versão curta (antes, despesas, depois, por categoria).
- **Margem com indiretos** vem **depois** da frase "É margem estimada: não inclui ... indiretos ...", como "Com os
  indiretos de referência por salgado (mão de obra, energia e gás), a margem estimada fica em ..." — duas margens,
  cada uma dita pelo nome. Sem referência em alguma linha, diz quantos itens ficaram sem indireto.
- **Estudo de preço:** canais com a mesma taxa são ditos juntos ("no balcão, dinheiro e balcão, pix, sobram ...");
  taxa não informada = "taxa não informada, sem conta". `simular_preco` aceita "balcão" (dois canais de mesma taxa:
  vale o primeiro); canais de taxas diferentes com o mesmo nome ("cartão") → pergunta. Quando o preço arredondado
  ao centavo não dá exatamente a sobra pedida, a fala diz "(o preço foi arredondado ao centavo)".
- **Resumo do dia:** dois assuntos novos (despesa vencida sem valor; sem valor vencendo logo). Despesa com valor já
  está em contas vencidas/a vencer: um aviso por situação.
- **Fora de `agente/`, `tests/` e `docs/`: nada.** Ajustes de fala em `agente/compras.py` (`mes_falado`,
  `dia_falado`, `sem_mes_numerico`; `ver_contas` dizia "compra None" para despesa) e `agente/decisoes.py`
  (`falavel` converte "11/2026" e tira ", parcela 1 de 1,"; origem "despesa sem valor").
- Testes antigos ajustados: contagem 77 → 88 (`test_mcp_agente_custos`, `_vendas`, `_escrita`); "indireto" e
  "preco" no nome agora existem só em ferramentas de leitura (`ver_indireto_real`, `ver_estudo_preco`,
  `simular_preco`); abertura do `ver_relatorio`.

## Fica para depois

| Item | Quando / quem |
|---|---|
| Aplicar no prompt do Monsieur EscofIA o trecho "Despesas, resultado e estudo de preço:" e as **três trocas de frase** (ver `docs/agente-instrucoes-despesas.md`); teste por voz com o roteiro | Coordenação |
| Cancelar despesa mensal **sem valor** ("não teve internet em outubro", Q9): `financeiro.despesas.cancelar_despesa` pede `conta_id` e a despesa sem valor não tem conta; hoje o agente diz que não dá por voz | Núcleo: `cancelar_despesa_do_mes(despesa_do_mes_id, motivo)` (pedir à coordenação) |
| Estornar só o pagamento de uma despesa (sem cancelar): `estornar_pagamento` do agente acha pagamento por fornecedor ou `pagamento_id`; despesa não tem fornecedor | Se o dono pedir; hoje "cancelar" estorna junto, ou pela tela |
| Pagamento parcial de despesa mensal por voz: em `pagar_despesa_do_mes` o valor dito é o valor **real** da conta (corrige o previsto), não um pagamento parcial; a fala do "Confirma?" deixa isso explícito | Se o dono pagar contas em partes |
| Ponto de equilíbrio com o canal de cartão sem taxa → erro "taxa não informada" (correto); despesas do mês inteiro mesmo no mês em andamento (regra do núcleo) | — |
| `ver_estudo_preco` fala até três jeitos de vender; o resto fica nos dados | Se as listas ficarem longas |
| Desempenho: `ver_despesas_a_pagar`/`pagar_despesa` leem `despesas_em_aberto` inteiro (poucas por mês); `simular_preco` herda a pendência do núcleo (calcula todas as apresentações) | Rever com centenas de despesas/apresentações |
