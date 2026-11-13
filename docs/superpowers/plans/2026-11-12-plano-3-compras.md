# Plano 3 — Compras, recebimento e contas a pagar — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O dono lança a compra do atacarejo (fornecedor, itens na unidade em que comprou, frete, desconto, total) e diz se pagou na hora ou a prazo. Quando a mercadoria chega, registra o que veio (tudo, parte ou o resto depois), com lote e validade, e só isso entra no estoque, com o custo certo. O que não veio fica pendente até chegar ou ser encerrado. As contas a pagar mostram o que vence e quanto se deve a cada fornecedor, e o dono anota o que pagou. O consumo que ficou sem estoque na produção é conciliado quando a compra entra.

**Architecture:** Dois apps novos: `compras` (compra, linhas, recebimentos) e `financeiro` (conta, parcelas, pagamentos, avisos de ajuste; o Plano 6 pendura as contas a receber aqui). `Fornecedor` fica em `cadastros` (RF-CAD-05, clientes virão ao lado). `ConsumoPendente` fica em `estoque`; a produção passa a aceitá-lo. Toda escrita passa por `nucleo.operacoes.executar()`; cada evento (aprovação, recebimento, pagamento, estorno) é uma operação própria (RN-04). Consultas são funções puras em `compras/consultas.py`, `financeiro/consultas.py` e `estoque/servicos.py`, reutilizadas por telas (fase 2a) e agente (fase 2b).

