# Plano 8 — pendências e decisões da execução (fase 2a, telas)

Branch `claude/plano8-telas-despesas`. Só `web/`, `tests/` e `docs/` mudaram; nenhum modelo, migração, serviço ou consulta foi alterado. Toda gravação passa pelos serviços da fase 1 (`financeiro.despesas`, `financeiro.servicos.registrar_pagamento`, `cadastros.servicos.salvar_referencias`, `vendas.servicos.salvar_canal_venda`).

## O que foi entregue

| URL | Tela |
|---|---|
| `/despesas/?mes=AAAA-MM` | O mês: resumo (total, pago, falta pagar, sem valor, vencidas), total por categoria, "falta pagar" primeiro (para percorrer e pagar uma a uma), pagas e canceladas; informar valor, pagar (valor real + data + forma) e cancelar com motivo |
| `/despesas/nova/` | Lançar avulsa (já paga ou a pagar com vencimento) |
| `/despesas/mensais/`, `/despesas/mensais/nova/`, `/despesas/mensais/<id>/` | Cadastro das mensais (valor previsto opcional) |
| `/despesas/categorias/` | Categorias (nome, indireta, ativa) |
| `/canais/` | Canais de venda e taxa (em branco = "não informada") |
| `/custos/referencias/` | Óleo e indiretos por unidade de cada tamanho (`salvar_referencias`) |
| `/estudo-de-preco/` | CMV, indiretos, taxa e sobra por apresentação, canal e tabela; simulador nos dois sentidos; ponto de equilíbrio; conferência `indireto_real` |
| `/relatorio/`, `/margens/`, tabela de preços | Bloco "depois das despesas" com o que falta; margem "com indiretos" ao lado da atual |
| Hoje | Despesas do mês sem valor e link para `/despesas/` em "O que pagar"; o menu não ganhou item (os links ficam em "Custos e relatórios") |

Endpoints só POST: `/despesas/valor/`, `/despesas/pagar/`, `/despesas/cancelar/`.

## Decisões

- A lista do mês usa `despesas_do_mes` (situações e totais) e `despesas_periodo` (total por categoria); a tela não calcula nenhum número.
- Pagar mensal manda o valor digitado a `pagar_despesa_do_mes`; mensal já com pagamento parcial paga só o saldo (sem campo de valor, porque o serviço recusa mudar o valor com pagamento anotado). Avulsa paga pelo `registrar_pagamento` (valor em branco = saldo).
- `cancelar_despesa` exige `conta_id`; mensal "sem valor" ainda não tem conta. Na tela, para dizer "não teve internet neste mês", informa-se um valor e cancela-se em seguida (a tela explica isso na própria despesa).
- Categoria e canal: não há "excluir"; desativa-se (campo ativa/ativo).
- Estudo de preço: o canal escolhido define a coluna mostrada; taxa não informada mostra o aviso e "—", nunca zero. O simulador e o ponto de equilíbrio são pedidos por GET (não gravam) e usam o canal e a tabela escolhidos no topo.
- Texto das telas diz "estimado"/"simulação" onde o contrato manda; o resultado depois das despesas repete "Não é lucro".

## Fica para depois

| Item | Observação |
|---|---|
| Cancelar mensal sem valor numa só ação | Depende de um serviço (`cancelar_despesa` por `despesa_do_mes_id`); hoje: informar valor e cancelar |
| Estornar pagamento de despesa pela tela das despesas | Existe em `/contas/` (pagamentos dos últimos 30 dias); a tela do mês só cancela (que estorna junto) |
| Data do pagamento de cada despesa paga na lista do mês | `despesas_do_mes` não devolve a data do pagamento |
| Editar despesa avulsa (valor/descrição) | Sem serviço: cancelar e lançar de novo |
| Ferramentas MCP e instruções do agente (fase 2b) | Em `agente/`, trabalho paralelo |
| Seletor de mês no relatório para "mês fechado" | O relatório já aceita datas livres e períodos prontos |
| Gráficos | Não pedidos |
