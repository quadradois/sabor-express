# Plano 6 — pendências e decisões da execução (fase 2a, telas)

Branch `claude/onda4-telas`. Suíte verde (389 testes, 41 novos em `tests/test_web_vendas.py`); `makemigrations --check` sem mudanças. Só `web/`, `tests/` e `docs/`, mais **um** ajuste mínimo numa consulta (abaixo).

## Telas entregues (Tasks 9 a 14)

| Tela | URL | Núcleo usado |
|---|---|---|
| Vender (balcão/atacado) | `/vender/` | `apresentacoes`, `clientes`, `registrar_venda`, `dividir_parcelas` |
| Vendas do dia e cancelar venda | `/vendas/`, `/vendas/<id>/cancelar/` | `vendas`, `cancelar_venda` |
| Encomendas: lista, nova, detalhe | `/encomendas/`, `/encomendas/nova/`, `/encomendas/<id>/` | `encomendas`, `encomendas_do_dia`, `detalhe_encomenda`, `criar_encomenda`, `completar_reserva`, `entregar_encomenda`, `cancelar_encomenda` |
| Necessidade de produção | `/necessidade/` | `necessidade_producao` (o botão leva a `/producao/nova/?produto=&unidades=&forma=`; nenhuma produção é criada sem o clique) |
| Fritura | `/fritura/` | `estoque_para_venda` (lista de salgados crus), `lotes_para_fritar`, `frituras`, `registrar_fritura` |
| Sobras e perda | `/sobras/` | `sobras_fritas`, `registrar_perda` |
| Descartar vencido | `POST /lotes/<id>/descartar/` (botão na tela do lote e no bloco de vencidos do Hoje) | `registrar_perda` |
| Clientes | `/clientes/`, `/clientes/novo/`, `/clientes/<id>/` | `clientes`, `salvar_cliente`, `devido_por_cliente` |
| Preços | `/precos/`, `/precos/novo/`, `/precos/<id>/` | `apresentacoes(ativas=False)`, `salvar_apresentacao` |
| Contas a receber | `/receber/` (`?cliente=<id>`), `POST /receber/anotar/`, `POST /receber/estornar/` | `receber_vencidas`, `receber_a_vencer`, `receber_em_aberto`, `devido_por_cliente`, `recebimentos`, `registrar_recebimento`, `estornar_recebimento_cliente` |
| Hoje (blocos novos) e caixa | `/`, `/decisoes/` | `resumo_do_dia`; origens `encomenda_sem_estoque`, `receber_vencidas` e `sobras_fritas` com rótulo e link |

## Ajuste fora de `web/`

- `vendas.consultas.total_dos_itens(itens, tabela)`: devolve o total que `registrar_venda`/`criar_encomenda` gravariam, lendo os preços pelo mesmo `_ler_itens` do serviço (sem regra nova, sem gravar, sem checar estoque). Existe porque a venda **a prazo** precisa das parcelas somando o total e a tela não pode fazer a conta (`dividir_parcelas(total, ...)`). Testado em `test_total_dos_itens_usa_a_regra_do_servico`.

## Decisões da execução

- Venda e encomenda usam a mesma grade de itens (`_grade_itens.html`): quantidade com −/+ (um script curto; sem ele o campo continua funcionando), preços de varejo e atacado visíveis, preço combinado opcional por linha (desconto manual). Quantidade só inteira.
- Erro de regra: formulários grandes (vender, nova encomenda, fritura, preços, clientes) voltam com o que foi digitado; as ações do detalhe da encomenda também. Cancelar venda, perda, descarte e recebimento são formulários pequenos que voltam à lista com a mensagem (padrão de contas a pagar).
- Cada render de formulário gera chave nova (`{% chave %}`); reenviar o mesmo POST não duplica (testado em venda, fritura, entrega e recebimento).
- "Entregar" só aparece com a encomenda **pronta** (derivada pela consulta); aberta mostra "Completar reserva" e o que falta. O serviço continua sendo quem recusa.
- Cancelar encomenda: "devolver o sinal" vem marcado (Q5).
- Filtro de encomendas: situação (em aberto, falta separar, prontas, entregues, canceladas, todas) e dia da entrega de/até, mais "Só hoje".
- Fritura: o salgado vem da lista de crus com estoque livre; o primeiro lote (vence primeiro) já vem marcado; a validade manual fica escondida, só serve quando o salgado não tem critério de "frito".
- Contas a receber filtradas por cliente (`?cliente=`) mostram tudo o que ele deve e os recebimentos de 90 dias.
- Novo filtro `numero` em `web/templatetags/formato.py` (vírgula, sem milhar, sem zeros à toa) para preencher campos; `conservacao` e `forma_nome` para os rótulos.

## Fica de fora ou duvidoso

| Item | Detalhe |
|---|---|
| Descarte pela caixa | O descarte de vencido é botão na tela do lote e no Hoje; `lotes_vencidos` continua só avisando (decisão do plano: fica com a fase 2b). |
| Venda a prazo: parcelas iguais | A tela só oferece número de parcelas, primeiro vencimento e intervalo (parcelas iguais, centavos na última). Parcelas de valores diferentes só pelo agente/serviço. |
| Sem prévia do total | `/vender/` não mostra o total antes de gravar (ele aparece na mensagem depois). Mostrar ao vivo exigiria conta no navegador ou um endpoint novo sobre `total_dos_itens`; deixei de fora para não criar regra na tela. |
| Estoque na grade | A grade mostra "Dá para vender N" (`livre_apresentacoes`) mas não trava o campo; quem recusa é o serviço, com a mensagem do núcleo. |
| Alterar encomenda, entrega parcial, devolução parcial, escolha de lote na venda | Continuam fora (plano, "Fora deste plano"). Na tela: cancelar e criar outra encomenda. |
| Troca e ajuste de óleo | Fora do plano; a fritura não mostra o ajuste. |
| Cancelamento de venda | Só total (núcleo). "Valor já pago, anotado como devolvido" é anotação: o sistema não movimenta dinheiro. |
| Lista de vendas | Sem paginação (por dia costuma ser curta); em período longo fica pesada: paginar como o histórico. |
| Desempenho | `apresentacoes()` e `estoque_para_venda()` percorrem as porções em Python a cada abertura de `/vender/`, `/encomendas/nova/` e `/fritura/` (pendência já registrada na fase 1). |
| Teste em aparelho | `/vender/` foi conferida a 360 px num navegador local (sem rolagem horizontal); as demais usam as mesmas classes mas não foram vistas uma a uma. Falta o dono usar no celular. |
| Menu | Os links novos entraram no menu da tela Hoje (padrão atual: o cabeçalho só leva ao Hoje). Com tantos itens, vale agrupar (venda, estoque, dinheiro, cadastros) numa rodada de design. |
