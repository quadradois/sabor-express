# Plano 7 — Custos, margens e relatórios — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O dono pergunta "quanto me custa uma coxinha?" e o sistema responde pela ficha, em cascata até o último ingrediente, com o preço da última compra de cada um — e diz o que falta quando um ingrediente nunca foi comprado. Depois de cada produção, mostra o previsto × o realizado (rendimento, quanto de cada ingrediente, custo). Das vendas, sai a margem **estimada** por produto, apresentação, cliente, tabela e dia, com o desconto à vista, e a comparação com o período anterior ("sua margem caiu 6 pontos"). O relatório do período junta vendas, produção, perdas com valor, compras, o dinheiro anotado, as contas em aberto e um resultado simples — cada número com a definição escrita aqui, sem contabilidade e sem inventar o que o sistema não registra.

**Architecture:** App novo `custos` **só de consultas** (sem modelos): `custos/fichas.py` (custo estimado da ficha), `custos/consultas.py` (períodos, previsto × realizado, margens, comparação, margem das apresentações, ranking, evolução de preço) e `custos/relatorios.py` (relatório do período). Um campo novo em `cadastros.Item`: `indireto_ref_un` (RF-CUS-05), editado pelo admin (que já grava por `executar()`). `compras.consultas.ultimo_custo` ganha `ate=` (a referência de um dia passado). `decisoes.consultas.resumo_do_dia` deixa de contar a rotina em `operacoes_hoje`. Nada grava fora do que já existia.

