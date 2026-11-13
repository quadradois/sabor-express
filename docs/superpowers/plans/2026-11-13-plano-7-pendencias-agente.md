# Plano 7 — pendências e decisões da fase 2b (ferramentas do agente de voz)

Branch `claude/onda5-agente-custos`. Sete ferramentas novas de leitura (nível 0) em `agente/custos.py`,
registradas em `agente/ferramentas.py` (77 no total); 20 testes em `tests/test_mcp_agente_custos.py`;
`docs/agente-mcp.md` e `docs/agente-instrucoes-custos.md` (trecho do prompt e roteiro de teste por voz).
Nada mudou em `custos/`, `web/` nem em modelos.

## Decisões tomadas na execução

- **Task 13 (`ver_vendas` com margem): não.** A margem fica só em `ver_margem` (e em `ver_mais_vendidos`,
  `ver_margem_tabela`, `ver_relatorio`), sempre com "estimada". `ver_vendas` continua só com dinheiro: o dono
  pergunta "quanto vendi" e ouve o total; quem quer margem pergunta pela margem. Revisável se o dono pedir as
  duas coisas na mesma frase.
- **Texto falado sem a palavra "lucro"**, nem para negar: o relatório diz "o resultado não desconta despesas,
  ..." em vez de "não é lucro" (o modelo tende a repetir a palavra que ouve). Os testes conferem.
- **Porcentagem e pontos por extenso** ("75 por cento", "caiu 6 pontos"), sem "%"; posição no ranking como
  "primeiro, segundo, terceiro" (o "1º" vira "1 grau" em alguns sintetizadores).
- **Custo por unidade arredondado ao centavo na fala** (os dados trazem 4 casas); abaixo de meio centavo a fala
  diz "menos de 1 centavo", nunca "zero real".
- **Custo incompleto não fala o parcial** (`ingredientes_conhecido` só nos dados): "Sem esse preço não dá para
  dizer o custo." Falar o parcial seria convidar o modelo a chamá-lo de custo.
- **`ver_custo` aceita preparação** (massa, recheio): primeiro procura um produto (tamanho) com o nome; sem
  produto, uma preparação ativa (`custo_preparacao` do rendimento, com o preço por quilo).
- **`ver_margem_tabela(produto)` filtra pelo nome do produto em todas as apresentações** ("coxinha" traz todos os
  tamanhos), em vez de exigir um tamanho só.
- **Períodos:** só os de `custos.consultas.intervalo` (com as formas faladas "esta semana", "mês passado",
  "últimos 30 dias"); data solta ("AAAA-MM-DD") não, ao contrário de `ver_vendas`. A comparação usa
  `intervalo_anterior` (o mesmo trecho), padrão do Plano 7 (Q3).
- **`ver_resumo_do_dia`** passou a usar `resumo_do_dia()["totais"]["operacoes_hoje"]`, que desde a fase 1 já vem
  sem a rotina; antes o agente refazia a mesma conta com `historico_operacoes`. A fala não muda.
- `docs/agente-instrucoes-vendas.md`: a frase "Não opine sobre margem, lucro ou se o preço está bom." foi trocada
  pela frase nova (a mesma indicada em `agente-instrucoes-custos.md`). O prompt do Chef é aplicado pela
  coordenação.

## Fica para depois

| Item | Quando |
|---|---|
| Aplicar o trecho "Custos, margens e relatórios" e a troca da frase no prompt do Monsieur EscofIA; teste por voz (roteiro em `docs/agente-instrucoes-custos.md`) | Coordenação |
| Período por datas ("de 1 a 15 de outubro", "outubro") nas ferramentas de custos | Se o dono pedir; hoje só os períodos de `intervalo` |
| Margem de **um** cliente ou produto ("qual a margem do João?"): `margens` aceita `cliente_id`/`produto_id`, mas `comparar_margens` não; hoje o agente agrupa por cliente/produto e fala os três maiores | Pedir à coordenação `cliente_id`/`produto_id` em `comparar_margens` (núcleo) |
| Custo de um tamanho em data passada (`custo_estimado(em=)`) por voz | Se o dono pedir "quanto custava em setembro" |
| `ver_evolucao_preco` sem filtro de período (fala a última × a anterior e a primeira × a última; os dados trazem as 20 últimas compras) | Se as listas ficarem longas |
| `ver_relatorio` fala só o essencial (vendas, margem, perdas, resultado, produção, compras, dinheiro, contas, ressalvas); encomendas, perdas por motivo, frituras e por produto ficam nos dados | Se o dono quiser ouvir mais |
| Precisão do custo por grama (4 casas por unidade base, pendência do Plano 3) — o custo estimado falado herda | Antes de usar o custo para formar preço |
| Desempenho: `ver_relatorio` chama `relatorio_periodo` inteiro (com `previsto_realizado` sem limite); `ver_margem` com comparação lê as linhas de venda dos dois períodos | Rever com centenas de vendas/produções por período |
| Gerador "margem abaixo do mínimo" e "ingrediente subiu" na caixa (Q4, Q5) | Quando o dono der os limites |
