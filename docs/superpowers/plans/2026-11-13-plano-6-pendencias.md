# Plano 6 — pendências e decisões da execução (fase 1, núcleo)

Branch `claude/onda4-nucleo-vendas-3963f2`. Suíte verde; `makemigrations --check` sem mudanças.

## Decisões tomadas na execução

- `Reserva` mora em `vendas`; `estoque.servicos` a lê com import tardio (`_reservas`), como `ConsumoPendente` aponta para `producao`. Assim `disponivel()` passou a descontar o reservado sem mudar a assinatura nem quem a usa (`itens_abaixo_do_minimo`, caixa, resumo).
- `alocar_porcoes` é o FEFO por **porção** (lote + conservação, forma do lote) usado por venda, reserva e geradores; o `alocar_fefo` antigo (por item, sem conservação) continua para ingredientes e embalagens.
- `LinhaVenda.baixas` guarda em JSON o que saiu de cada lote (produto e embalagem); é o que a devolução ao estoque usa. Valores como texto (`_json`).
- `registrar_pagamento`/`estornar_pagamento` mantêm as mensagens antigas; o corpo virou `_anotar`/`_estornar`, compartilhado com `registrar_recebimento`/`estornar_recebimento_cliente`.
- O `financeiro` ganhou duas migrações (`0002` cliente/tipo, `0003` venda) porque `vendas` depende de `cadastros 0005`.
- Geradores: "encomendas do dia" ficou só no resumo; a caixa recebe `encomenda_sem_estoque`, `receber_vencidas` e `sobras_fritas`. Cada rodada da rotina grava 3 operações a mais (agora 13 por rodada) — reforça a pendência do Plano 4 sobre `operacoes_hoje` contar a rotina.
- Testes montam lotes de salgado direto no banco (atalho `lote()` em `tests/test_vendas.py`) em vez de passar por uma produção inteira; produção e fritura reais têm seus próprios testes.

## Fica para depois

| Item | Quando |
|---|---|
| Telas (Tasks 9–14) | Fase 2a |
| Ferramentas MCP e `docs/agente-instrucoes-vendas.md` (Tasks 15–18) | Fase 2b |
| Troca de óleo e ajuste de óleo (RF-FRI-04, RN-26, CA-25) — desenho no plano, "Fora deste plano" | Próxima rodada do Plano 6 ou Plano 7 (custos) |
| Devolução parcial de venda; alterar encomenda; entrega parcial (Q3) | Se o dono pedir |
| Descarte de vencido aprovável pela caixa (`lotes_vencidos` propor `registrar_perda`) | Junto com a fase 2b (muda textos de voz já testados) |
| `agente.consultas.estoque` ainda compara o saldo bruto (pendência do Plano 4); agora o reservado também fica de fora dela | Fase 2b |
| Textos da caixa com datas "15/11" (pendência de voz do Plano 4) valem também para os geradores novos | Junto com a correção do Plano 4 |
| Margem por produto e período, relatórios de vendas por tabela (RF-REL-02/03) | Plano 7 |
| `estoque_para_venda` e `necessidade_producao` percorrem as porções em Python (algumas consultas por porção) | Rever se houver centenas de lotes com saldo |
