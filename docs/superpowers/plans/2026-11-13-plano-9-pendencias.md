# Plano 9 — pendências e decisões da execução (fase 1, núcleo)

Branch `claude/recursing-solomon-ed677a`. Suíte verde (543 testes: 529 de antes + 14 novos em `tests/test_lotes_operacao.py`); `makemigrations --check` sem mudanças.

## Migrações

- `estoque 0007_lotes_na_operacao`: `Movimento.motivo_vencido` e `Movimento.destino` (texto, padrão vazio).
- `vendas 0004_lotes_na_operacao`: `LinhaVenda.lotes_indicados` (padrão falso) e `LinhaVenda.deixados` (JSON, padrão lista vazia).

Só colunas novas com padrão: nenhum dado existente muda; as duas são reversíveis (`migrate estoque 0006` / `migrate vendas 0003`). Não foram aplicadas no banco real (só no banco de teste).

## Decisões tomadas na execução

- Nenhuma mudança em `web/` nem em `agente/`: todos os parâmetros novos são opcionais e as frases de recusa antigas que telas/testes conferem continuam dentro das novas mensagens.
- Um teste existente foi ajustado: `tests/test_etiquetas.py::test_dados_etiqueta_iguais_ao_lote` compara o dicionário inteiro e passou a incluir `dia_producao` e `nome_lote`.
- A venda passou a alocar **todas as linhas antes de gravar** (antes alocava e gravava linha a linha). O resultado é o mesmo; a diferença é que a separação (consulta) e a venda usam o mesmo `Separador`.
- `registrar_venda` com `data_venda` **futura** agora recusa (antes aceitava). Nenhum teste nem tela usava data futura. O mesmo vale para `entregar_encomenda(data_entrega=)`.
- No FEFO com data passada, lote feito depois do dia da venda vai **para o fim** da fila em vez de ser excluído: os testes de custos/margens vendem no passado com lote criado hoje (e lançamentos antigos sem lote não podem travar).
- O gerador `lotes_vencidos` manteve nome, assunto e começo do texto (decisões vigentes no banco real continuam as mesmas; o texto pendente é atualizado na próxima rotina).
- "Consumo da equipe" e "doação" são `Movimento.tipo="perda"` com `destino` próprio — entram nas perdas do relatório, separáveis pelo `destino`.
- `ajustar_contagem` sem diferença não cria movimento (a operação fica na trilha).

## Para a fase 2b (agente) — atenção

- O texto do resumo falado (`agente/`) ainda diz "Vencido não pode ser usado." (`tests/test_mcp_agente_decisoes.py` confere essa frase). Com o Plano 9, o certo é "vencido só sai com motivo". Não mexi por ser do agente.
- As ferramentas de venda/entrega/fritura/perda do agente ainda não passam `lotes`, `motivo_vencido` nem `destino`; continuam funcionando como antes.
- `agente/decisoes.py` e `web/views_decisoes.py` não conhecem a origem nova `lotes_deixados` (caem no rótulo genérico "Lotes deixados").

## Fica para depois

| Item | Quando |
|---|---|
| Telas (Tasks 9–14) | Fase 2a |
| Ferramentas MCP (Tasks 15–18) | Fase 2b |
| Saldo/conservação **na data passada** (hoje usa os de agora) | Se o dono lançar muita venda atrasada |
| Conferência no **último dia** de validade em vez do dia seguinte | Depende de Q1 |
| Inventário geral (contar tudo de uma vez) | Se o dono pedir; `ajustar_contagem` por porção já serve |
| `_linhas_saida` faz uma consulta de lotes por linha e `nome_lote` uma por lote (ordem no dia) | Rever se as vendas tiverem dezenas de linhas |
| `lotes_deixados` lê as linhas com `deixados` de todas as vendas concluídas (filtra em Python) | Rever se houver milhares de vendas com lote indicado |
| Entrega com lote indicado libera a reserva que não foi coberta **inteira** pelo que saiu da porção dela (reserva não se divide) | Só afeta o "reservado" mostrado de encomenda já entregue |
