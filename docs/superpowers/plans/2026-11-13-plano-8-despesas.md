# Plano 8 — Despesas, resultado depois das despesas e estudo de preço pelo CMV — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O dono quer saber **o que sobra depois de todas as despesas** — e ainda não sabe; o sistema existe para revelar isso. Ele lança as despesas pela tela (tudo de uma vez no fim do mês) ou por voz ("paguei 850 de luz"), e o sistema **lembra das contas que se repetem** (vencimento padrão dia 10) para ele "pagar e registrar sem esquecer". O relatório do período passa a mostrar o resultado **antes** e **depois** das despesas; a margem por salgado ganha a versão **com indiretos** (os R$ 0,74 de mão de obra, energia e gás por unidade) e uma conferência "os 74 centavos estão certos?" contra as despesas reais do mês. O preço sai de um **estudo do CMV**: quanto sobra no preço atual, por canal (balcão, cartão), e a simulação "com preço P sobra quanto?" / "para sobrar M%, o preço seria P" — sem o sistema escolher margem nem gravar preço.

**Architecture:** Despesa **é conta a pagar**: `financeiro.Conta` com `origem="despesa"`, mais `categoria` e `competencia` (campos novos). Pagamento, estorno, vencidas, a vencer e os lembretes da caixa seguem o fluxo que já existe para contas de fornecedor. Modelos novos em `financeiro`: `CategoriaDespesa`, `DespesaMensal` (cadastro da recorrente) e `DespesaDoMes` (a recorrente num mês, gerada uma vez pela rotina; sem valor, ainda não tem conta). Serviços em `financeiro/despesas.py`; consultas em `financeiro/consultas.py`. Em `custos`: margens com indiretos (`custos/consultas.py`), relatório com despesas (`custos/relatorios.py`) e o módulo novo `custos/precos.py` (estudo, simulação, ponto de equilíbrio, indireto real). `vendas.CanalVenda` guarda as taxas por canal. `cadastros.servicos`: `criar_tamanho` herda o indireto e `salvar_referencias` (óleo e indireto, só tela).