**Tech Stack:** Python 3.12, uv, Django 5.2, SQLite, pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-10-19-agente-cozinha-design.md` (§4 A3: "a IA não calcula custos" — o núcleo calcula, o agente repete; §6.3.4 aprendizado por estatística; §6.6.5 consultas de custos e relatórios). Regras em `docs/prd/02-prd.md`: RF-FIC-02/05, RF-OP-06/09, RF-CUS-01 a 07, RF-REL-02/03/04, RF-FIN-10, RN-20 a 26, RN-30, RN-33, §16 (indicadores e critérios de cálculo), CA-14, CA-15, CA-32 a 34. Pendências herdadas: `2026-11-12-plano-3-pendencias.md` (despesas avulsas e categorias → Plano 7; precisão do custo por grama), `2026-11-12-plano-4-pendencias-agente.md` (`operacoes_hoje` conta a rotina), `2026-11-13-plano-6-pendencias.md` (margem por produto e período; troca e ajuste de óleo), `2026-11-13-plano-6-pendencias-agente.md` (`ver_vendas` sem margem até haver dados).

## O que muda em relação ao PRD (realidade do produto)

- **Ficha do produto por proporção** (design §6.3): o custo estimado é **por unidade de um tamanho** (`Item` produto com `peso_g`), não "por unidade de rendimento" da ficha. A conta é a mesma da escala: `peso_g × percentual` de cada preparação, em cascata.
- **Preparações não viram estoque** (design §6.3.5): RF-FIC-06 ("preparação teórica no estimado, consumida do estoque da preparação na produção") vale só no estimado; na produção, os ingredientes saem direto.
- **Margem por produto** vem das vendas (o custo já está gravado na linha, RN-30), e a "margem estimada" da tabela de preço vem da ficha × preço atual. As duas são **estimadas** e dizem o que não incluem (RF-CUS-06).

## Divisão do plano

| Fase | Quem | Entrega | Situação |
|---|---|---|---|
| **1 — Núcleo** | esta sessão | consultas de custo, previsto × realizado, margens, comparação, relatório; campo de indireto; `operacoes_hoje` sem a rotina; testes | **feita** (Tasks 1–6) |
| **2a — Telas** | sessão paralela, só `web/` | Custos (tabela de custo por produto e por preparação), Margens (com comparação), Previsto × realizado, Relatório do período, Evolução de preço (Tasks 7–11) | a fazer |
| **2b — Ferramentas MCP** | sessão paralela, só `agente/` e `docs/` do agente | ferramentas de leitura (nível 0) e instruções do agente de voz sobre custo e margem (Tasks 12–14) | a fazer |

As fases 2a e 2b não mexem em modelo, serviço nem consulta; se precisarem de algo do núcleo, pedem à coordenação. O contrato estável está no fim deste documento.

## Decisões deste plano (revisáveis pelo dono)

| Decisão | Por quê / custo se estiver errada |
|---|---|
| **Referência de custo = última compra aprovada, não cancelada** (RN-23). Entrada manual de estoque **não** é referência; item nunca comprado deixa o custo **incompleto** (`None` + `faltando`), nunca zero. | RN-23 e CA-14 dizem exatamente isso. Custo: no começo, com estoque lançado só por entrada manual, muitas fichas aparecem "incompletas" até a primeira compra de cada ingrediente (pergunta Q1). |
| **Óleo e indiretos de referência à parte** (RF-CUS-05): `ingredientes`, `indiretos`, `oleo`, `custo_cru` (= ingredientes + indiretos) e `custo_frito` (= custo_cru + óleo). Indireto é **por produto** (`Item.indireto_ref_un`, como o óleo); vazio = "não inclui indiretos". | O PRD pede "valores de referência configuráveis por unidade para indiretos e óleo"; o óleo já é por produto. Custo: um campo a mais no cadastro de cada tamanho (pergunta Q2). |
| **Previsto da produção = quantidades previstas da ficha × referência que valia no dia da produção** (`ultimo_custo(ate=dia)`), mais o óleo na mesma taxa apropriada. O realizado é o custo gravado (RN-25). | Fica estável no tempo (uma compra nova não muda o previsto de uma produção antiga) e separa "usei mais" de "paguei mais caro". Custo: se o lote consumido era de uma compra antiga e mais barata, o desvio aparece "a favor" mesmo usando a quantidade certa — é verdade: o custo real foi menor. |
| **Rendimento = boas ÷ planejadas** (PRD §16), em pontos percentuais. | É a definição do PRD; a sugestão de ficha (Plano 4) usa a mesma. |
| **Produção com custo pendente ou sem referência fica fora da comparação de custo** (lista em `fora`), mas conta nas unidades. | Comparar custo parcial com previsto inteiro daria um desvio falso. |
| **Margem das vendas = receita (preço praticado) − custo gravado na linha** (salgado + embalagem). Linhas com custo **duvidoso** — custo zero, ou lote de produção com consumo pendente aberto, ou conciliado **depois** da venda — ficam **fora da margem** e dentro da receita, com o motivo. | RN-30 congela o custo na venda; uma venda feita antes de conciliar gravou um custo menor que o real. Tratar como margem boa seria inventar lucro. Custo: a margem cobre só parte das vendas até a conciliação, e o retorno diz quanto ficou de fora. |
| **Desconto = preço de tabela − preço praticado**, por linha (RF-VEN-01). | O preço original já fica gravado na linha. |
| **Comparação de períodos em pontos percentuais** (`pontos` = margem% atual − anterior). Período anterior padrão: os mesmos tantos dias logo antes; `intervalo_anterior` compara "o mesmo trecho" (semana até sexta × semana passada até sexta; dia 1–13 × dia 1–13 do mês passado). | "Caiu 6 pontos" é o que o dono quer ouvir; comparar uma semana pela metade com uma inteira enganaria na receita. |
| **Margem estimada da apresentação = preço de tabela − (unidades × custo da ficha por unidade + embalagens × última compra da embalagem)**, sem indiretos. | É o custo direto, comparável com a margem das vendas (o custo do lote também não tem indiretos). |
| **Resultado do período = receita das vendas concluídas − custo gravado nelas − perdas com valor.** Perdas com valor = movimentos "perda" (saldo × custo do lote) + vendas canceladas com destino perda (custo gravado na venda). Perdas dentro da produção/fritura só em unidades (o custo já está no custo por unidade do lote). | Sem despesas (o sistema ainda não registra, ver "Fora deste plano") não há lucro; o rótulo é "estimado" e `nao_inclui` diz o que falta. |
| **Dinheiro do período é anotação**: entrou = vendas à vista (`recebido_na_hora`, mesmo das canceladas depois) + sinais de encomenda + recebimentos de clientes; saiu = pagamentos (inclui compras à vista) + valores devolvidos em cancelamentos. | O sistema nunca movimenta dinheiro (design §3); é o que foi anotado. |
| **Posição das contas é a de hoje** (o que está em aberto agora), não "no fim do período". | As parcelas não guardam histórico de saldo por data; recalcular o passado seria inventar. |
| **Sem gerador novo na caixa de decisões.** "Margem abaixo do mínimo" e "ingrediente que subiu muito" não têm limite definido no PRD. | Perguntas Q4 e Q5; o desenho está em "Fora deste plano". |
| **`operacoes_hoje` sem a rotina**: conta as operações de hoje fora do canal `sistema`; a rotina vai para `operacoes_rotina_hoje`. | Pendência dos Planos 4 e 6 (a rotina gravava 13 operações por rodada). A tela Hoje e o agente leem o mesmo número; o teste antigo (`>= 3`) continua valendo. |

## Definições (cada número)

| Número | Definição |
|---|---|
| Referência de um item | `LinhaCompra.custo_unitario` (RN-20) da última compra não cancelada do item até o dia `em` (data da compra, depois id). |
| Custo estimado — ingredientes por unidade | Σ (quantidade do item na cascata para 1 unidade × referência). Cascata: produto `peso_g × percentual ÷ 100` g de cada preparação; preparação: itens × (g ÷ rendimento_g) e sub-preparações × (g ÷ rendimento_g). |
| `custo_cru` / `custo_frito` | ingredientes + indireto de referência (se cadastrado) / custo_cru + óleo de referência. |
| Custo da preparação (`por_kg`) | Σ itens da cascata para `gramas` ÷ gramas × 1000. |
| Custo previsto da produção | Σ (previsto por item × referência no dia do encerramento) + taxa de óleo apropriada × unidades planejadas (frito). |
| Custo real da produção | `Producao.custo_total` (RF-OP-06; com o consumo pendente conciliado somado, RN-25 a). Por item: consumos da operação de conclusão × custo do lote + consumos pendentes conciliados. |
| Óleo real (frito) | custo real − consumos. Taxa de óleo = óleo real ÷ (boas + perdas). |
| Rendimento | boas ÷ planejadas × 100. |
| Desvio | real − previsto; `desvio_*_pct` = (real − previsto) ÷ previsto × 100. Uso do ingrediente: (usado − previsto) ÷ previsto × 100. |
| Custo unitário previsto / real | previsto ÷ planejadas / `Producao.custo_unitario` (real ÷ boas). Por produto: Σ ÷ Σ das produções comparadas. |
| Receita | Σ `LinhaVenda.total` das vendas **concluídas** (canceladas fora), pela data da venda. |
| Receita de tabela / desconto | Σ preço de tabela × quantidade / receita de tabela − receita. |
| Custo da venda | `LinhaVenda.custo` (lotes baixados: salgado + embalagem, RN-30). `custo_salgado` e `custo_embalagem` separam pelo item de cada baixa. |
| Margem | receita_com_custo − custo, só das linhas sem custo duvidoso. `margem_pct` = margem ÷ receita_com_custo × 100. |
| Pontos | margem_pct atual − margem_pct anterior. |
| Participação / acumulado | valor do produto ÷ total do critério (`receita`, `unidades` ou `margem`) × 100; acumulado na ordem. |
| Variação de preço | (custo da compra − custo da compra anterior) ÷ anterior × 100; do período: último ÷ primeiro. |
| Perdas com valor | movimento "perda": quantidade × custo do lote; venda cancelada com destino perda: custo gravado na venda (data do cancelamento). |
| Resultado | receita − custo gravado das vendas concluídas (todas as linhas) − perdas com valor. `resultado_pct` = resultado ÷ receita × 100. |
| Dinheiro: entrou / saiu | vendas à vista (data da venda) + sinais (dia em que a encomenda foi criada) + recebimentos (valor pago, não estornados) / pagamentos (valor pago, não estornados) + devolvido nas vendas e encomendas canceladas (data do cancelamento). |
| Posição | Σ saldo das parcelas em aberto (a pagar, a receber) e das vencidas, hoje. |

Arredondamento: Decimal com `ROUND_HALF_UP`; dinheiro 2 casas; custo por unidade 4; quantidade 3; percentuais 1 casa. Somas feitas com os valores exatos e arredondadas no fim (uma linha da cascata arredondada pode diferir do total em 0,0001).

## Global Constraints

- Tudo dos Planos 1 a 6 continua valendo: Decimal sempre; toda gravação por `executar()`; nada é apagado (RN-34).
- Consultas não gravam, não repetem regra e devolvem Decimal/date. Onde falta dado, dizem o que ficou de fora (`completo`, `faltando`, `fora`, `ressalvas`) em vez de contar zero.
- Toda margem e todo resultado levam o rótulo "estimada"/"estimado" e a lista do que não incluem (RF-CUS-06, CA-33).
- O agente nunca calcula custo, margem ou preço (design A3): repete o retorno das consultas.

## Review Focus

- Cascata e CA-14 (`test_ca14_parcela_de_massa_por_coxinha`, `test_custo_em_cascata_pelas_subpreparacoes`).
- Dado faltante sinalizado, nunca zero (`test_item_nunca_comprado_deixa_o_custo_incompleto`, `test_producao_sem_compra_do_ingrediente_nao_tem_previsto`, `test_venda_com_custo_zero_fica_fora_da_margem_e_dentro_da_receita`).
- Previsto × realizado com desvio de quantidade e de preço (`test_previsto_realizado_por_producao`, `test_previsto_realizado_frito_conta_o_oleo`, `test_custo_pendente_e_sem_referencia_ficam_fora_da_comparacao`).
- Margem com desconto, por tabela e cliente; cancelada fora (`test_margem_por_produto_tabela_e_cliente_com_desconto`).
- "Caiu 6 pontos" (`test_comparacao_de_periodos_em_pontos`).
- Venda feita antes da conciliação (`test_venda_de_lote_com_custo_pendente_fica_fora_ate_a_conciliacao`).
- Relatório: perdas valorizadas, dinheiro anotado e resultado (`test_relatorio_do_periodo`).

---

## Fase 1 — Núcleo (feita)

### Task 1: Indireto de referência e referência por data
**Files:** `cadastros/models.py`, `cadastros/admin.py`, `cadastros/migrations/0006_indireto_ref_un.py`, `compras/consultas.py`.
- [x] `Item.indireto_ref_un` (R$ por unidade, opcional); coluna no admin de itens (que grava por `executar()`).
- [x] `ultimo_custo(item_id, *, ate=None)`.

### Task 2: Custo estimado da ficha
**Files:** `custos/fichas.py`, `custos/apps.py`, `sabor/settings.py`.
- [x] `custo_estimado`, `custos_estimados`, `custo_preparacao`.

### Task 3: Previsto × realizado
**Files:** `custos/consultas.py`.
- [x] `previsto_realizado_producao`, `previsto_realizado`.

### Task 4: Margens, comparação, apresentações, ranking, evolução de preço, períodos
**Files:** `custos/consultas.py`.
- [x] `intervalo`, `intervalo_anterior`, `margens`, `margem_das_linhas`, `comparar_margens`, `margem_apresentacoes`, `ranking_produtos`, `evolucao_preco`.

### Task 5: Relatório do período e resumo do dia
**Files:** `custos/relatorios.py`, `decisoes/consultas.py`.
- [x] `relatorio_periodo`; `resumo_do_dia()["totais"]["operacoes_hoje"]` sem a rotina e `operacoes_rotina_hoje`.

### Task 6: Testes e fechamento
**Files:** `tests/test_custos.py`.
- [x] 19 testes; `uv run pytest` verde (426); `makemigrations --check` sem mudanças.

---

## Fase 2a — Telas (`web/`)

Padrão das telas existentes: login obrigatório, sem rolagem horizontal a 360 px, a tela nunca calcula (todos os números vêm das consultas). **Toda margem mostra "estimada" e a lista `nao_inclui`/`inclui`** (CA-33). Valor `None` aparece como "—" com o motivo (`faltando`, `fora_motivo`), nunca como "R$ 0,00".

### Task 7: Custos dos produtos e das preparações
- [ ] `/custos/`: `custos_estimados()` — por produto: ingredientes, indiretos, óleo, custo cru, custo frito; "incompleto: falta comprar X" quando `completo=False`; `erro` da ficha em destaque.
- [ ] `/custos/<produto_id>/`: `custo_estimado` com os blocos (preparação, gramas, itens com referência, compra e fornecedor) e `margem_apresentacoes(produto_id=)`.
- [ ] `/custos/preparacao/<ficha_id>/`: `custo_preparacao` (por kg e por rendimento).

### Task 8: Margens
- [ ] `/margens/?periodo=semana&agrupar=produto`: `intervalo` + `comparar_margens(de, ate, de_anterior, ate_anterior, agrupar)` com `intervalo_anterior`; filtros período (hoje, semana, mês, mês passado, de/até) e agrupamento (produto, apresentação, cliente, tabela, dia). Mostra receita, desconto, custo, margem, margem %, pontos e o bloco "fora da margem" (`fora`).
- [ ] Tabela de preço com margem estimada: `margem_apresentacoes()` (na tela Preços existente ou em `/margens/tabela/`).
- [ ] Ranking: `ranking_produtos(ordem=)`.

### Task 9: Previsto × realizado
- [ ] `/producao/previsto-realizado/`: `previsto_realizado(de, ate, produto_id)` — por produto e lista; `fora` explicado.
- [ ] Na tela da produção concluída: `previsto_realizado_producao(id)` (itens: previsto, usado, desvio, custo previsto e real).

### Task 10: Relatório do período
- [ ] `/relatorio/?periodo=mes`: `relatorio_periodo(de, ate)` em blocos (vendas, encomendas, produção, perdas, compras, dinheiro, posição, resultado, ressalvas), cada um com a definição curta (tirar da tabela "Definições").

### Task 11: Evolução de preço
- [ ] `/itens/<id>/precos/`: `evolucao_preco(item_id, de, ate)`; link a partir do custo da ficha (cada item).

---

## Fase 2b — Ferramentas MCP e instruções do agente de voz (`agente/`)

Todas de **leitura (nível 0)**. O agente repete os números do retorno, sempre dizendo "estimada" e, se perguntado, o que não inclui.

### Task 12: Leitura (nível 0)
- [x] Ferramentas da tabela "Ferramentas MCP sugeridas".
- [x] Produto e item por **nome falado** (sem acento, sem caixa, como `agente.vendas`); ambíguo → pergunta.

### Task 13: `ver_vendas` com margem
- [x] Liberar a margem: `ver_vendas` pode citar `margens(de, ate)["totais"]["margem_pct"]` **com o rótulo**, ou deixar a margem só em `ver_margem` (escolha da fase 2b; registrar em pendências).

### Task 14: Instruções
- [x] `docs/agente-instrucoes-custos.md` (padrão de `docs/agente-instrucoes-vendas.md`): "quanto custa uma coxinha?", "qual a minha margem esta semana?", "a margem caiu?", "o que mais vende?", "a última produção rendeu quanto?", "como foi o mês?", "a farinha subiu?". Seção "O que pode e o que não pode dizer" (ver contrato).
- [x] `docs/agente-mcp.md`: tabela das ferramentas novas.

---

## Fora deste plano (desenho pronto)

- **Despesas avulsas e recorrentes com categorias** (RF-FIN-02/05, RF-CUS-03/07, CA-35/38) — pendência do Plano 3. Desenho: `Conta.tipo="pagar"` com `origem="despesa"`, `categoria` (fabricação indireta, comercial, operacional, investimento — RF-CUS-07) e `competencia` (mês); `lancar_despesa(descricao, categoria, valor, competencia, parcelas|a_vista)` sobre `executar()`; recorrência como `Recorrencia` que gera conta **prevista** (RN-37) pela rotina. Entra no relatório como bloco "despesas da competência" e no resultado como "resultado depois das despesas".
- **Rateio de indiretos e custo pleno do período** (RF-CUS-04, RN-24, RF-REL-03, CA-34) — depende das despesas de categoria "fabricação indireta". Desenho: `custo_pleno(de, ate)` = custo direto dos lotes produzidos no período (produções + frituras) + indiretos da competência rateados por lote, proporcional ao custo direto, + ajuste de óleo; só relatório, nenhum lote muda. CA-34 vira teste direto (A 600 + B 400, indiretos 500 → 300/200, pleno 1.500).
- **Troca de óleo e ajuste de óleo** (RF-FRI-04, RN-26, CA-25) — desenho no Plano 6 ("Fora deste plano"): `TrocaOleo` em `producao`, ajuste = custo do óleo baixado − Σ óleo de referência × unidades fritas desde a troca anterior; entra no relatório e no custo pleno.
- **Exportar CSV** dos relatórios financeiros e de compras (RF-REL-04, "S") — fase de telas, sobre as mesmas consultas.
- **Gerador "margem abaixo do mínimo"** (Q4): `margem_apresentacoes()` com `margem_varejo_pct < MARGEM_MINIMA` → aviso na caixa (`assunto=margem_baixa:<apresentacao_id>`), sem operação. Só quando o dono der o número.
- **Gerador "ingrediente subiu"** (Q5): `evolucao_preco` da última compra × a anterior acima de um limite → aviso com os produtos afetados (`custos_estimados`). Só quando o dono der o limite.
- **Margem e resultado com despesas comerciais/tributos** — PRD §4 exclui contabilidade/fiscal; só se o dono pedir uma alíquota simples.

## Perguntas em aberto para o dono (com o padrão adotado)

| # | Pergunta | Padrão adotado até a resposta | Custo de estar errado |
|---|---|---|---|
| Q1 | Quando um ingrediente nunca foi comprado pelo sistema (só entrou por "entrada de estoque"), o custo da coxinha deve usar o valor dessa entrada? | **Não**: o custo aparece "incompleto, falta comprar X" (regra do PRD: o custo vem da última compra). | Fichas "incompletas" até a primeira compra de cada ingrediente. Se o dono quiser, a entrada manual vira referência quando não houver compra (mudança pequena em `custos/fichas.py`). |
| Q2 | Quanto custam, por salgado, a mão de obra, o gás e a energia ("indiretos")? Um valor por tamanho? | **Sem valor**: o custo mostra "não inclui indiretos" até alguém preencher o campo no cadastro do tamanho. | A margem estimada parece maior do que é. |
| Q3 | Comparar "esta semana" com a semana passada inteira ou com o mesmo pedaço dela (segunda a hoje)? | **Mesmo pedaço** (segunda a sexta × segunda a sexta). | Receita comparada em tamanhos diferentes, se o dono pensar em semana inteira. |
| Q4 | Existe uma margem mínima abaixo da qual o senhor quer ser avisado? Quanto? | **Nenhum aviso** na caixa (o PRD não define o número). | Um produto pode passar a dar pouca margem sem aviso; o dono vê na tela de margens. |
| Q5 | Quer aviso quando um ingrediente subir muito de preço? A partir de quantos por cento? | **Nenhum aviso**; a evolução de preço fica na consulta. | Aumento de custo percebido tarde. |
| Q6 | Venda feita com lote cujo custo ainda estava pendente: a margem dela deve contar? | **Não conta** (fica "fora da margem" com o motivo), porque o custo gravado é menor que o real. | A margem do período cobre menos vendas. |
| Q7 | O "resultado do período" pode aparecer sem as despesas (aluguel, gás, salários), que o sistema ainda não registra? | **Sim, com o rótulo "estimado" e a lista do que não inclui.** | O dono pode ler como lucro; o texto e a voz sempre dizem "antes das despesas". |
| Q8 | A margem por voz pode ser dita para qualquer pessoa da cozinha? | **Sim, pelo agente** (não há perfis no MVP, design §3). | Informação de margem ouvida por quem não deveria; perfis ficam para depois. |

## Contrato para a fase 2

Consultas: argumentos **keyword-only** (exceto `previsto_realizado_producao(producao_id)` e `intervalo(periodo, ...)`, posicionais por clareza); **não gravam**; devolvem dicts com Decimal e date (quem expõe em JSON usa `DjangoJSONEncoder`); recusas levantam `nucleo.operacoes.RegraViolada` com mensagem em pt-BR. Datas podem ser `date`; períodos falados viram datas com `intervalo`.

### Serviços

Nenhum serviço novo. O campo `Item.indireto_ref_un` é editado pelo admin de itens (já grava por `executar()`); se a tela precisar editar fora do admin, pedir à coordenação um `salvar_referencias(produto_id, oleo_ref_un, indireto_ref_un)` sobre `executar()`.

### Consultas (sem gravar)

| Consulta | Parâmetros | Retorno | Recusas |
|---|---|---|---|
| `custos.fichas.custo_estimado` | `produto_id`, `em=None` (data da referência; padrão hoje) | `{produto_id, produto, ficha_id, ficha, versao, peso_g, em, completo, faltando: [{item_id, item, motivo}], ingredientes, ingredientes_conhecido, indiretos, oleo, custo_cru, custo_frito, inclui: [str], nao_inclui: [str], blocos: [{ficha_id, nome, gramas, custo, custo_conhecido, completo, itens: [{item_id, item, unidade_base, quantidade, referencia, compra_id, data_compra, fornecedor, custo}]}]}` — por **uma unidade**; `None` onde falta referência | "Produto não encontrado."; ficha inválida (mensagens de `validar_ficha`: proporções ≠ 100%, referência circular...) |
| `custos.fichas.custos_estimados` | `ativos=True`, `em=None` | lista de `custo_estimado`; ficha inválida vem `{produto_id, produto, erro, completo: False}` | — |
| `custos.fichas.custo_preparacao` | `ficha_id`, `gramas=None` (padrão: rendimento), `em=None` | `{ficha_id, nome, rendimento_g, gramas, em, completo, faltando, total, conhecido, por_kg, blocos}` | "Preparação não encontrada."; gramas ≤ 0; ficha inválida |
| `custos.consultas.intervalo` | `periodo` ("hoje", "ontem", "semana", "semana_passada", "mes", "mes_passado", "ultimos_7", "ultimos_30"), `hoje=None` | `(de, ate)` | "Período desconhecido: ..." |
| `custos.consultas.intervalo_anterior` | idem | `(de, ate)` do mesmo trecho do período anterior | idem |
| `custos.consultas.previsto_realizado_producao` | `producao_id` | `{producao_id, produto_id, produto, forma, data, versao, unidades, boas, perdas, perda_motivo, rendimento_pct, custo_previsto, custo_real, custo_pendente, desvio_custo, desvio_custo_pct, custo_unitario_previsto, custo_unitario_real, desvio_unitario_pct, oleo_previsto, oleo_real, faltando, itens: [{item_id, item, unidade_base, previsto, usado, desvio_pct, referencia, custo_previsto, custo_real, pendente}]}` ou `None` (não existe ou não concluída) | — |
| `custos.consultas.previsto_realizado` | `de=None`, `ate=None` (dia do encerramento), `produto_id=None` | `{de, ate, producoes: [como acima], por_produto: [{produto_id, produto, producoes, unidades, boas, perdas, rendimento_pct, comparadas, unidades_comparadas, boas_comparadas, custo_previsto, custo_real, desvio_custo, desvio_custo_pct, custo_unitario_previsto, custo_unitario_real}], fora: {custo_pendente: [producao_id], sem_previsto: [producao_id]}}` | — |
| `custos.consultas.margens` | `de=None`, `ate=None`, `agrupar="produto"` ("apresentacao", "cliente", "tabela", "dia"), `cliente_id=None`, `produto_id=None` | `{de, ate, agrupar, rotulo: "estimada", inclui, nao_inclui, totais, grupos: [{chave, nome, **totais}]}`; `totais` = `{vendas, linhas, quantidade, unidades, receita, receita_tabela, desconto, receita_com_custo, custo, margem, margem_pct, fora: {linhas, receita, motivos: {motivo: n}, linha_ids}}` (`margem`/`margem_pct` `None` sem linhas com custo) | "Agrupamento desconhecido: ..." |
| `custos.consultas.margem_das_linhas` | `venda_id` | `[{linha_id, venda_id, data, cliente_id, cliente, tabela, apresentacao_id, apresentacao, produto_id, produto, quantidade, unidades, preco_tabela, preco, receita, receita_tabela, custo, custo_salgado, custo_embalagem, margem, margem_pct, fora_motivo}]` (vazia se cancelada) | — |
| `custos.consultas.comparar_margens` | `de`, `ate`, `de_anterior=None`, `ate_anterior=None` (padrão: os mesmos dias logo antes), `agrupar="produto"` | `{de, ate, de_anterior, ate_anterior, agrupar, rotulo, inclui, nao_inclui, atual: totais, anterior: totais, variacao: {receita, receita_pct, margem, pontos}, grupos: [{chave, nome, receita, receita_anterior, margem_pct, margem_pct_anterior, pontos}]}` | como `margens` |
| `custos.consultas.margem_apresentacoes` | `ativas=True`, `produto_id=None`, `em=None` | `[{apresentacao_id, produto_id, produto, nome, descricao, forma, estado, unidades, preco_varejo, preco_atacado, custo_salgado, custo_embalagem, custo, completo, faltando, erro, margem_varejo, margem_varejo_pct, margem_atacado, margem_atacado_pct, custo_un_ultimo_lote, ultimo_lote_id, rotulo, nao_inclui}]` | — |
| `custos.consultas.ranking_produtos` | `de=None`, `ate=None`, `ordem="receita"` ("unidades", "margem"), `limite=None` | `{de, ate, ordem, total, produtos: [grupo de `margens` + participacao_pct, acumulado_pct], totais, rotulo}` | "Ordem desconhecida..." |
| `custos.consultas.evolucao_preco` | `item_id`, `de=None`, `ate=None` | `{item_id, item, unidade_base, de, ate, compras: [{compra_id, data, fornecedor, quantidade_base, valor, custo_unitario, variacao_pct}], primeiro, ultimo, variacao_pct}` | "Item não encontrado." |
| `custos.relatorios.relatorio_periodo` | `de`, `ate`, `hoje=None` | `{de, ate, dias, vendas: {totais (como margens), custo_gravado, recebido_na_hora, a_prazo, por_forma_pagamento, por_produto, por_cliente, por_tabela, por_dia, canceladas: {vendas, total, venda_ids}}, encomendas: {criadas, valor_criadas, sinais, entregues, valor_entregues, canceladas, valor_canceladas}, producao: {producoes, unidades, boas, perdas, custo_real, custo_pendente, perdas_por_motivo, por_produto, frituras: {frituras, fritas, boas, perdas, custo_total, por_produto}, canceladas}, perdas: {movimentos, por_motivo: [{motivo, movimentos, valor, itens}], valor_movimentos, vendas_canceladas: {vendas, valor, venda_ids}, valor_total, unidades_producao, unidades_fritura}, compras: {compras, total, por_fornecedor, observacao}, dinheiro: {entrou, vendas_a_vista, sinais, recebimentos, saiu, pagamentos, devolvido_vendas, devolvido_sinais, saldo}, posicao: {hoje, a_pagar, a_pagar_vencido, a_receber, a_receber_vencido}, resultado: {receita, custo_vendido, perdas, resultado, resultado_pct, rotulo: "estimado", nao_inclui}, ressalvas: [str]}` | "O fim do período vem antes do início." |
| `compras.consultas.ultimo_custo` | ganha `ate=None` | sem mudança para quem já usa | — |
| `decisoes.consultas.resumo_do_dia` | sem mudança | `totais.operacoes_hoje` agora **sem** a rotina; novo `totais.operacoes_rotina_hoje` | — |

### Telas sugeridas (fase 2a)

Custos dos produtos e das preparações · Margens (com comparação e "fora da margem") · Tabela de preço com margem estimada · Ranking · Previsto × realizado (lista e na produção concluída) · Relatório do período · Evolução de preço do item.

### Ferramentas MCP sugeridas (fase 2b)

| Ferramenta | Nível | Consulta | Por quê |
|---|---|---|---|
| `ver_custo(produto)` | 0 | `custo_estimado` | "quanto custa uma coxinha?" — fala ingredientes, cru/frito e o que falta |
| `ver_margem(periodo="semana", agrupar="produto", comparar=True)` | 0 | `intervalo` + `comparar_margens` (com `intervalo_anterior`) | "qual minha margem?", "caiu?" — fala `margem_pct`, `pontos` e, se houver, "N vendas ficaram de fora" |
| `ver_margem_tabela(produto="")` | 0 | `margem_apresentacoes` | margem estimada de cada preço de tabela |
| `ver_mais_vendidos(periodo="mes", ordem="receita")` | 0 | `ranking_produtos` | "o que mais vende/dá mais lucro?" (3 primeiros) |
| `ver_previsto_realizado(producao_id=None, periodo="semana")` | 0 | `previsto_realizado_producao` / `previsto_realizado` | "a última produção rendeu quanto?" |
| `ver_relatorio(periodo="mes")` | 0 | `relatorio_periodo` | "como foi o mês?" — receita, margem, perdas, resultado "antes das despesas" |
| `ver_evolucao_preco(item)` | 0 | `evolucao_preco` | "a farinha subiu?" |

Nenhuma ferramenta grava. Mudar `indireto_ref_un`/`oleo_ref_un` por voz: **não** (só tela/admin), como o preço (Plano 6, Q10).

### O que o agente de voz passa a poder dizer sobre custo e margem

- O **custo estimado** de um salgado, dizendo "pela última compra de cada ingrediente" e, se `completo=False`, "falta o preço de X; nunca foi comprado".
- A **margem estimada** de um período, produto, cliente ou tabela, sempre com a palavra "estimada", e a variação em **pontos** ("caiu 6 pontos em relação à semana passada"), só a partir de `comparar_margens`.
- Quanto ficou **fora da margem** e por quê (`fora`).
- O **previsto × realizado** de produções (rendimento, ingrediente que passou, custo a mais).
- O **resultado do período** sempre como "antes das despesas" e com as `ressalvas`.

### O que continua proibido

- **Inventar ou calcular número**: custo, margem, ponto, total ou média que não esteja no retorno de uma consulta (design A3). Sem dado → dizer que não há dado.
- **Recomendar preço** ("cobre R$ X") ou "preço sugerido": o sistema não calcula preço sugerido (o PRD não define a regra). No máximo repetir a margem estimada do preço atual.
- Chamar o resultado de **lucro**, ou omitir "estimada"/"antes das despesas".
- Contar como margem as vendas que o núcleo pôs **fora** (custo duvidoso).
- Mudar referência de óleo, indiretos ou preço por voz.
