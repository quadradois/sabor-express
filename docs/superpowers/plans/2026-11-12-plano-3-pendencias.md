# Plano 3 — pendências e decisões da execução (fase 1, núcleo)

Branch `claude/onda2-nucleo-compras-fd0818`. Suíte: 211 testes verdes; `makemigrations --check` sem mudanças.

## Decisões tomadas na execução

- Consumo pendente e conciliação entraram na fase 1 (era pendência do Plano 2 para o Plano 3). `iniciar_producao` e `concluir_producao` só mudam de comportamento quando recebem `pendente_justificativa`; sem ela, recusam como antes. O parâmetro só entra nos `parametros` da trilha quando é usado, para não mudar a comparação de idempotência das chamadas antigas.
- `alocar_fefo` passou a usar `alocar_fefo_parcial` (mesma ordem e mesma mensagem de falta).
- O filtro `dinheiro` foi acrescentado em `web/templatetags/formato.py` (sem tela nova) porque as mensagens do núcleo citam valores em reais.
- Os resultados dos serviços seguem o `executar()`: Decimal e data voltam como texto.

## Fica para depois

| Item | Quando |
|---|---|
| Telas de compras, recebimento, contas e conciliação | Fase 2a |
| Ferramentas MCP e propostas | Fase 2b |
| Precisão do custo por grama (4 casas por unidade base perdem centavos em itens comprados por kg) — avaliar 6 casas em `Lote.custo_unitario` e `LinhaCompra.custo_unitario` | Antes de usar custo para formar preço (junto com REG-01) |
| Mudar parcelas de uma conta já lançada (Q6) | Se o dono pedir |
| Conciliação juntando mais de um lote (Q8) | Se o dono pedir |
| Inventário/ajuste conciliando consumo pendente (DEC-F2-041) | Plano de estoque/inventário |
| Despesas avulsas e recorrentes, categorias | Plano 7 |
| Importação de cupom criando a compra por `registrar_compra` | Plano 5 |
| Pendência de recebimento descontada do "disponível" na consulta de estoque do agente (RN-03 já vale: pendência nunca entra no estoque) | Fase 2b, se o dono quiser ver junto |