**Tech Stack:** Python 3.12, uv, Django 5.2, SQLite, pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-10-19-agente-cozinha-design.md` (§3: o sistema nunca movimenta dinheiro; §4 A3: o agente não calcula). PRD `docs/prd/02-prd.md`: RF-FIN-02 (despesa avulsa), RF-FIN-05 (recorrente), RF-FIN-09 (estorno), RF-CUS-03/04/07 (categorias, rateio, separação), RF-REL-02/03, RN-24, RN-33, RN-34, RN-37, CA-34, CA-35, CA-38. Herdado do Plano 7, "Fora deste plano": "Despesas avulsas e recorrentes com categorias" e "Rateio de indiretos e custo pleno (CA-34)"; Q2 e Q7 do Plano 7 (indiretos e "resultado sem as despesas").

## Decisões do dono que este plano segue (conversa de 2026-11-13)

- A margem que interessa é **o que sobra depois de todas as despesas**; não há margem-alvo nem margem mínima ainda.
- O preço deve sair de um **estudo do CMV** (ingredientes + óleo + embalagem), não o contrário.
- Despesas conhecidas: funcionário MEI R$ 2.200/mês; energia ~R$ 850 (só produção); gás 2 × P13 a R$ 115; internet e DAS (a informar); diarista eventual; taxa de cartão (a informar); plataformas só no futuro (hoje 100% balcão). ~200 salgados/dia, segunda a sexta (~4.400/mês). `indireto_ref_un = 0,74` já gravado (0,50 + 0,19 + 0,05).
- Lançamento **híbrido** (tela ou voz); o sistema deve **lembrar das que se repetem**; vencimento padrão **dia 10**; as mensais nascem **sem valor**.
- Padrões antigos: preço não muda por voz; o sistema só **anota** pagamento; o agente **não calcula**, repete a consulta; **valor desconhecido nunca vira zero**.

## O que muda em relação ao PRD (realidade do produto)

- **Recorrente com valor previsto já é conta a pagar** (RN-37 pede "prevista, não aparece até confirmar"). O dono pediu para ser lembrado das contas que se repetem; uma conta "invisível até confirmar" não lembra ninguém. Aqui: **sem valor**, a despesa do mês existe só como `DespesaDoMes` (não é conta, não entra em soma, aparece como "sem valor" nos lembretes); **com valor previsto**, nasce a conta a pagar pelo previsto, e o valor real corrige ao anotar o pagamento. O resultado diz quais entraram "ainda sem pagamento anotado" (ressalva). Pergunta Q2.
- **Categorias simples** (mão de obra, energia, gás, diária, internet, impostos/MEI, taxas, outras), com uma marca `indireta` (gasto da produção) em vez do "método de apropriação" de RF-CUS-03 e da separação fabricação/comercial/operacional/investimento de RF-CUS-07. A marca basta para a única conta que o dono pediu: comparar o indireto de referência com o real. Pergunta Q3.
- **Rateio por lote (RN-24, CA-34) fica de fora**: o dono pensa por salgado, não por lote. No lugar, `indireto_real` divide as despesas indiretas do mês pelas unidades boas produzidas no mês e compara com os R$ 0,74. O desenho do custo pleno por lote está em "Fora deste plano".
- **Imposto (DAS) é despesa** como as outras (categoria "Impostos/MEI"); o sistema não calcula tributo (PRD §4).

## Divisão do plano

| Fase | Quem | Entrega | Situação |
|---|---|---|---|
| **1 — Núcleo** | esta sessão | modelos e migrações, serviços de despesa, rotina, lembretes, consultas de despesas, resultado depois das despesas, margem com indiretos, indireto real, estudo/simulação de preço, ponto de equilíbrio, canais, admin, testes | **feita** (Tasks 1–7) |
| **2a — Telas** | sessão paralela, só `web/` | Despesas (do mês, lançar, mensais, categorias), Relatório com "depois das despesas", Margens com indiretos, Estudo de preço com simulação, Canais e taxas, Referências do salgado (Tasks 8–13) | a fazer |
| **2b — Ferramentas MCP** | sessão paralela, só `agente/` e `docs/` do agente | leitura (nível 0) e lançamento/pagamento de despesa por voz (nível 2, com confirmação), instruções do agente (Tasks 14–16) | **feita** |

As fases 2a e 2b não mexem em modelo, serviço nem consulta; se precisarem de algo do núcleo, pedem à coordenação. O contrato estável está no fim deste documento.

## Decisões deste plano (revisáveis pelo dono)

| Decisão | Por quê / custo se estiver errada |
|---|---|
| **Despesa = `Conta` a pagar com `origem="despesa"`**, uma parcela, sem fornecedor. Nada de app novo. | Pagamento parcial, juros/desconto, estorno, vencidas/a vencer, posição das contas, dinheiro anotado no relatório e lembretes da caixa já existem e valem igual. Custo: consultas antigas de "contas a pagar" passam a incluir despesas (é o certo: são contas a pagar); `devido_por_fornecedor` filtra só compras. |
| **Mensal sem valor = `DespesaDoMes` sem conta.** A conta nasce quando o valor é informado (`informar_valor_despesa`) ou ao anotar o pagamento com o valor (`pagar_despesa_do_mes`). | `Parcela.valor` é obrigatório e todas as somas do financeiro dependem disso; uma conta "de valor nulo" quebraria tudo. Valor desconhecido nunca vira zero. |
| **A rotina gera só o mês corrente**, uma vez por despesa (restrição única `despesa + competência`), antes dos geradores da caixa. Salvar uma mensal ativa já gera o mês corrente. Mudar dia/valor vale para os próximos meses. | Idempotente por construção. Meses passados não são recriados (o dono lança o que faltou como avulsa). |
| **Vencimento**: `dia_vencimento` (padrão 10); mês mais curto → último dia. | Dia 31 em fevereiro vira 28/29. |
| **Valor real corrige o previsto** enquanto não houver pagamento; com pagamento anotado, recusa ("estorne antes"). | Correção financeira só por estorno (RN-34). |
| **Cancelar despesa estorna os pagamentos dela na mesma operação**, com o mesmo motivo; nada é apagado. Mensal cancelada = "não há essa despesa neste mês". | "Lancei errado" em um passo só (voz). O original continua visível (RF-FIN-09). |
| **Competência**: mensal pertence ao **mês** (dia 1), não ao dia do pagamento; avulsa pertence ao **dia da despesa** (`competencia`; padrão: dia do pagamento se paga, senão o dia do lançamento). | "Resultado de setembro" deve ter a luz de setembro mesmo paga em outubro. |
| **Período que pega só parte do mês: mensal rateada por dia** (valor × dias do período no mês ÷ dias do mês), com `rateado=True` e ressalva. Avulsa entra inteira no seu dia. | Comparar uma semana com as despesas do mês inteiro daria prejuízo falso. Custo: a diária do dia de pico pesa toda na sua semana (é verdade). |
| **Lembretes sem duplicar**: despesa com valor usa os geradores de contas (assunto da parcela); sem valor, gerador novo `despesas_sem_valor` (vence em até 3 dias ou vencida; assunto muda de "a_vencer" para "vencida", o anterior fica sem efeito). | Uma situação, um aviso. |
| **Margem com indiretos** = margem − unidades × `indireto_ref_un` (vendas) e preço − (CMV + indiretos) (apresentações). Campos **novos**; os antigos não mudam. Sem referência num produto: `None` e `linhas_sem_indireto`. | Telas e ferramentas no ar dependem dos campos atuais. |
| **Resultado depois das despesas** = resultado (antes) − despesas por competência do período. Despesa sem valor fica fora, com `completo=False`, `faltando` e frase. | O "antes" continua igual (o teste antigo passa intacto). |
| **Indireto real** = despesas das categorias `indireta` (rateadas pelos dias no mês em andamento) ÷ unidades **boas** de produções **concluídas** no mês; referência = média de `indireto_ref_un` ponderada pelas unidades. | É a conta "os 74 centavos estão certos?". Fritura não conta como produção (não faz salgado novo). |
| **`criar_tamanho` herda o indireto** do tamanho mais recente (de qualquer salgado) que tenha valor; quem passar `indireto_ref_un` manda. | Mão de obra, energia e gás por unidade não dependem do recheio; tamanho novo nasce sem "não inclui indiretos". Custo: um tamanho muito maior pode merecer outro valor — `salvar_referencias` corrige. |
| **Estudo de preço só consulta**: CMV, CMV %, indiretos, taxa do canal, contribuição e sobra (R$ e %), por canal ativo. **Simulação** nos dois sentidos, rotulada "simulação"; preço para sobra M% = (CMV + indiretos) ÷ (1 − taxa% − M%), arredondado ao centavo, e a sobra devolvida é a do preço arredondado. | O dono escolhe a margem; o sistema não grava preço nem sugere "o" preço. |
| **Canais de venda** em `vendas.CanalVenda` (balcão dinheiro 0%, balcão pix 0%, débito e crédito sem taxa). Taxa vazia = "não informada" (simular recusa; o estudo mostra `None`). | Taxa desconhecida nunca vira zero. |
| **Ponto de equilíbrio** = despesas do mês ÷ contribuição (preço − CMV − taxa), arredondado para cima, como se todas as vendas fossem daquela apresentação. **Sem** os indiretos de referência na contribuição. | Mão de obra, energia e gás já estão nas despesas; contar duas vezes inflaria o ponto. |

## Definições (cada número)

| Número | Definição |
|---|---|
| Despesa do mês (mensal) | `DespesaDoMes` da competência (dia 1). Valor = `Conta.total` (previsto ou informado); sem conta = "sem valor". |
| Situação da despesa | `sem_valor` · `aberta` · `parcial` · `paga` · `cancelada` (da parcela, como no financeiro); `vencida` = sem valor/aberta/parcial com vencimento antes de hoje. |
| Despesas do mês: `valor`, `pago`, `falta_pagar` | Σ das mensais com valor e avulsas com competência no mês, não canceladas: valor; pagamentos não estornados; saldo. `sem_valor` = quantas sem valor (fora das somas); `completo` = nenhuma sem valor. |
| Despesas do período | Mensais: valor × dias do período no mês ÷ dias do mês (inteiro se o período cobre o mês). Avulsas com competência no período, inteiras. Canceladas fora. `indiretas` = só categorias `indireta`. |
| Resultado antes das despesas | Igual ao Plano 7: receita − custo gravado das vendas concluídas − perdas com valor. |
| Resultado depois das despesas | resultado antes − despesas do período. `resultado_pct` = ÷ receita × 100. |
| Indiretos (venda) | unidades vendidas × `indireto_ref_un` do produto, 2 casas, por linha. |
| Margem com indiretos | margem − indiretos (só linhas com custo confiável e todas com referência). `_pct` = ÷ receita com custo. |
| CMV (apresentação) | `custo` de `margem_apresentacoes`: ingredientes pela ficha + óleo de referência (frito) + embalagem. |
| Custo com indiretos (apresentação) | CMV + unidades × `indireto_ref_un`. |
| Taxa do canal | preço × `taxa_pct` ÷ 100, 2 casas. |
| Contribuição | preço − CMV − taxa. |
| Sobra | contribuição − indiretos; `sobra_pct` = sobra ÷ preço × 100; `sobra_un` = sobra ÷ unidades da apresentação. |
| Preço para sobra M% | (CMV + indiretos) ÷ (1 − taxa%/100 − M/100), `ROUND_HALF_UP` ao centavo. |
| Ponto de equilíbrio | ⌈despesas do mês ÷ contribuição⌉ apresentações; receita = apresentações × preço. |
| Indireto real por unidade | despesas indiretas do mês (até hoje, rateadas, no mês em andamento) ÷ Σ `quantidade_boa` das produções concluídas no mês; 4 casas. `despesa_total_un` idem com todas as despesas. |
| Referência média | Σ (`indireto_ref_un` × boas do produto) ÷ Σ boas dos produtos com referência. `diferenca_pct` = (real − referência) ÷ referência × 100. |

Arredondamento: como no Plano 7 (Decimal, `ROUND_HALF_UP`; dinheiro 2 casas, por unidade 4, % 1 casa).

## Global Constraints

- Tudo dos Planos 1 a 7 continua valendo: Decimal sempre; toda gravação por `executar()`; nada é apagado (RN-34).
- Consultas não gravam e dizem o que ficou de fora (`completo`, `faltando`, `ressalvas`). **Despesa sem valor e taxa não informada nunca viram zero.**
- Compra de item estocável **não** é despesa (RN-33): continua só em `compras` e no custo de quem usa o item.
- O sistema não escolhe margem nem grava preço a partir do estudo; simulação é rotulada "simulação".

## Review Focus

- Rotina idempotente e mês sem valor (`test_despesa_mensal_gera_a_conta_do_mes_uma_unica_vez`, `test_despesa_sem_valor_lembra_sem_duplicar_e_pede_o_valor_ao_pagar`).
- Valor real corrigindo o previsto; estorno antes de mudar valor pago (`test_previsto_corrigido_pelo_valor_real_e_lembrete_da_conta`).
- Avulsa paga/a pagar, cancelada com estorno, "parecidas" (`test_despesa_avulsa_paga_a_pagar_e_cancelada_com_estorno`).
- Competência e rateio por dia (`test_despesas_por_competencia_rateadas_no_periodo_parcial`).
- Resultado depois das despesas com despesa faltando, e o "antes" intacto (`test_resultado_depois_das_despesas_com_despesa_faltando`).
- Margem com indiretos sem mudar a margem (`test_margem_com_indiretos_nas_vendas_sem_mudar_a_margem`, `test_margem_cheia_das_apresentacoes_e_referencias`).
- Estudo, simulação com taxa de canal, ponto de equilíbrio, indireto real (`test_estudo_de_preco_pelo_cmv_por_canal`, `test_simulacao_de_preco_nos_dois_sentidos`, `test_ponto_de_equilibrio_do_mes`, `test_indireto_real_do_mes_contra_a_referencia`).

---

## Fase 1 — Núcleo (feita)

### Task 1: Modelos e migrações
**Files:** `financeiro/models.py`, `financeiro/migrations/0004_despesas.py`, `financeiro/migrations/0005_categorias_iniciais.py`, `vendas/models.py`, `vendas/migrations/0002_canais_de_venda.py`, `vendas/migrations/0003_canais_iniciais.py`.
- [x] `CategoriaDespesa(nome, indireta, ativa, ordem)`, `DespesaMensal(nome, categoria, dia_vencimento=10, valor_previsto?, ativa)`, `DespesaDoMes(despesa, competencia, vencimento, conta?, operacao)` com única `despesa + competencia`.
- [x] `Conta.categoria` e `Conta.competencia` (anuláveis: contas antigas não mudam).
- [x] `CanalVenda(nome, taxa_pct?, ativo, ordem)`.
- [x] Dados iniciais: 8 categorias (mão de obra, energia, gás, diária = indiretas; internet, impostos/MEI, taxas, outras) e 4 canais (balcão dinheiro 0%, balcão pix 0%, débito e crédito sem taxa). `get_or_create`: reaplicar não duplica; banco existente só ganha tabelas e colunas anuláveis.

### Task 2: Serviços de despesa
**Files:** `financeiro/despesas.py`.
- [x] `salvar_categoria_despesa`, `salvar_despesa_mensal` (gera o mês corrente), `gerar_despesas_do_mes` (rotina), `lancar_despesa`, `cancelar_despesa`, `informar_valor_despesa`, `pagar_despesa_do_mes`.

### Task 3: Rotina, lembretes e resumo do dia
**Files:** `decisoes/geradores.py`, `decisoes/consultas.py`, `decisoes/management/commands/rotina_diaria.py`.
- [x] `rodar_rotina` gera as despesas do mês antes dos geradores (`saida["despesas_do_mes"]`); gerador `despesas_sem_valor`.
- [x] `resumo_do_dia`: bloco `despesas` (`sem_valor`, `sem_valor_vencidas`) e `totais.despesas_sem_valor`; rótulos das operações novas.

### Task 4: Consultas de despesas
**Files:** `financeiro/consultas.py`.
- [x] `categorias_despesa`, `despesas_mensais`, `despesas_do_mes`, `despesas_sem_valor`, `despesas_em_aberto`, `despesas_vencidas`, `despesas_periodo`; `parcelas_em_aberto(origem=)`; parcela com `origem`, `categoria_id`, `categoria`, `competencia`.

### Task 5: Resultado depois das despesas e margem com indiretos
**Files:** `custos/relatorios.py`, `custos/consultas.py`.
- [x] `relatorio_periodo`: `despesas` e `depois_das_despesas`.
- [x] `margens`/`comparar_margens`/`margem_das_linhas`/`ranking_produtos`: `indiretos`, `margem_com_indiretos`, `margem_com_indiretos_pct`, `linhas_sem_indireto`; `margem_apresentacoes`: `indiretos`, `custo_com_indiretos`, `margem_*_com_indiretos(_pct)`.

### Task 6: Referências, estudo de preço, ponto de equilíbrio, indireto real, canais
**Files:** `cadastros/servicos.py`, `custos/precos.py`, `vendas/servicos.py`, `financeiro/admin.py`, `vendas/admin.py`.
- [x] `criar_tamanho` herda o indireto; `salvar_referencias`; `salvar_canal_venda`.
- [x] `canais_venda`, `estudo_preco`, `simular_preco`, `ponto_equilibrio`, `indireto_real`.
- [x] Admin: categorias, despesas mensais e canais editáveis (gravam por `executar()`); despesa do mês só leitura; conta mostra origem, categoria e competência.

### Task 7: Testes e fechamento
**Files:** `tests/test_despesas.py`.
- [x] 13 testes; suíte inteira verde; `makemigrations --check` sem mudanças.

---

## Fase 2a — Telas (`web/`)

Padrão das telas existentes: login, 360 px sem rolagem horizontal, **a tela nunca calcula**. Valor `None` aparece como "—" com o motivo ("sem valor", "taxa não informada"), **nunca "R$ 0,00"**. Resultado sempre "estimado"; simulação sempre "simulação — o preço da tabela não muda".

### Task 8: Despesas do mês (a tela do "fim do mês")
- [ ] `/despesas/?mes=AAAA-MM`: `despesas_do_mes(competencia=)` — mensais (situação, valor, vencimento; "sem valor" em destaque com campo de valor) e avulsas; totais (valor, pago, falta pagar, "N sem valor"). Ações: informar valor (`informar_valor_despesa`), pagar (`pagar_despesa_do_mes` com valor, data, forma — padrão o valor já lançado), cancelar (`cancelar_despesa` com motivo), estornar pagamento (`estornar_pagamento`).
- [ ] Lançar avulsa (`lancar_despesa`): descrição, categoria, valor, "já paga" (data, forma) ou vencimento, competência opcional. Se o retorno trouxer `parecidas`, mostrar "a Energia deste mês ainda está em aberto — era ela?" com link para pagar a mensal (e cancelar a avulsa, se for o caso).
- [ ] Lançamento em lote no fim do mês: a mesma tela com uma linha por mensal sem valor/aberta e "pagar" em cada uma (uma chamada por linha, cada uma com a sua `chave`).

### Task 9: Despesas mensais e categorias
- [ ] `/despesas/mensais/`: `despesas_mensais()`; criar/editar (`salvar_despesa_mensal`: nome, categoria, dia — padrão 10 —, valor previsto opcional, ativa). Explicar: "mudar dia ou valor vale do próximo mês em diante".
- [ ] `/despesas/categorias/`: `categorias_despesa(ativas=False)`; `salvar_categoria_despesa` (nome, "é gasto da produção", ativa).

### Task 10: Relatório com "depois das despesas"
- [ ] Na tela do relatório (`/relatorio/`): bloco "Despesas do período" (`despesas.por_categoria`, `faltando`, `ressalvas`) e "Resultado" com duas linhas: **antes das despesas** (`resultado`) e **depois das despesas** (`depois_das_despesas`), com `completo=False` → "faltando: Internet de 09/2026 sem valor".

### Task 11: Margens com indiretos e "os 74 centavos estão certos?"
- [ ] Margens e tabela de preço: coluna "com indiretos" (`margem_com_indiretos(_pct)`, `margem_*_com_indiretos(_pct)`), rótulo `rotulo_com_indiretos`; "N linhas sem indireto de referência".
- [ ] `/custos/indiretos/?mes=`: `indireto_real(competencia=)` — real × referência por unidade, diferença em R$ e %, por categoria, ressalvas.

### Task 12: Estudo de preço
- [ ] `/precos/estudo/?tabela=varejo`: `estudo_preco(tabela=)` — por apresentação: preço, CMV (R$ e %), indiretos, e por canal: taxa, sobra (R$, %, por unidade).
- [ ] Simulador na mesma tela: apresentação, canal, e "preço" **ou** "quero que sobre __%" → `simular_preco`. Mostrar `aviso`.
- [ ] Ponto de equilíbrio: `ponto_equilibrio(apresentacao_id, competencia, canal_id)` — "precisa vender N por mês (R$ X)" com `ressalvas`.

### Task 13: Canais e referências
- [ ] `/precos/canais/`: `canais_venda(ativos=False)`; `salvar_canal_venda` (nome, taxa %, ativo).
- [ ] No cadastro do tamanho: óleo e indireto de referência por `salvar_referencias` (só tela).

---

## Fase 2b — Ferramentas MCP e instruções do agente de voz (`agente/`)

Feita: ver `2026-11-13-plano-8-pendencias-agente.md` (nomes finais, alçada — pagamento, lançamento e cancelamento ficaram nível 2 — e o que ficou para depois).

### Task 14: Leitura (nível 0)
- [x] Ferramentas da tabela "Ferramentas MCP sugeridas" de nível 0. Despesa e categoria por **nome falado** (sem acento/caixa; "luz" = categoria Energia ou mensal com "energia"/"luz" no nome; ambíguo → pergunta).

### Task 15: Despesa por voz (nível 1, com confirmação)
- [x] `pagar_despesa(nome, valor, data="hoje")`: se houver `DespesaDoMes` do mês corrente em aberto que case com o nome → `pagar_despesa_do_mes`; senão → `lancar_despesa(paga=True)`. Antes de gravar, repete "anoto R$ 850,00 de Energia de novembro como paga hoje?".
- [x] `lancar_despesa_a_pagar(descricao, categoria, valor, vencimento)` → `lancar_despesa(paga=False)`.
- [x] `informar_valor_despesa(nome, valor)` ("a conta de internet veio 99,90").
- [x] `cancelar_despesa(...)` só com motivo e confirmação.

### Task 16: Instruções
- [x] `docs/agente-instrucoes-despesas.md`: "paguei 850 de luz", "o que falta pagar este mês?", "tem conta vencida?", "quanto sobrou no mês depois das despesas?", "a coxinha dá quanto depois de tudo?", "os 74 centavos estão certos?", "se eu vender a 6 reais, sobra quanto?", "quanto teria que cobrar para sobrar 40%?". Seção "o que pode e o que não pode dizer" (ver contrato).
- [x] `docs/agente-mcp.md`: tabela das ferramentas novas.

---

## Fora deste plano (desenho pronto)

- **Custo pleno por lote (RN-24, RF-CUS-04, RF-REL-03, CA-34)**: `custo_pleno(de, ate)` = custo direto dos lotes produzidos no período + despesas `indireta` do período (de `despesas_periodo`) rateadas por lote, proporcional ao custo direto, + ajuste de óleo; só relatório. CA-34 vira teste direto (A 600 + B 400, indiretos 500 → 300/200, pleno 1.500). Fica de fora porque o dono pensa por salgado (`indireto_real` responde) e o ajuste de óleo ainda não existe.
- **Troca e ajuste de óleo** (RF-FRI-04, RN-26, CA-25) — desenho no Plano 6.
- **Taxa de cartão automática na venda**: `Venda.forma_pagamento` → canal → taxa como despesa "Taxas" do dia. Hoje a taxa entra só no estudo de preço; no resultado, só se o dono lançar a despesa de taxa (avulsa ou mensal). Depende de Q5.
- **Recorrência com periodicidade diferente de mensal** (semanal, anual) e **parcelas** em despesa avulsa (hoje uma parcela). `lancar_despesa` pode ganhar `parcelas` reaproveitando `_ler_parcelas`.
- **Mensal de meses passados**: a rotina não recria; se o dono cadastrar em novembro e quiser outubro, lança avulsa com `competencia` em outubro.
- **Plataformas (iFood, 99)**: basta cadastrar o canal com a taxa; repasse e comissão como despesa ficam para quando houver venda por elas.
- **Avisos "despesa do mês acima do normal"** e **"indireto real muito acima da referência"**: só com um limite dado pelo dono.

## Perguntas em aberto para o dono (com o padrão adotado)

| # | Pergunta | Padrão adotado até a resposta | Custo de estar errado |
|---|---|---|---|
| Q1 | A luz paga em outubro, mas que é de setembro, conta no resultado de setembro ou de outubro? | **Setembro** (o mês da conta). Despesa mensal pertence ao mês dela; avulsa ao dia em que aconteceu. | Se o dono pensar "pelo dia que o dinheiro saiu", o resultado do mês fica diferente do extrato; o "dinheiro do período" do relatório continua mostrando pelo dia do pagamento. |
| Q2 | Uma despesa mensal com valor previsto (o funcionário, R$ 2.200) já deve aparecer em "contas a pagar" e no resultado antes de o senhor confirmar? | **Sim**: aparece pelo previsto; ao pagar, o senhor diz o valor real e ele substitui o previsto. O resultado avisa "ainda sem pagamento anotado". Sem valor previsto, ela só aparece como "sem valor" e não entra em soma. | Se o previsto estiver longe do real, o resultado do mês fica errado até o pagamento ser anotado (o aviso diz isso). |
| Q3 | Quais despesas são "da produção" (entram na conta dos 74 centavos)? | **Mão de obra, energia, gás e diária**. Internet, impostos/MEI, taxas e outras ficam fora (mas entram no resultado depois das despesas). Cada categoria pode ser trocada. | Indireto real por salgado mais alto ou mais baixo do que deveria. |
| Q4 | Num relatório de uma semana, como entram as despesas do mês? | **Pela parte dos dias** (1/30 da luz por dia de um mês de 30 dias). A diarista entra inteira no dia dela. | Uma semana pode parecer melhor ou pior do que o mês inteiro; o mês fechado é a conta certa. |
| Q5 | Qual a taxa da maquininha no débito e no crédito? Quer que a taxa de cada venda no cartão vire despesa sozinha? | **Taxas em branco** ("não informada"); a taxa só aparece no estudo de preço quando for cadastrada, e no resultado só se for lançada como despesa. | Sem a taxa, o estudo mostra "—" no cartão e o resultado pode ficar maior que o real. |
| Q6 | O tamanho novo de salgado deve copiar os 74 centavos do último tamanho cadastrado? | **Sim, copia** (pode ser mudado na tela). | Um salgado grande pode gastar mais energia/mão de obra; corrige-se na tela. |
| Q7 | Quanto o senhor quer que sobre por salgado (em %)? | **Nenhum número**: o sistema mostra quanto sobra hoje e simula com o número que o senhor disser. | Nenhum (é escolha do dono). |
| Q8 | O agente pode anotar pagamento de despesa por voz e cancelar despesa por voz? | **Anotar sim, com confirmação** (como pagamento de fornecedor). **Cancelar só com motivo e confirmação.** Mudar previsto, dia ou categoria de mensal: **só tela**. | Despesa anotada errado por voz — corrige-se cancelando (estorna junto). |
| Q9 | Despesa mensal que o senhor cancela num mês ("não teve internet em outubro") deve sumir dos avisos daquele mês? | **Sim**: cancelada = não há essa despesa no mês. | Se cancelar por engano, perde o lembrete daquele mês (o cancelamento fica na trilha). |

## Contrato para a fase 2

Consultas: argumentos **keyword-only**; **não gravam**; devolvem dicts com Decimal e date (quem expõe em JSON usa `DjangoJSONEncoder`). Serviços: gravam por `executar()` (auditados, idempotentes por `chave`) e **devolvem o resultado já em JSON** (Decimal e date como texto). Recusas: `nucleo.operacoes.RegraViolada` com mensagem em pt-BR.

### Serviços

| Serviço | Parâmetros | Retorno | Recusas |
|---|---|---|---|
| `financeiro.despesas.salvar_categoria_despesa` | `nome`, `indireta=False`, `ativa=True`, `categoria_id=None`, `autor`, `canal`, `chave` | `{categoria_id, nome}` | "Informe o nome da categoria."; "Já existe a categoria 'X'."; "Categoria não encontrada." |
| `financeiro.despesas.salvar_despesa_mensal` | `nome`, `categoria_id`, `dia_vencimento=10`, `valor_previsto=None`, `ativa=True`, `despesa_id=None`, `hoje=None`, `autor`, `canal`, `chave` | `{despesa_id, nome, despesa_do_mes_gerada}` (id da despesa do mês corrente se foi criada agora) | nome vazio; "Escolha a categoria da despesa."; categoria inativa; "O dia de vencimento vai de 1 a 31."; previsto ≤ 0; "Já existe a despesa mensal 'X'."; "Despesa mensal não encontrada." |
| `financeiro.despesas.gerar_despesas_do_mes` | `hoje=None`, `autor="rotina"`, `canal="sistema"` | `{competencia, criadas: [despesa_do_mes_id]}` | — (a rotina chama; a tela não precisa) |
| `financeiro.despesas.lancar_despesa` | `descricao`, `categoria_id`, `valor`, `paga=False`, `data_pagamento=None` (padrão hoje), `vencimento=None` (obrigatório se não paga), `competencia=None`, `forma=""`, `hoje=None`, `autor`, `canal`, `chave` | `{conta_id, parcela_id, valor, paga, vencimento, competencia, parecidas: [{despesa_do_mes_id, despesa, vencimento}]}` | "Diga do que é a despesa."; categoria; "Informe o valor da despesa (maior que zero)."; "Informe o vencimento (ou diga que já está paga)."; datas inválidas |
| `financeiro.despesas.cancelar_despesa` | `conta_id`, `motivo`, `autor`, `canal`, `chave` | `{conta_id, pagamentos_estornados: [pagamento_id]}` | "Despesa não encontrada." (inclui conta que não é despesa); "Esta despesa já foi cancelada."; "Informe o motivo do cancelamento." |
| `financeiro.despesas.informar_valor_despesa` | `despesa_do_mes_id`, `valor`, `autor`, `canal`, `chave` | `{despesa_do_mes_id, conta_id, valor_anterior, valor}` | "Despesa do mês não encontrada."; "A despesa X de MM/AAAA foi cancelada."; valor ≤ 0; "Já há pagamento anotado de X: estorne o pagamento antes de mudar o valor." |
| `financeiro.despesas.pagar_despesa_do_mes` | `despesa_do_mes_id`, `valor=None` (o valor real da conta; sem ele, paga o que já está lançado), `data_pagamento=None`, `forma=""`, `autor`, `canal`, `chave` | `{despesa_do_mes_id, conta_id, pagamento_id, parcela_id, valor, valor_pago, situacao, saldo}` | as de `informar_valor_despesa`; "X de MM/AAAA ainda não tem valor: diga quanto foi pago."; "X de MM/AAAA já está paga (R$ …)." |
| `financeiro.servicos.registrar_pagamento` / `estornar_pagamento` | sem mudança | valem para despesas (são contas a pagar): pagamento parcial, juros/multa/desconto, estorno | — |
| `cadastros.servicos.criar_tamanho` | ganha `indireto_ref_un=None` | ganha `indireto_ref_un` e `indireto_herdado_de: {item_id, nome}` ou `None` | — |
| `cadastros.servicos.salvar_referencias` | `produto_id`, `oleo_ref_un=None`, `indireto_ref_un=None` (vazio = sem referência; **os dois são gravados**: mande os dois), `autor`, `canal`, `chave` | `{produto_id, antes: {oleo_ref_un, indireto_ref_un}, depois: {...}}` | "Produto não encontrado."; "A referência não pode ser negativa."; valor inválido |
| `vendas.servicos.salvar_canal_venda` | `nome`, `taxa_pct=None`, `ativo=True`, `canal_id=None`, `autor`, `canal`, `chave` | `{canal_id, nome, taxa_pct}` | nome vazio; "A taxa vai de 0% a menos de 100%."; "Já existe o canal 'X'."; "Canal não encontrado." |

### Consultas (sem gravar)

| Consulta | Parâmetros | Retorno | Recusas |
|---|---|---|---|
| `financeiro.consultas.categorias_despesa` | `ativas=True` | `[{categoria_id, nome, indireta, ativa}]` | — |
| `financeiro.consultas.despesas_mensais` | `ativas=None` (todas) | `[{despesa_id, nome, categoria_id, categoria, indireta, dia_vencimento, valor_previsto, ativa}]` | — |
| `financeiro.consultas.despesas_do_mes` | `competencia=None` (qualquer dia do mês; padrão hoje), `hoje=None` | `{competencia, mensais: [{despesa_do_mes_id, despesa_id, despesa, categoria_id, categoria, indireta, competencia, vencimento, dias, conta_id, parcela_id, valor_previsto, valor, pago, saldo, situacao, vencida}], avulsas: [{conta_id, parcela_id, descricao, categoria_id, categoria, indireta, competencia, vencimento, valor, pago, saldo, situacao, vencida, motivo_cancelamento}], totais: {valor, pago, falta_pagar, sem_valor, completo, vencidas}}` — `valor`/`saldo` `None` quando `situacao="sem_valor"` | — |
| `financeiro.consultas.despesas_sem_valor` | `ate=None` (vencimento até), `hoje=None` | lista como `mensais` acima | — |
| `financeiro.consultas.despesas_em_aberto` | `hoje=None` | `{parcelas: [como parcelas_em_aberto], sem_valor: [como mensais], vencidas: [das duas], total, completo}` | — |
| `financeiro.consultas.despesas_vencidas` | `hoje=None` | `vencidas` acima | — |
| `financeiro.consultas.despesas_periodo` | `de`, `ate`, `hoje=None` | `{de, ate, total, indiretas, completo, rateado, por_categoria: [{categoria_id, categoria, indireta, valor, lancamentos, completo}], mensais: [mensal + valor_mes, dias, dias_mes; valor = rateado], avulsas, faltando: [{despesa_do_mes_id, despesa, competencia, categoria, motivo}], ressalvas: [str]}` | — |
| `financeiro.consultas.parcelas_em_aberto` | ganha `origem=None` | cada parcela ganha `origem`, `categoria_id`, `categoria`, `competencia` (todas as consultas de parcela: `contas_vencidas`, `contas_a_vencer`, `detalhe_conta`...) | — |
| `custos.consultas.margens` / `comparar_margens` / `ranking_produtos` | sem mudança | `totais` e cada grupo ganham `indiretos`, `margem_com_indiretos`, `margem_com_indiretos_pct`, `linhas_sem_indireto`; `margens` ganha `rotulo_com_indiretos` | — |
| `custos.consultas.margem_das_linhas` | sem mudança | cada linha ganha `indiretos`, `margem_com_indiretos`, `margem_com_indiretos_pct` | — |
| `custos.consultas.margem_apresentacoes` | sem mudança | ganha `indiretos`, `custo_com_indiretos`, `margem_varejo_com_indiretos(_pct)`, `margem_atacado_com_indiretos(_pct)` | — |
| `custos.relatorios.relatorio_periodo` | sem mudança | ganha `despesas` (= `despesas_periodo`) e `depois_das_despesas: {resultado_antes, despesas, resultado, resultado_pct, completo, faltando, rateado, rotulo, nao_inclui, ressalvas}`; `resultado.nao_inclui[0]` mudou de texto (ver "Mudanças em retornos") | como antes |
| `custos.precos.canais_venda` | `ativos=True` | `[{canal_id, nome, taxa_pct, ativo}]` | — |
| `custos.precos.estudo_preco` | `produto_id=None`, `tabela="varejo"` ("atacado"), `ativas=True`, `em=None` | `{tabela, rotulo: "estimado", canais, observacao, apresentacoes: [{apresentacao_id, produto_id, produto, nome, descricao, forma, unidades, tabela, preco, preco_un, cmv, cmv_un, cmv_pct, custo_salgado, custo_embalagem, indiretos, custo_com_indiretos, completo, faltando, erro, por_canal: [{canal_id, canal, taxa_pct, taxa, contribuicao, contribuicao_pct, sobra, sobra_pct, sobra_un, faltando}]}]}` | "Tabela desconhecida: use varejo ou atacado." |
| `custos.precos.simular_preco` | `apresentacao_id`, `preco=None` **ou** `sobra_pct=None`, `canal_id=None` (padrão: primeiro canal ativo, balcão), `tabela="varejo"`, `em=None` | `{rotulo: "simulação", aviso, apresentacao_id, descricao, unidades, canal_id, canal, taxa_pct, tabela, preco_atual, sobra_pct_pedida, preco, preco_un, cmv, cmv_pct, indiretos, inclui_indiretos, taxa, contribuicao, sobra, sobra_pct, sobra_un, diferenca_preco_atual}` | "Informe o preço ou a sobra desejada (um dos dois)."; "Apresentação não encontrada."; "O custo de X está incompleto: …"; "Canal de venda não encontrado."; "A taxa do canal 'X' não foi informada…"; "Não existe preço que deixe sobrar M% com taxa de T%…"; preço ≤ 0; sobra negativa |
| `custos.precos.ponto_equilibrio` | `apresentacao_id`, `competencia=None`, `canal_id=None`, `tabela="varejo"`, `hoje=None`, `em=None` | `{rotulo: "estimado", competencia, apresentacao_id, descricao, unidades_por, canal, taxa_pct, preco, cmv, taxa, contribuicao, despesas, completo, faltando: [nome], apresentacoes, unidades, receita, ressalvas}` | as de `simular_preco`; "X não tem preço de atacado."; "Com o preço de P cada venda não cobre nem o CMV e a taxa…" |
| `custos.precos.indireto_real` | `competencia=None` (padrão: mês de hoje), `hoje=None` | `{rotulo: "estimado", competencia, de, ate, unidades_produzidas, por_produto: [{produto_id, produto, indireto_ref_un, unidades}], despesas_indiretas, despesas_total, por_categoria, completo, faltando, indireto_real_un, despesa_total_un, referencia_un, diferenca_un, diferenca_pct, ressalvas}` (`None` sem unidades ou sem referência) | "Esse mês ainda não começou." |
| `decisoes.consultas.resumo_do_dia` | sem mudança | ganha `despesas: {sem_valor, sem_valor_vencidas}` e `totais.despesas_sem_valor`; `contas` passa a incluir despesas com valor (`origem="despesa"`) | — |
| `decisoes.geradores.rodar_rotina` | sem mudança | ganha `despesas_do_mes: {competencia, criadas}` (ou `{erro}`); gerador novo `despesas_sem_valor` | — |

### Mudanças em retornos já existentes

- **Só acréscimos de chaves**, com uma exceção de texto: `relatorio_periodo()["resultado"]["nao_inclui"][0]` era "despesas (aluguel, gás, energia, salários): o sistema ainda não registra despesas" e agora é "despesas (aluguel, gás, energia, salários): veja o resultado depois das despesas" (o começo foi mantido: a tela do relatório no ar e o teste dela conferem esse trecho).
- **Contas a pagar incluem despesas**: `parcelas_em_aberto()`, `contas_vencidas()`, `contas_a_vencer()`, `resumo_do_dia()["contas"]`, `relatorio_periodo()["posicao"]` e o gerador da caixa passam a trazer as despesas com valor (é o pedido: lembrar). Quem mostra "fornecedor" deve cair em `descricao` quando `fornecedor` vier vazio (os geradores já fazem). `devido_por_fornecedor` passou a filtrar só contas de compra (antes não havia outra origem de conta a pagar; o número não muda para compras).
- `relatorio_periodo()["dinheiro"]["pagamentos"]` passa a incluir pagamentos de despesas (é dinheiro que saiu).
- Retorno de `criar_tamanho` ganha `indireto_ref_un` e `indireto_herdado_de`; os parâmetros gravados na trilha ganham `indireto_ref_un`.

### Telas sugeridas (fase 2a)

Despesas do mês (com lançar avulsa e pagar/informar valor em lote) · Despesas mensais · Categorias · Relatório com "antes" e "depois das despesas" · Margens e tabela com "com indiretos" · Indireto real ("os 74 centavos") · Estudo de preço com simulador e ponto de equilíbrio · Canais e taxas · Referências do salgado (óleo e indireto).

### Ferramentas MCP sugeridas (fase 2b)

| Ferramenta | Nível | Serviço / consulta | Por quê |
|---|---|---|---|
| `ver_despesas(mes="este")` | 0 | `despesas_do_mes` | "o que falta pagar este mês?" — fala `falta_pagar`, as vencidas e as "sem valor" |
| `ver_despesas_vencidas()` | 0 | `despesas_em_aberto` | "tem conta vencida?" (fornecedor continua em `ver_contas`) |
| `ver_resultado(periodo="mes")` | 0 | `intervalo` + `relatorio_periodo` | "quanto sobrou depois das despesas?" — `depois_das_despesas` com `faltando` |
| `ver_indireto_real(mes="este")` | 0 | `indireto_real` | "os 74 centavos estão certos?" |
| `ver_estudo_preco(produto="")` | 0 | `estudo_preco` | "quanto sobra numa coxinha?" — CMV, sobra no balcão e no cartão |
| `simular_preco(produto, apresentacao, preco=None, sobra_pct=None, canal="")` | 0 | `simular_preco` | "se eu vender a 6, sobra quanto?" / "para sobrar 40%, quanto cobro?" — sempre "é uma simulação" |
| `ver_ponto_equilibrio(produto, apresentacao)` | 0 | `ponto_equilibrio` | "quantas preciso vender para pagar as contas?" |
| `pagar_despesa(nome, valor, data="hoje", forma="")` | 1 | `pagar_despesa_do_mes` ou `lancar_despesa(paga=True)` | "paguei 850 de luz" — confirmação antes |
| `lancar_despesa(descricao, categoria, valor, vencimento)` | 1 | `lancar_despesa` | "chegou o boleto do gás, vence dia 20" |
| `informar_valor_despesa(nome, valor)` | 1 | `informar_valor_despesa` | "a internet veio 99,90" |
| `cancelar_despesa(...)` | 2 | `cancelar_despesa` | só com motivo, confirmação e repetindo o que será estornado |

Por voz **não**: criar/alterar despesa mensal, categoria, canal, taxa, `salvar_referencias` e preço (só tela).

### O que o agente de voz passa a poder dizer

- O que falta pagar no mês, o que venceu e o que **ainda não tem valor** ("a internet de novembro ainda não tem valor").
- O resultado **antes e depois das despesas**, sempre "estimado", e, se `completo=False`, "faltando a internet, sem valor".
- A margem **com indiretos** e o **indireto real** contra a referência, só a partir das consultas.
- O CMV, quanto **sobra** por salgado no preço atual e, numa **simulação** pedida, o preço ou a sobra — dizendo "é só uma simulação, o preço não mudou".

### O que continua proibido

- **Calcular** qualquer número (sobra, preço, rateio, ponto de equilíbrio) fora do retorno das consultas.
- **Escolher a margem** ou recomendar "o" preço; mudar preço, taxa, referência ou despesa mensal por voz.
- Dizer que **pagou**: o sistema só anota o pagamento.
- Tratar despesa sem valor ou taxa não informada como **zero**; chamar o resultado de "lucro" sem "estimado".
