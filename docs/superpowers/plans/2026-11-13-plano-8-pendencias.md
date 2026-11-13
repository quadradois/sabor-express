# Plano 8 — pendências e decisões da execução (fase 1, núcleo)

Branch `claude/plano8-nucleo-despesas-d810c1`. Suíte verde (474 testes, 13 novos em `tests/test_despesas.py`); `makemigrations --check` sem mudanças. Migrações aplicadas sobre uma cópia do banco real sem perda (só tabelas novas e colunas anuláveis; categorias e canais iniciais por `get_or_create`).

## Migrações

- `financeiro 0004_despesas`: `CategoriaDespesa`, `DespesaMensal`, `DespesaDoMes`; `Conta.categoria` e `Conta.competencia` (anuláveis).
- `financeiro 0005_categorias_iniciais`: 8 categorias (mão de obra, energia, gás, diária = indiretas; internet, impostos/MEI, taxas, outras).
- `vendas 0002_canais_de_venda`: `CanalVenda`.
- `vendas 0003_canais_iniciais`: balcão dinheiro 0%, balcão pix 0%, cartão de débito e de crédito **sem taxa** (não informada).

Nenhuma despesa mensal é criada pela migração: o dono cadastra (pela tela da fase 2a ou pelo admin) com ou sem valor previsto.

## Decisões tomadas na execução

- Despesa reaproveita `financeiro.Conta` (`origem="despesa"`); nada de app novo. Mensal sem valor vive só em `DespesaDoMes` (sem conta) porque `Parcela.valor` é obrigatório e todas as somas dependem disso.
- `rodar_rotina` gera as despesas do mês **antes** dos geradores, numa operação própria (`gerar_despesas_do_mes`, canal `sistema`); a falha dela vai para o relatório da rotina como a dos geradores, e o comando `rotina_diaria` imprime "despesas do mês: N geradas".
- `cancelar_despesa` estorna os pagamentos da despesa na mesma operação (um passo só por voz).
- `lancar_despesa` devolve `parecidas` (mensais da mesma categoria em aberto no mês) em vez de recusar: quem decide se é a mesma conta é o dono.
- `salvar_referencias` grava os **dois** campos (óleo e indireto) sempre — a tela manda os dois.
- `devido_por_fornecedor` passou a filtrar `origem="compra"` (despesa não tem fornecedor).
- O texto `relatorio_periodo()["resultado"]["nao_inclui"][0]` manteve o começo "despesas (aluguel, gás, energia, salários)" (a tela no ar e `tests/test_web_custos.py` conferem esse trecho) e trocou o fim falso "o sistema ainda não registra despesas" por "veja o resultado depois das despesas".
- Ressalva nova em `despesas_periodo`: mensais "ainda sem pagamento anotado" (entraram pelo valor previsto ou informado) — é a forma honesta de seguir o espírito do RN-37 sem esconder a conta do lembrete.

## Fica para depois

| Item | Quando |
|---|---|
| Telas (Tasks 8–13) | Fase 2a |
| Ferramentas MCP e `docs/agente-instrucoes-despesas.md` (Tasks 14–16) | Fase 2b |
| Custo pleno por lote (RN-24, CA-34) e ajuste de óleo | Quando houver troca de óleo registrada (desenho no plano) |
| Taxa de cartão automática por venda | Depois que o dono informar as taxas (Q5) |
| Recorrência não mensal; parcelas em despesa avulsa | Se o dono pedir |
| Mensal de meses anteriores ao cadastro | Não será recriada; lançar como avulsa com `competencia` |
| Avisos "despesa acima do normal" / "indireto real acima da referência" | Quando o dono der um limite |
| `margem_apresentacoes` não traz taxa de canal; `estudo_preco` traz | — |
| Desempenho: `despesas_periodo` lê a parcela de cada despesa (poucas por mês); `simular_preco`/`ponto_equilibrio` calculam `margem_apresentacoes` de todas as apresentações para achar uma | Rever se houver centenas de apresentações |
| `ponto_equilibrio` usa as despesas do mês **inteiro** (não rateadas) mesmo no mês em andamento — é o que o mês vai custar | — |
| Admin de `DespesaMensal`: salvar pelo admin não gera o mês corrente na hora (a rotina gera em até 2 horas); pela tela (`salvar_despesa_mensal`) gera | Se incomodar, `depois_de_salvar` no admin pode chamar o gerador |
