# Plano 7 — pendências e decisões da execução (fase 2a, telas)

Branch `claude/onda5-telas-custos`. Telas só de leitura em `web/views_custos.py`; nenhum modelo, nenhuma migração, nada alterado em `custos/` nem em `agente/`.

## Telas entregues

| URL | O que mostra |
|---|---|
| `/custos/` | custo estimado de 1 unidade de cada produto (ingredientes, indiretos, óleo, cru, frito); "incompleto: falta comprar X" quando falta compra; ficha inválida em destaque; seletor do item para a evolução de preço |
| `/custos/<produto>/` | blocos e itens (referência, compra e fornecedor de onde veio) e a margem estimada dos preços de tabela do produto |
| `/custos/preparacao/<ficha>/` | custo da preparação por kg e pelo rendimento |
| `/itens/<item>/precos/` | evolução do custo por compra, com variação (links nos itens das telas acima e no previsto × realizado) |
| `/margens/` | margem **estimada** por período e agrupamento (produto, apresentação, cliente, tabela, dia), comparação em pontos com o período anterior, bloco "fora da margem" com os motivos, e a margem estimada da tabela de preço atual (`#tabela`) |
| `/ranking/` | mais vendidos por receita, unidades ou margem, com participação e acumulado |
| `/previsto-realizado/` | lista por período e produto; `/previsto-realizado/<producao>/` o detalhe (link na tela da produção concluída) |
| `/relatorio/` | vendas, encomendas, produção e fritura, perdas, compras, dinheiro, contas em aberto hoje e resultado "estimado — antes das despesas" com `nao_inclui` e ressalvas |

Menu da tela Hoje: um item "Custos e relatórios" (leva a `/custos/`, que tem a barra com as outras telas); `/precos/` ganhou o link "Margem estimada dos preços".

## Decisões

- A margem da tabela de preço ficou como seção de `/margens/` (e por produto em `/custos/<produto>/`), não como colunas de `/precos/`: a tela de preços é de edição e fica curta.
- Período: seletor nomeado (hoje, ontem, semana, semana passada, mês, mês passado, últimos 7/30) ou datas livres (que valem no lugar do período). Período ou data inválidos não quebram: aparece o aviso e vale o padrão (margens e ranking semana/mês). Com datas livres, o período anterior é "os mesmos dias logo antes" (escolha da consulta); com período nomeado, usa `intervalo_anterior`.
- Novos filtros em `web/templatetags/formato.py`: `din` (None vira "—"), `custo4`, `pct`, `pctsinal`, `pontos`, `get_item`.

## Fica para depois

| Item | Observação |
|---|---|
| Editar `indireto_ref_un` e `oleo_ref_un` pela tela | continua no admin; pedir `salvar_referencias` sobre `executar()` à coordenação se o dono quiser |
| CSV (RF-REL-04) e impressão do relatório | só tela |
| Gráficos (evolução de preço, margem por dia) | tabelas apenas |
| Filtro de margem por cliente/produto específico na tela | a consulta aceita (`cliente_id`, `produto_id`); a tela só agrupa |
| Lista das vendas que ficaram "fora da margem" (hoje só a contagem, o valor e o motivo) | a consulta devolve `linha_ids`; falta tela de detalhe |
| `/custos/` calcula a ficha de todos os produtos a cada abertura, e `/margens/` chama `margem_apresentacoes()` inteira | rever junto do desempenho de `previsto_realizado` (pendência da fase 1) |
| Ferramentas MCP e instruções do agente (Tasks 12–14) | fase 2b, em `agente/` |
| Pendências da fase 1 (despesas, custo pleno, óleo, geradores de margem baixa e de ingrediente que subiu) | continuam em `2026-11-13-plano-7-pendencias.md` |
| Teste em navegador real a 360 px | as telas usam o CSS existente (tabelas rolam dentro do bloco); não conferido em aparelho |
