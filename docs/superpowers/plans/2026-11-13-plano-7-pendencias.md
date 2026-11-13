# Plano 7 — pendências e decisões da execução (fase 1, núcleo)

Branch `claude/onda5-nucleo-custos-fafc5b`. Suíte verde (426 testes, 19 novos em `tests/test_custos.py`); `makemigrations --check` sem mudanças.

## Decisões tomadas na execução

- App novo `custos` sem modelos (só consultas). O único dado novo é `Item.indireto_ref_un` (migração `cadastros 0006`), editável no admin de itens.
- `compras.consultas.ultimo_custo` ganhou `ate=`; quem já usava não muda.
- O custo real por item da produção é lido dos movimentos da operação `concluir_producao` (achada pela trilha, `parametros.producao_id`) mais os consumos pendentes conciliados; o total oficial continua `Producao.custo_total`.
- "Custo duvidoso" numa linha de venda: custo zero, ou lote (ou o lote cru de onde a fritura veio) de produção com consumo pendente aberto ou conciliado depois da venda. Vai para `fora`, não para a margem.
- `resumo_do_dia`: `operacoes_hoje` sem o canal `sistema`; a rotina em `operacoes_rotina_hoje` (o teste antigo `>= 3` continua valendo). O agente já contava sem a rotina por conta própria — pode passar a usar o total.

## Fica para depois

| Item | Quando |
|---|---|
| Telas (Tasks 7–11) | Fase 2a |
| Ferramentas MCP e `docs/agente-instrucoes-custos.md` (Tasks 12–14) | Fase 2b |
| Despesas avulsas/recorrentes com categorias (RF-FIN-02/05, RF-CUS-03/07) — desenho em "Fora deste plano" | Próxima rodada (pendência do Plano 3) |
| Rateio de indiretos e custo pleno (RF-CUS-04, RN-24, RF-REL-03, CA-34) | Depois das despesas |
| Troca e ajuste de óleo (RF-FRI-04, RN-26, CA-25) | Junto com o custo pleno |
| CSV (RF-REL-04) | Fase de telas |
| Geradores "margem abaixo do mínimo" e "ingrediente subiu" | Quando o dono der os limites (Q4, Q5) |
| Precisão do custo por grama: `LinhaCompra.custo_unitario` e `Lote.custo_unitario` têm 4 casas por unidade base (R$ 0,00449/g vira 0,0045) — o custo estimado herda o arredondamento | Antes de usar o custo para formar preço (pendência do Plano 3) |
| Previsto da produção usa a taxa de óleo apropriada; se o `oleo_ref_un` mudou depois, o previsto não muda (o gravado manda) | — |
| Posição das contas só "hoje" (sem saldo histórico por data) | Se o dono pedir "quanto eu devia no fim do mês" |
| Desempenho: `previsto_realizado` lê produção por produção (algumas consultas cada) e `margens` percorre as linhas em Python; `margem_apresentacoes` calcula a ficha uma vez por produto | Rever com centenas de produções/linhas por período |
| `relatorio_periodo` chama `previsto_realizado` sem limite de produto e `vendas()` inteiro do período | Idem |