**Tech Stack:** Python 3.12, uv, Django 5.2, SQLite, pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-10-19-agente-cozinha-design.md` (§3, §6.2, §6.6, §6.7). Regras em `docs/prd/02-prd.md`: RF-CAD-05/07, RF-CMP-01/08/10/12/13/15, RF-REC-01 a 08, RF-EST-04/06/07, RF-FIN-01/03/04/07/08/09/10, RN-03/04/05/06/07/08/09/20/21/23/25/31/32/34/40, CA-06/09/10/11/12/19/36/38/39/41/42, FL-02, FL-08, FL-09, FL-10; decisões DEC-F2-005/006/007/008/010/024/025/027/029/033/036/037/038/039/044. Pendências do Plano 2: `docs/superpowers/plans/2026-10-19-plano-2-pendencias.md` (consumo pendente e conciliação).

## Divisão do plano

| Fase | Quem | Entrega | Situação |
|---|---|---|---|
| **1 — Núcleo** | esta sessão | modelos, migrações, serviços sobre `executar()`, consultas, admin, testes | **feita** (Tasks 1–7) |
| **2a — Telas** | sessão paralela, só `web/` | formulários e consultas da web (Tasks 8–12) | a fazer |
| **2b — Ferramentas MCP** | sessão paralela, só `agente/` | ferramentas, propostas, documentação (Tasks 13–15) | a fazer |

As fases 2a e 2b não mexem em modelo nem em serviço; se precisarem de algo do núcleo, pedem à coordenação. O contrato estável está no fim deste documento.

## Decisões deste plano (revisáveis pelo dono)

| Decisão | Por quê / custo se estiver errada |
|---|---|
| **Lançar e aprovar a compra são uma operação só** (`registrar_compra`). A compra nasce "aprovada" e a conta nasce junto. Não existe rascunho de compra manual. | PRD §11: a compra começa em "aprovada"; rascunho/revisão é da importação (Plano 5), que vai criar a compra por este mesmo serviço. O agente já tem a "proposta" (nível 2) como rascunho. |
| **Recebimento é sempre um evento separado** (`receber_compra`), mesmo que a tela faça os dois de uma vez. | RN-04, CA-10. A tela pode chamar os dois em sequência. |
| Quantidade do recebimento vem **na unidade da compra** por padrão (pode mandar outra, convertida). | O dono conta "8 sacos" do jeito que comprou. |
| **Cada recebimento de linha cria um lote novo** com o custo unitário da linha (RN-21), mesmo que seja complementar. | RF-REC-03; o lote do fornecedor pode ser outro. |
| **Custo unitário guardado com 4 casas por unidade base** (por g, mL ou un), como o `Lote` já faz. | DEC-F2-047 fixa 4 casas. Em itens por grama há perda de centavos (ex.: R$ 23,90 por 5 kg vira R$ 0,0048/g → R$ 24,00 no lote). Ver pendências. |
| Frete, desconto e acréscimo **rateados pelo valor da linha** (RN-20). Divergência entre a soma e o total do documento **exige justificativa**; a conta é **pelo total do documento** (DEC-F2-006). | CA-09, CA-12. |
| **Duplicata:** mesmo número de documento + fornecedor **bloqueia**; mesmo fornecedor + data + total só **alerta** (devolvido em `alertas`). Compra cancelada não conta. | RN-05 (c) e (d), DEC-F2-039. Os casos (a) e (b) (hash do arquivo, mensagem) são do Plano 5. |
| **Total zero é recusado**; mercadoria sem cobrança entra por `receber_bonificacao` (lote a custo zero). | DEC-F2-038. |
| Item do tipo **produto** não pode ser comprado; item ou fornecedor **inativo** é recusado. | Produto é feito aqui (Plano 2); RF-CAD-07. |
| **À vista:** a conta nasce com 1 parcela já paga (data = `data_pagamento` ou a data da compra; forma opcional). **A prazo:** parcelas informadas; a soma tem de bater com o total (RN-32). `dividir_parcelas()` sugere parcelas iguais (centavos na última). | DEC-F2-006, DEC-F2-024. |
| **Situação e saldo da parcela são derivados** dos pagamentos não estornados: aberta, parcial, paga, cancelada; "vencida" à parte. Nada guarda saldo. | RF-FIN-07, RN-31; o estorno "volta ao estado anterior" sozinho. |
| **Pagamento é anotação.** `valor` = quanto abate da parcela; `diferenca` + tipo (juros, multa, desconto) + motivo registram o que saiu do bolso a mais ou a menos. Não se paga acima do saldo. | O sistema nunca paga (design §3); DEC-F2-025. |
| **Estorno marca o original** (`estorno_operacao`, `motivo_estorno`) sem mudar os valores; recebimento estornado também gera um movimento de saída "estorno_recebimento". | DEC-F2-027, RN-34: nada é apagado; a operação de estorno fica na trilha. |
| **Não entregue** e **devolução ao fornecedor** criam um `AvisoAjuste` na conta; o valor devido **não muda**. O dono resolve o aviso dizendo o que fez (ex.: "abateu no boleto"), e o abatimento real entra como desconto no pagamento. | RN-09, DEC-F2-007, DEC-F2-036. |
| **Cancelar compra** só sem recebimento e sem pagamento (estornar antes). Cancela a conta junto. | DEC-F2-037, RF-CMP-15. |
| **Consumo pendente** (feito neste plano, era pendência do Plano 2): `iniciar_producao` e `concluir_producao` aceitam `pendente_justificativa`. O que faltar vira `ConsumoPendente`, **sem movimento** (o estoque nunca fica negativo) e a produção fica com `custo_pendente`. `conciliar_consumo` baixa do lote escolhido, fecha o custo da produção e atualiza o custo do lote produzido **uma única vez** por pendência. | DEC-F2-005/033, CA-19, RN-25 (a). O recebimento devolve `conciliaveis` (RF-EST-07); confirmar é nível 2 do agente. |
| Consultas devolvem **Decimal e date**; os serviços devolvem o dict do `executar()` (já em JSON: Decimal vira texto, ex.: `"100.00"`). | Mesmo padrão dos serviços existentes. |
| Os serviços aceitam números e datas **como texto** (`"25.50"`, `"2026-11-10"`) além de Decimal/date (`nucleo/valores.py`). | Uma proposta do agente é reexecutada a partir de JSON; listas aninhadas (linhas, parcelas) não precisam de conversão na camada do agente. |
| O admin mostra compras, contas, pagamentos, avisos e consumos pendentes **só para leitura**; fornecedor é cadastrado no admin **pelo núcleo** (`AdminViaExecutar`). | Compra e pagamento têm regras que o admin não aplica. |

## Global Constraints

- Tudo dos Planos 1 e 2 continua valendo: Decimal sempre; quantidade 3 casas, custo unitário 4 casas, dinheiro 2 casas, `ROUND_HALF_UP`; unidade base `g`, `mL` ou `un`; conversões só pelo `cadastros.unidades.fator` (RN-40); sem fator, recusa.
- **Toda gravação passa por `executar()`**; o resultado só é sucesso depois de gravado (RN-39). Recebimento é atômico: todas as linhas ou nenhuma (RN-08).
- Só o recebido entra no estoque; a compra guarda o documentado; a pendência não é disponível (RN-03, RN-07).
- Nada é apagado nem editado: estorno, encerramento e aviso são registros novos ou marcas, sempre com motivo (RN-34).
- O valor devido nunca é recalculado sozinho (RN-09).
- Nenhuma conta de dinheiro, quantidade ou custo fora dos serviços e consultas do núcleo (design A3).
- Mensagens em pt-BR; dinheiro formatado por `web.templatetags.formato.dinheiro` ("R$ 1.234,56"), quantidades por `quantidade`.

## Review Focus

- Compra com frete e desconto → custo por unidade base igual ao CA-12; recebimento parcial não muda o custo unitário (`test_custo_unitario_com_rateio_de_frete_e_desconto`).
- Receber mais do que o documentado, inclusive a mesma linha duas vezes na mesma chamada → recusado sem gravar nada (`test_excesso_recusado_e_bonificacao_a_custo_zero`).
- Aprovar ou receber duas vezes com a mesma chave → uma compra, uma conta, um movimento (`test_idempotencia_por_chave`).
- Parcelas que não somam o total → nada da compra é gravado (`test_parcelas_precisam_somar_o_total`).
- Pagar acima do saldo, pagar parcela paga, estornar duas vezes → recusados (`test_contas_pagar.py`).
- Estornar recebimento de lote já usado → recusado (`test_estorno_recusado_se_lote_ja_foi_usado`).
- Produção sem estoque e sem justificativa → continua recusando como no Plano 2 (`test_sem_justificativa_continua_recusando`).

---

## Fase 1 — Núcleo (feita)

### Task 1: Fornecedor

**Files:** `cadastros/models.py`, `cadastros/servicos.py`, `cadastros/admin.py`, migração `cadastros/0004_fornecedor.py`. Test: `tests/test_compras.py::test_fornecedor_nome_unico_e_admin_pelo_nucleo`.

- [x] `Fornecedor(nome único, documento opcional, contato opcional, ativo)`.
- [x] `salvar_fornecedor(...)` cria ou altera; nome repetido (sem diferenciar maiúsculas) é recusado.
- [x] Admin pelo núcleo (`AdminViaExecutar`).

### Task 2: Compra aprovada e conta a pagar

**Files:** `compras/models.py`, `compras/servicos.py`, `financeiro/models.py`, `financeiro/servicos.py`, `nucleo/valores.py`, `web/templatetags/formato.py` (filtro `dinheiro`), migrações iniciais. Test: `tests/test_compras.py`.

- [x] `Compra`, `LinhaCompra` (quantidade como veio + fator + quantidade base + valor + custo unitário), `Conta`, `Parcela`, `Pagamento`.
- [x] `registrar_compra`: validações, conversão, rateio (RN-20), divergência com justificativa, duplicatas, conta à vista ou a prazo.
- [x] Testes: CA-06, CA-09, CA-12, parcelas, à vista, recusas, duplicatas, idempotência.

### Task 3: Recebimento, pendência, bonificação, devolução, estorno, cancelamento

**Files:** `compras/servicos.py`, `financeiro/models.py` (`AvisoAjuste`). Test: `tests/test_compras.py`.

- [x] `receber_compra` (parcial, complementar, recusa de excesso, validade obrigatória quando o item controla), lote novo por linha, `conciliaveis`.
- [x] `encerrar_pendencia` com aviso de ajuste; `receber_bonificacao`; `devolver_ao_fornecedor` com aviso; `estornar_recebimento`; `cancelar_compra`.
- [x] Status da compra recalculado a cada evento: aprovada → parcial → recebida; encerrada com pendência; cancelada.
- [x] Testes: CA-10 (caminho feliz até pagar), CA-39, CA-41, CA-42, estornos, cancelamento.

### Task 4: Pagamentos, estorno e avisos

**Files:** `financeiro/servicos.py`. Test: `tests/test_contas_pagar.py`.

- [x] `registrar_pagamento` (total ou parcial, diferença classificada), `estornar_pagamento`, `resolver_aviso`, `dividir_parcelas`.
- [x] Testes: CA-36, CA-38, desconto/multa, idempotência, valores como texto.

### Task 5: Consultas

**Files:** `compras/consultas.py`, `financeiro/consultas.py`, `estoque/servicos.py` (`consumos_pendentes`).

- [x] Compras em aberto, falta receber (com idade), detalhe da compra, possíveis duplicatas, último custo (RN-23).
- [x] Parcelas em aberto, vencidas, a vencer, devido por fornecedor, detalhe da conta, pagamentos por período, avisos.

### Task 6: Consumo pendente e conciliação

**Files:** `estoque/models.py` (`ConsumoPendente`), `estoque/servicos.py` (`alocar_fefo_parcial`), `producao/models.py` (`pendente_justificativa`, `custo_pendente`), `producao/servicos.py` (`iniciar_producao`, `concluir_producao`, `conciliar_consumo`, `origem`). Test: `tests/test_consumo_pendente.py`.

- [x] Produção começa e conclui com falta só com justificativa; o que falta vira pendência, sem estoque negativo.
- [x] Recebimento propõe; `conciliar_consumo` baixa, fecha custo da produção e do lote, uma vez só; rastreio (`origem`) inclui o lote conciliado.

### Task 7: Admin e fechamento da fase

- [x] Compras, recebimentos, contas, parcelas, pagamentos, avisos e consumos pendentes no admin, só leitura.
- [x] `uv run pytest` verde (211); `makemigrations --check` sem mudanças.

---

## Fase 2a — Telas (`web/`)

Padrão das telas existentes: templates Django, login obrigatório, `{% chave %}` em todo formulário de POST (idempotência), `DecimalBR` nos campos decimais, erros `RegraViolada` mostrados no formulário sem perder o que foi digitado, botões de 44 px, sem rolagem horizontal a 360 px. A tela nunca calcula: rateio, saldos, situação e totais vêm das consultas.

### Task 8: Fornecedores
- [ ] Lista com busca e ativo/inativo; formulário novo/editar → `salvar_fornecedor`.
- [ ] Test: criar, editar, nome repetido mostra a mensagem.

### Task 9: Lançar compra
- [ ] Formulário: fornecedor, data, documento, linhas dinâmicas (item, quantidade, unidade com as conversões do item, valor), frete, desconto, acréscimo, total, condição (à vista: forma e data; a prazo: nº de parcelas + primeiro vencimento → `dividir_parcelas` preenche as linhas, editáveis).
- [ ] Antes de enviar, mostrar `possiveis_duplicatas` e a diferença entre soma e total (a tela pode exibir a soma, mas quem decide é o serviço: a recusa vem como mensagem).
- [ ] Opção "recebi tudo agora": depois de `registrar_compra`, chama `receber_compra` com todas as linhas pelo documentado (dois eventos).
- [ ] Mostrar `alertas` do resultado.
- [ ] Test: compra a prazo, divergência sem justificativa mostra a mensagem, duplo envio cria uma compra.

### Task 10: Compra e recebimento
- [ ] Detalhe da compra (`detalhe_compra`): linhas com documentado, recebido, pendente, custo; recebimentos com lote; conta com parcelas, pagamentos e avisos.
- [ ] Formulário de recebimento por linha (quantidade na unidade da compra, código do lote, validade quando o item controla) → `receber_compra`; se vier `conciliaveis`, oferecer "usar este lote para o consumo pendente" → `conciliar_consumo`.
- [ ] Botões com motivo: encerrar pendência, estornar recebimento, cancelar compra, devolver ao fornecedor (na tela do lote), bonificação.
- [ ] Lista "Falta receber" (`falta_receber`) com idade da pendência e "Compras em aberto".

### Task 11: Contas a pagar
- [ ] Lista: vencidas, a vencer (7 dias), demais em aberto; total devido por fornecedor (`devido_por_fornecedor`).
- [ ] "Paguei": valor (padrão: saldo), data, forma, diferença opcional com tipo e motivo → `registrar_pagamento`; estornar com motivo → `estornar_pagamento`.
- [ ] Avisos de ajuste abertos com "resolver" → `resolver_aviso`.
- [ ] Pagamentos por período (`pagamentos`).

### Task 12: Consumo pendente e "Hoje"
- [ ] Produção nova: quando falta estoque, mostrar a falta e oferecer "começar mesmo assim" com justificativa (`pendente_justificativa`).
- [ ] Lista de consumos pendentes com os lotes possíveis → `conciliar_consumo`; produção com custo pendente rotulada "custo pendente".
- [ ] Página inicial / "Hoje": contas vencidas e a vencer, falta receber, consumos pendentes, avisos de ajuste.

---

## Fase 2b — Ferramentas MCP (`agente/`)

Padrão de `agente/ferramentas.py`: nomes falados resolvidos por `consultas.escolher` (fornecedor, item, compra pelo fornecedor e data), nível 0 consulta, 1 faz e repete, 2 cria `Proposta` simulada e espera o "sim". Quantidades com `texto` falado, dinheiro com texto "R$ 12,50". Registrar cada operação nova em `agente.propostas.OPERACOES` (os serviços já aceitam números e datas como texto, inclusive dentro de `linhas` e `parcelas`; `decimais`/`datas` só precisam ser listados para os parâmetros de topo, se a ferramenta mandar Decimal).

### Task 13: Consultas (nível 0)
- [x] `ver_compras_em_aberto`, `ver_falta_receber`, `ver_compra`, `ver_contas` (vencidas e a vencer), `ver_divida_fornecedores`, `ver_consumos_pendentes`, `ver_avisos_de_ajuste`, `buscar_fornecedores`, `ultimo_preco`.

### Task 14: Escrita (nível 1 e 2)
- [x] Ferramentas da tabela de alçada abaixo, cada uma montando o resumo falado a partir do resultado da simulação (`alertas` de duplicata entram no "Confirma?").
- [x] Testes no padrão de `tests/test_mcp_agente_escrita.py`: proposta não grava; confirmar grava uma vez; confirmar duas vezes não duplica.

### Task 15: Documentação e skill
- [x] `docs/agente-mcp.md`: tabela de ferramentas e exemplos ("comprei 10 kg de farinha no Atacadão por 60 reais, a prazo para dia 30").
- [ ] Contas a vencer no resumo da manhã quando a fila de tarefas existir (design §6.7; Plano 4).

---

## Fora deste plano

- Importação de cupom, fila de revisão, sinônimos, Telegram (RF-CMP-02 a 07, 09, 11, 14; RN-05 a/b; RN-10/11) — Plano 5. A importação aprovada chama `registrar_compra`.
- Despesas avulsas e recorrentes, categorias de custo (RF-FIN-02/05, RN-37) — Plano 7. O modelo `Conta` já tem `origem` e `fornecedor` opcional.
- Contas a receber (RF-FIN-06) — Plano 6, reaproveitando `Parcela`/`Pagamento`.
- Inventário e ajuste avulso de estoque (RF-EST-08/09), que também podem conciliar pendente (DEC-F2-041) — plano de estoque.
- Exportação CSV (RF-REL-04).

## Perguntas em aberto para o dono (com o padrão adotado)

| # | Pergunta | Padrão adotado até a resposta |
|---|---|---|
| Q1 | Quando você diz ao agente "paguei o boleto do Atacadão", ele deve anotar na hora ou repetir e esperar seu "sim"? O design (§6.2) diz "na hora"; a coordenação pediu que tudo que tem valor em dinheiro espere o "sim". | **Espera o "sim"** (nível 2). Mudar para nível 1 é configuração da ferramenta. |
| Q2 | Fornecedor precisa de CNPJ/CPF e contato, ou só o nome basta? | Só o nome é obrigatório. |
| Q3 | Ao pagar à vista, a forma de pagamento (pix, dinheiro, cartão) precisa ser informada? | Opcional. |
| Q4 | Pagar uma parcela com valor **maior** que o saldo (ex.: adiantar a próxima) deve ser aceito? | Recusado; o que passar vira juros/multa ou vai para a próxima parcela em outro lançamento. |
| Q5 | Pode receber mercadoria já vencida (ex.: lote com validade de ontem)? | Aceita; o lote vencido fica indisponível como qualquer outro (RN-19). |
| Q6 | Depois de lançada, dá para mudar as parcelas (ex.: o fornecedor trocou o vencimento)? | Não neste plano: cancela a compra (se nada foi recebido nem pago) e lança de novo. |
| Q7 | Comprar algo que também produzimos (ex.: salgado de outro fornecedor para revender)? | Recusado: só ingrediente, insumo e embalagem são comprados. |
| Q8 | Ao conciliar um consumo pendente, o lote proposto deve cobrir a quantidade toda, ou pode juntar dois lotes? | Um lote só, que cubra tudo. |
| Q9 | A data em que você pagou pode ser no futuro (agendamento)? | Aceita a data que vier; sem data, hoje. |

## Contrato para a fase 2

Todos os serviços: argumentos **keyword-only**, terminando em `autor`, `canal="web"`, `chave=None`; gravam por `executar()` (idempotentes por `chave`); devolvem o dict do `executar()` (Decimal e data viram texto); recusas levantam `nucleo.operacoes.RegraViolada` com mensagem em pt-BR para mostrar ao dono. Números e datas podem vir como Decimal/date ou texto (`"10.5"`, `"2026-11-30"`). Consultas não gravam e devolvem Decimal/date.

### Serviços

| Serviço | Parâmetros | Retorno | Recusas principais |
|---|---|---|---|
| `cadastros.servicos.salvar_fornecedor` | `nome`, `documento=""`, `contato=""`, `ativo=True`, `fornecedor_id=None` (None cria) | `{fornecedor_id, nome}` | nome vazio; nome repetido; não encontrado |
| `compras.servicos.registrar_compra` | `fornecedor_id`, `data_compra`, `linhas=[{item_id, quantidade, unidade, valor}]`, `total`, `condicao` ("a_vista"/"a_prazo"), `parcelas=[{valor, vencimento}]` (a prazo), `data_pagamento=None`, `forma_pagamento=""` (à vista), `frete=0`, `desconto=0`, `acrescimo=0`, `documento=""`, `justificativa=""` | `{compra_id, conta_id, total, alertas: [str], linhas: [{linha_id, item, quantidade_base, custo_unitario}]}` | fornecedor inexistente/inativo; item inexistente/inativo/produto; sem fator de conversão; quantidade ≤ 0; total ≤ 0; soma ≠ total sem justificativa; documento já lançado; parcelas ≠ total; condição inválida |
| `compras.servicos.receber_compra` | `compra_id`, `linhas=[{linha_id, quantidade, unidade=<da compra>, lote_codigo="", validade=None}]` | `{compra_id, status, recebimentos: [{recebimento_id, linha_id, lote_id, quantidade_base}], conciliaveis: [{pendente_id, item, quantidade, lote_id, producao_id}]}` | compra não aberta; linha de outra compra; excesso ("só faltam receber X…"); validade obrigatória; sem fator |
| `compras.servicos.encerrar_pendencia` | `compra_id`, `motivo`, `linha_ids=None` (todas) | `{compra_id, status, aviso_id, linhas: [{linha_id, encerrado}]}` | sem motivo; sem pendência; compra não aberta |
| `compras.servicos.estornar_recebimento` | `recebimento_id`, `motivo` | `{recebimento_id, compra_id, status}` | sem motivo; já estornado; lote já usado |
| `compras.servicos.devolver_ao_fornecedor` | `lote_id`, `quantidade`, `motivo`, `unidade=None` (base) | `{lote_id, quantidade_base, saldo_lote, aviso_id}` | sem motivo; lote não veio de compra; acima do saldo |
| `compras.servicos.receber_bonificacao` | `item_id`, `quantidade`, `unidade`, `motivo`, `lote_codigo=""`, `validade=None`, `compra_id=None` | `{lote_id, quantidade_base, conciliaveis}` | sem motivo; item inválido; validade obrigatória |
| `compras.servicos.cancelar_compra` | `compra_id`, `motivo` | `{compra_id, conta_id}` | sem motivo; já cancelada; tem recebimento; tem pagamento |
| `financeiro.servicos.registrar_pagamento` | `parcela_id`, `valor=None` (saldo), `data_pagamento=None` (hoje), `forma=""`, `diferenca=0`, `diferenca_tipo=""` ("juros"/"multa"/"desconto"), `diferenca_motivo=""` | `{pagamento_id, parcela_id, valor, valor_pago, situacao, saldo}` | conta cancelada; parcela paga; valor ≤ 0 ou acima do saldo; diferença sem tipo/motivo; desconto ≥ valor |
| `financeiro.servicos.estornar_pagamento` | `pagamento_id`, `motivo` | `{pagamento_id, parcela_id, situacao, saldo}` | sem motivo; já estornado |
| `financeiro.servicos.resolver_aviso` | `aviso_id`, `observacao` | `{aviso_id}` | sem observação; já resolvido |
| `producao.servicos.iniciar_producao` | + `pendente_justificativa=""` | igual ao Plano 2 | sem justificativa e com falta: "Falta X de …" |
| `producao.servicos.concluir_producao` | + `pendente_justificativa=""` (ou a do início) | + `custo_pendente`, `pendentes: [{pendente_id, item, quantidade}]` | igual ao Plano 2 |
| `producao.servicos.conciliar_consumo` | `pendente_id`, `lote_id` | `{pendente_id, lote_id, custo, producao_id, custo_total, custo_pendente}` | já conciliado; lote de outro item; vencido; saldo insuficiente |

### Consultas (sem gravar)

| Consulta | Parâmetros | Retorno |
|---|---|---|
| `compras.consultas.compras_em_aberto` | `fornecedor_id=None` | `[{compra_id, fornecedor, data, total, status, dias, pendentes: [linha]}]` |
| `compras.consultas.falta_receber` | `compra_id=None`, `item_id=None` | `[linha + {compra_id, fornecedor}]` — linha: `{linha_id, item_id, item, unidade_base, quantidade, unidade, fator, documentado, recebido, encerrado, pendente, motivo_encerramento, valor, custo_unitario, dias}` |
| `compras.consultas.detalhe_compra` | `compra_id` | cabeçalho, `soma_itens`, quem aprovou e quando, `linhas` com `recebimentos`, `conta` (= `detalhe_conta`); `None` se não existe |
| `compras.consultas.possiveis_duplicatas` | `fornecedor_id`, `data_compra`, `total`, `documento=""` | `[{compra_id, data, total, documento, bloqueia}]` |
| `compras.consultas.ultimo_custo` | `item_id` | `{custo_unitario, compra_id, data, fornecedor}` ou `None` (RN-23) |
| `compras.servicos.pendente_linha` / `recebido_linha` / `custos_das_linhas` | linha / linha / `[(valor, quantidade_base)]`, `frete`, `desconto`, `acrescimo` | Decimal / Decimal / `[Decimal]` (prévia do custo) |
| `financeiro.consultas.parcelas_em_aberto` | `ate=None`, `fornecedor_id=None`, `hoje=None` | `[{parcela_id, conta_id, compra_id, fornecedor_id, fornecedor, descricao, numero, de, valor, pago, saldo, vencimento, dias, situacao, vencida}]` por vencimento |
| `financeiro.consultas.contas_vencidas` | `hoje=None` | igual, só vencidas |
| `financeiro.consultas.contas_a_vencer` | `dias=7`, `hoje=None` | igual, de hoje até hoje+dias, não vencidas |
| `financeiro.consultas.devido_por_fornecedor` | `hoje=None` | `[{fornecedor_id, fornecedor, devido, vencido, parcelas}]` do maior para o menor |
| `financeiro.consultas.detalhe_conta` | `conta` (objeto) | `{conta_id, descricao, total, cancelada, parcelas: [parcela + pagamentos], avisos}` |
| `financeiro.consultas.pagamentos` | `de=None`, `ate=None`, `fornecedor_id=None`, `incluir_estornados=False` | `[{pagamento_id, parcela_id, valor, valor_pago, data, forma, diferenca, diferenca_tipo, diferenca_motivo, estornado, motivo_estorno, fornecedor, descricao}]` |
| `financeiro.consultas.avisos_de_ajuste` | `abertos=True` | `[{aviso_id, conta_id, compra_id, texto, criado_em, resolvido, observacao}]` |
| `financeiro.servicos.dividir_parcelas` | `total`, `n`, `primeiro_vencimento`, `intervalo_dias=30` | `[{valor, vencimento}]` (soma = total) |
| `financeiro.servicos.saldo_parcela` / `situacao_parcela` / `vencida` | parcela | Decimal / "aberta"·"parcial"·"paga"·"cancelada" / bool |
| `estoque.servicos.consumos_pendentes` | `item_id=None`, `abertos=True` | `[{pendente_id, item_id, item, unidade_base, quantidade, justificativa, producao_id, criado_em, lote_id, custo, lotes_possiveis: [{lote_id, codigo, validade, saldo, custo_unitario}]}]` |

### Telas sugeridas (fase 2a)

Fornecedores · Nova compra (com "recebi tudo agora") · Compra (detalhe + receber + encerrar/estornar/cancelar) · Falta receber · Contas a pagar (vencidas, a vencer, por fornecedor, "paguei", estorno) · Avisos de ajuste · Consumos pendentes (conciliar) · Ajustes em Produção nova (começar com falta) e em Hoje.

### Ferramentas MCP sugeridas (fase 2b)

| Ferramenta | Nível | Serviço / consulta |
|---|---|---|
| `buscar_fornecedores`, `ver_compras_em_aberto`, `ver_falta_receber`, `ver_compra`, `ver_contas`, `ver_divida_fornecedores`, `ver_avisos_de_ajuste`, `ver_consumos_pendentes`, `ultimo_preco` | 0 | consultas acima |
| `cadastrar_fornecedor` | 1 | `salvar_fornecedor` (sem valor em dinheiro) |
| `registrar_compra` | 2 | `registrar_compra` (dinheiro; mostra itens, total, condição e `alertas`) |
| `receber_compra` | 2 | `receber_compra` (entra no estoque com custo) |
| `encerrar_pendencia` | 2 | `encerrar_pendencia` (gera aviso sobre a conta) |
| `registrar_pagamento` | 2 | `registrar_pagamento` (dinheiro; ver Q1) |
| `estornar_pagamento`, `estornar_recebimento`, `cancelar_compra` | 2 | correções de dinheiro/estoque |
| `devolver_ao_fornecedor`, `receber_bonificacao` | 2 | baixa/entrada com efeito na conta ou no custo |
| `conciliar_consumo` | 2 | design §6.2: conciliação espera o "ok" |
| `resolver_aviso` | 1 | só anota o que o dono disse |
