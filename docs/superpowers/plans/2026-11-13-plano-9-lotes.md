# Plano 9 — Lotes na operação: de qual lote pegar, lote indicado, vencido com motivo e conferência — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoje a venda e a produção baixam o estoque pelo que vence primeiro (FEFO) **sem dizer de onde**: o atendente pega um pacote qualquer, o sistema baixa outro, e o estoque do lote deixa de bater com a prateleira. E o vencido é uma trava dura em seis lugares. O dono quer o contrário: o sistema **diz de qual lote pegar** antes de fechar a venda ("30 coxinhas: 18 do lote do dia 8, que vence amanhã, e 12 do lote do dia 10; o do dia 8 zera e no do dia 10 sobram 28"), o atendente **confirma ou indica outro lote**, e o sistema registra o lote verdadeiro. Lote vencido deixa de ser trava: vira **aviso com motivo** (o sistema avisa, exige um motivo, deixa seguir e audita). Venda registrada depois vale pela **data em que aconteceu**. E, quando um lote vence com saldo, o sistema **pergunta se ele ainda está lá** (já foi vendido / está aqui / não sei).

**Architecture:** Nada de app novo. `estoque/lotes.py` (novo): o nome falável do lote (`nome_lote`, "lote do dia 8") e a regra única do vencido (`checar_vencido`). `vendas/lotes.py` (novo): o `Separador` — a mesma alocação para a consulta de separação (não grava) e para a venda/entrega (grava) — mais `separacao_venda`, `separacao_encomenda` e `lotes_deixados`. `estoque/servicos.py` ganha `ajustar_contagem` e o `destino` da perda. Os serviços que recusavam vencido (`registrar_venda`, `entregar_encomenda`, `cancelar_venda`, `registrar_fritura`, `transferir_estado`, `concluir_producao`, `conciliar_consumo`) ganham `motivo_vencido` (opcional). Caixa de decisões: o gerador `lotes_vencidos` vira a conferência; gerador novo `lotes_deixados`. Migrações pequenas, só colunas com padrão: `Movimento.motivo_vencido`, `Movimento.destino`, `LinhaVenda.lotes_indicados`, `LinhaVenda.deixados`.

**Tech Stack:** Python 3.12, uv, Django 5.2, SQLite, pytest + pytest-django.

**Spec:** PRD `docs/prd/02-prd.md`: RN-18 (FEFO por porção), RN-19 (vencido), RN-35/36 (reserva, devolução), RF-EST-02/10 (perda/descarte), RF-FRI-01, FL-04 E1, FL-06/07/09. Planos 2 (lotes e etiquetas), 6 (vendas) e 7 (decisões).

## Decisões do dono que este plano segue (conversa de 2026-11-13)

1. O sistema **diz de qual lote pegar** antes de fechar a venda, em **unidades por lote** (pacotes têm quantidade variável; cada pacote tem a etiqueta do lote).
2. O atendente **confirma ou indica outro lote**; o sistema registra o lote verdadeiro. Pegou lote mais novo deixando um que vence antes: **avisa, não trava**, e o alerta reaparece no resumo.
3. Lote vencido: **aviso com motivo** — avisa, exige motivo, deixa seguir, tudo auditado. O dono teme sistema rígido; quer decisões revisáveis, não regras duras.
4. Venda registrada depois **vale pela data em que aconteceu**: lote válido em `data_venda` baixa normalmente, sem motivo.
5. No vencimento, **conferência**: "já foram vendidas" (venda com a data real), "estão aqui" (destino com motivo: descarte, consumo da equipe...), "não sei" (contagem).
6. **Continuam travados**: saldo negativo, reserva de encomenda saindo em outra venda, histórico imutável.
7. Etiqueta com o **dia da produção em destaque**; a fala é "lote do dia 8", não o código.

## Divisão do plano

| Fase | Quem | Entrega | Situação |
|---|---|---|---|
| **1 — Núcleo** | esta sessão | nome falável, separação, lote indicado, vencido com motivo, data passada, conferência, contagem, destino da perda, etiqueta, geradores, resumo, migrações, testes | **feita** (Tasks 1–8) |
| **2a — Telas** | sessão paralela, só `web/` | separação no balcão e na entrega, "pegar de outro lote", motivo do vencido nas telas que hoje recusam, conferência na caixa, contagem, etiqueta com o dia (Tasks 9–14) | a fazer |
| **2b — Ferramentas MCP** | sessão paralela, só `agente/` | "de onde pego?", venda/entrega com lote indicado, motivo do vencido, conferência por voz, contagem (Tasks 15–18) | a fazer |

As fases 2a e 2b não mexem em modelo, serviço nem consulta; se precisarem de algo do núcleo, pedem à coordenação. O contrato estável está no fim deste documento.

## Decisões deste plano (revisáveis pelo dono)

| Decisão | Por quê / custo se estiver errada |
|---|---|
| **"Dia do lote" = dia em que o lote foi criado** (`Lote.criado_em` no fuso da cozinha): produção concluída, fritura, entrada manual/compra. É o mesmo dia da "fabricação" que a etiqueta já imprime. | Não existe outro "dia da produção" gravado. Produção iniciada num dia e concluída no outro fica com o dia da conclusão (é quando o lote nasce). |
| **Nome falável**: "lote do dia 8"; de outro mês, "lote do dia 28 de outubro" (de outro ano, "... de 2025"); segundo lote do mesmo item **e forma** no mesmo dia, "segundo lote do dia 8". | Curto para falar; o mês só aparece quando "dia 28" poderia ser deste mês. Cru e frito do mesmo dia não se confundem (a forma vem junto na fala). |
| **Uma alocação só** (`Separador`) para a consulta e para a venda: a tela/agente mostra exatamente o que a venda vai baixar. A venda aloca todas as linhas antes de gravar. | Sem isso, a instrução e a baixa poderiam divergir (era o problema). |
| **Lote indicado parcial completa por FEFO**: `lotes` somando menos que o item → o resto sai pelo FEFO; somando mais → recusa. | Atendente/agente pode dizer só "10 do lote do dia 10" sem calcular o resto. O retorno mostra a alocação final. |
| **FEFO automático nunca pega vencido** (no dia da venda). Vencido só sai **indicado + `motivo_vencido`** (venda/entrega) ou no lote **escolhido + motivo** (fritura, transferência, devolução, ingrediente fixado na pesagem). | Regra do dono: o vencido não some do estoque sem alguém decidir e dizer por quê. |
| **Sem motivo, a recusa continua**, mas a mensagem diz o lote ("lote do dia 8"), o dia em que venceu e que dá para seguir informando o motivo. As frases antigas que as telas e testes conferem foram mantidas dentro da nova ("só aceita descarte", "vencido não pode ser frito", "venceu: a devolução vai para perda", "Complete a reserva com outro lote"). | Telas no ar mostram a mensagem; nada quebra, e a mensagem passa a ensinar o caminho. |
| **Motivo gravado em três lugares**: `RegistroOperacao.parametros["motivo_vencido"]` (só quando informado), `Movimento.motivo_vencido` (só no movimento de porção vencida) e `LinhaVenda.baixas[].motivo_vencido`. `historico_operacoes` devolve `motivo_vencido`. | Auditoria completa sem tabela nova. Parâmetro vazio não entra em `parametros` (chaves de idempotência antigas continuam batendo). |
| **Transferência de vencido continua vencida**: com motivo, a porção nova fica com a validade antiga (não ganha validade do critério). | Senão congelar um vencido "ressuscitaria" o lote e o FEFO voltaria a vendê-lo sozinho. Pergunta Q3. |
| **Fritura de vencido com motivo**: o lote frito nasce com a validade do critério de frito (é um produto novo), e o motivo fica no consumo do cru. | Igual à fritura normal; o motivo explica de onde veio. Pergunta Q4. |
| **Ingrediente vencido na produção**: mesma regra — só o lote **fixado na pesagem** (`registrar_peso(lote_id=)`) e com `motivo_vencido` em `concluir_producao`; o resto sai por FEFO sem vencido. `conciliar_consumo` também aceita `motivo_vencido`. | Padrão sugerido pela coordenação; o ingrediente vencido nunca entra sozinho. Pergunta Q5. |
| **Data passada**: validade julgada em `data_venda`/`data_entrega`; **data futura recusada**; lote indicado feito **depois** do dia da venda recusado. No FEFO com data passada, lotes feitos depois daquele dia vão **para o fim** da fila (não são excluídos). | Excluir quebraria lançamentos antigos sem lote (e os testes de custos que vendem no passado com lote de hoje). Saldo e reserva continuam os de agora (não há "saldo naquele dia"). |
| **Lote deixado para trás**: a venda grava e devolve o aviso; a `LinhaVenda` guarda `lotes_indicados` e `deixados`. O gerador `lotes_deixados` lembra (assunto `lote_deixado:{lote}:{estado}`) **só enquanto** a porção tem saldo, **não entrou** na janela de validade (aí `lotes_vencendo`/`lotes_vencidos` assumem — sem aviso em dobro) e **nada saiu dela** depois daquela venda. | Uma situação, um aviso; some sozinho quando voltam a vender do lote certo. |
| **Entrega com lote indicado**: pode usar o reservado da própria encomenda; reservas cobertas pelo que saiu da porção delas viram "baixada", as outras são liberadas ("na entrega saiu de outro lote"). | Reserva é só intenção; o que vale é o que saiu. |
| **Conferência do vencido** = o gerador `lotes_vencidos` (mesmo assunto `lote_vencido:{lote}:{estado}`, mesmo começo de texto), agora perguntando "ainda estão aí?" e com as três respostas em `detalhes.conferencia`. Uma decisão por porção enquanto houver saldo (não repete por dia); some ao zerar. Para ingrediente, "já foram usadas" → contagem. | Reaproveita a caixa; decisões abertas no banco real continuam as mesmas (só o texto é atualizado). Pergunta Q1 (no dia seguinte ao último dia de validade). |
| **"Estão aqui" = `registrar_perda` com `destino`** (perda, descarte, consumo da equipe, doação). Todas continuam `Movimento.tipo="perda"` (entram nas perdas do relatório, com `destino` em cada linha). | Consumo da equipe também é custo que saiu sem venda; separado pelo `destino`, não some do relatório. Pergunta Q2. |
| **"Não sei" = `ajustar_contagem`**: informa o que há de fato; lança a diferença (`ajuste_contagem`), entrada com a validade e o custo da porção; achou menos que o reservado → libera as reservas mais novas até caber. Contagem igual: sem movimento (fica na trilha). | Saldo nunca negativo (contado ≥ 0); correção é lançamento novo. Não existia ajuste/inventário para reaproveitar. |

## Definições

- **Porção** = lote + conservação (fresco/resfriado/congelado). Validade da porção = `validade_porcao` (a da entrada mais antiga nela, ou a do lote).
- **Vencida em `quando`** = validade < `quando` (o último dia de validade ainda vale).
- **Livre** = saldo da porção − reservado para encomendas (+ o reservado da própria encomenda, na entrega) − o que já foi pego nesta venda.
- **Sobra** (na separação) = saldo da porção − o que esta venda pega dela (o reservado continua lá fisicamente).
- **Deixado para trás** = porção livre, válida e existente no dia da venda, que vence **antes** do lote mais novo que saiu na linha.

## Global Constraints

- Tudo dos Planos 1 a 8 continua valendo: Decimal sempre; toda gravação por `executar()`; nada é apagado (RN-34); correção é lançamento novo.
- **Continuam travados**: saldo negativo; reservado para encomenda saindo em outra venda (inclusive indicado); histórico imutável.
- Parâmetros novos são **opcionais**; sem eles, o comportamento é o de antes (FEFO, recusa do vencido).

## Review Focus

- Separação = baixa (`test_separacao_diz_de_qual_lote_pegar_e_quanto_sobra_sem_gravar`).
- Lote indicado, aviso e lembrete sem duplicar (`test_lote_indicado_deixa_o_mais_velho_para_tras_avisa_e_lembra_sem_duplicar`, `test_lote_deixado_some_quando_volta_a_sair_dele`, `test_lote_indicado_parcial_completa_por_fefo`, `test_lote_indicado_recusas`).
- Vencido com motivo em todos os pontos (`test_venda_de_vencido_so_indicado_e_com_motivo`, `test_entrega_com_lote_indicado_e_reserva_vencida_com_motivo`, `test_fritura_transferencia_e_devolucao_de_vencido_com_motivo`, `test_ingrediente_vencido_na_producao_so_escolhido_e_com_motivo`).
- Data passada (`test_venda_com_data_passada_julga_a_validade_naquele_dia`).
- Conferência nas três respostas e contagem (`test_conferencia_do_vencido_pergunta_uma_vez_e_as_tres_respostas`, `test_contagem_acha_mais_ou_menos_que_o_reservado`).

---

## Fase 1 — Núcleo (feita)

### Task 1: Modelos e migrações
**Files:** `estoque/models.py`, `estoque/migrations/0007_lotes_na_operacao.py`, `vendas/models.py`, `vendas/migrations/0004_lotes_na_operacao.py`.
- [x] `Movimento.motivo_vencido` (texto, padrão vazio) e `Movimento.destino` (perda/descarte/consumo_equipe/doacao, padrão vazio); `DESTINOS_PERDA`.
- [x] `LinhaVenda.lotes_indicados` (padrão falso) e `LinhaVenda.deixados` (JSON, padrão lista vazia). Só colunas novas com padrão: dados existentes intactos; reversível.

### Task 2: Nome falável e regra do vencido
**Files:** `estoque/lotes.py`, `estoque/etiquetas.py`.
- [x] `dia_producao`, `nome_lote`, `dados_lote`, `vencida`, `checar_vencido`, `texto_vencido`.
- [x] `dados_etiqueta` ganha `dia_producao` (número do dia, para destaque) e `nome_lote`; layout não mudou.

### Task 3: Separação (só leitura)
**Files:** `vendas/lotes.py`.
- [x] `Separador` (FEFO no dia da venda, sem vencido, sem reservado; lote indicado; deixados; texto).
- [x] `separacao_venda`, `separacao_encomenda`, `reservas_da_encomenda`, `dia_da_venda`.

### Task 4: Venda e entrega com lote indicado, data passada e vencido com motivo
**Files:** `vendas/servicos.py`.
- [x] `registrar_venda`: `itens[].lotes`, `motivo_vencido`; validade em `data_venda`; data futura recusada; aloca tudo antes de gravar; `avisos` e `data` no retorno; linhas com `lotes`, `lotes_indicados`, `deixados`.
- [x] `entregar_encomenda`: `lotes` por item, `motivo_vencido`, validade em `data_entrega`; reservas não usadas liberadas.
- [x] `cancelar_venda`: `motivo_vencido` para devolver vencido ao estoque.

### Task 5: Fritura, transferência, produção
**Files:** `producao/fritura.py`, `estoque/servicos.py`, `producao/servicos.py`.
- [x] `registrar_fritura`, `transferir_estado` (vencido continua vencido), `concluir_producao` (lote fixado), `conciliar_consumo`: `motivo_vencido`.

### Task 6: Conferência, perda com destino e contagem
**Files:** `estoque/servicos.py`, `decisoes/geradores.py`, `custos/relatorios.py`.
- [x] `registrar_perda(destino=)`; perdas do relatório com `destino`.
- [x] `ajustar_contagem`.
- [x] `lotes_vencidos` vira conferência (texto + `detalhes.conferencia`).

### Task 7: Lote deixado para trás no resumo e na caixa
**Files:** `vendas/lotes.py`, `decisoes/geradores.py`, `decisoes/consultas.py`.
- [x] `lotes_deixados`; gerador `lotes_deixados`; `resumo_do_dia()["validade"]["deixados"]` e `totais.lotes_deixados`; `historico_operacoes` com `motivo_vencido`; rótulo "Ajuste por contagem".

### Task 8: Testes e fechamento
**Files:** `tests/test_lotes_operacao.py`, `tests/test_etiquetas.py`.
- [x] 14 testes novos; `test_dados_etiqueta_iguais_ao_lote` ganhou as duas chaves novas; suíte inteira verde; `makemigrations --check` limpo.

---

## Fase 2a — Telas (`web/`)

### Task 9: Separação no balcão
- [ ] Na tela de venda, antes de "Fechar venda": chamar `separacao_venda` e mostrar, por item, a lista de lotes ("18 do lote do dia 8 — vence amanhã — zera"), os avisos (vence hoje/amanhã, falta, só vencido) e o texto. Botão "Confirmar" envia os mesmos itens (sem `lotes`: a venda baixa igual à separação).
- [ ] "Peguei de outro lote": por item, escolher lote(s) da mesma forma/conservação com unidades; mostrar de novo a separação com `lotes` (deixados e avisos). Vencido indicado → campo "motivo" obrigatório antes de confirmar (`precisa_motivo`).
- [ ] Depois de gravar, mostrar `avisos` da venda ("Ficaram 18 un do lote do dia 8...").

### Task 10: Separação na entrega de encomenda
- [ ] Mostrar `separacao_encomenda` (de quais lotes pegar a partir das reservas); "peguei de outro lote" envia `lotes` por `item_encomenda_id`; reserva vencida → motivo ou "completar reserva".

### Task 11: Motivo do vencido nas telas que hoje recusam
- [ ] Fritura, mudança de conservação, devolução ao estoque no cancelamento, conclusão da produção (ingrediente vencido fixado na pesagem): quando a recusa vier com "informe o motivo", mostrar o campo `motivo_vencido` e reenviar.

### Task 12: Conferência do vencido na caixa e no lote
- [ ] Na decisão `lotes_vencidos`, três botões a partir de `detalhes.conferencia`: "Já foram vendidas" (abre a venda com o lote indicado e a data), "Estão aqui" (destino + motivo → `registrar_perda`), "Não sei" (contagem → `ajustar_contagem`).
- [ ] Na tela do lote: "Contar" (`ajustar_contagem`) e destino na perda.

### Task 13: Lotes deixados
- [ ] Bloco "Venda primeiro" na tela Hoje a partir de `resumo_do_dia()["validade"]["deixados"]`; rótulo da origem `lotes_deixados` na caixa ("Lote deixado para trás").

### Task 14: Etiqueta e histórico
- [ ] Etiqueta com `dia_producao` em destaque (layout é da 2a); em listas de lote, usar `nome_lote`.
- [ ] Histórico de operações: mostrar `motivo_vencido` quando houver; perdas do relatório com `destino`.

## Fase 2b — Ferramentas MCP (`agente/`)

### Task 15: "De onde eu pego?" (nível 0)
- [ ] `ver_separacao(itens, data="hoje")` → `separacao_venda`; fala o `texto` de cada linha e os avisos.

### Task 16: Venda e entrega com lote indicado (com confirmação)
- [ ] `registrar_venda`/`entregar_encomenda` aceitam "peguei do lote do dia 10" → `lotes` (o agente resolve o nome pelo `nome` das linhas da separação; não calcula o resto, o núcleo completa por FEFO). Repetir o aviso de "deixado" depois de gravar.

### Task 17: Vencido com motivo (nível 2, confirmação)
- [ ] Onde a recusa pedir motivo, perguntar o motivo, repetir "o lote do dia 8 venceu em 12/11; vou registrar com o motivo X" e só então enviar `motivo_vencido`.

### Task 18: Conferência por voz e contagem
- [ ] Na caixa, a decisão `lotes_vencidos` vira pergunta: "já foram vendidas / estão aqui / não sei" → `registrar_venda(data_venda, lotes)`, `registrar_perda(destino, motivo)`, `ajustar_contagem(contado, motivo)`.
- [ ] Atualizar o texto do resumo que hoje diz "Vencido não pode ser usado" (agora: "vencido só sai com motivo").

---

## Fora deste plano (desenho pronto)

- **Saldo na data passada**: a venda com data passada usa o saldo e as reservas de agora. Reconstituir o saldo daquele dia (somando movimentos até a data) é possível, mas só muda algo se houve saída depois; fica para quando o dono lançar muita venda atrasada.
- **Conservação na data passada**: a porção é a de agora; se o lote mudou de conservação depois da venda, a venda atrasada precisa da porção atual. Rever se acontecer.
- **Conferência no dia do vencimento** (validade = hoje) em vez do dia seguinte: basta trocar o `ate` do gerador para `hoje` e tirar `dias == 0` de `lotes_vencendo`. Depende de Q1.
- **Contagem geral (inventário)**: `ajustar_contagem` é por porção; uma tela de inventário que conta tudo e chama o serviço por porção é da fase 2a se o dono pedir.

## Perguntas em aberto para o dono (com o padrão adotado)

| # | Pergunta | Padrão adotado até a resposta | Custo de estar errado |
|---|---|---|---|
| Q1 | A conferência ("ainda estão aí?") deve vir **no último dia de validade** ou **no dia seguinte**, quando já venceu? | **No dia seguinte** (já vencido). No último dia, o aviso "vence hoje" continua como antes. | Se o dono quiser no último dia, a pergunta chega um dia depois do que ele gostaria (troca simples, ver "Fora deste plano"). |
| Q2 | "Consumo da equipe" e "doação" devem entrar nas **perdas** do relatório? | **Sim**, como perdas com `destino` próprio (é mercadoria que saiu sem venda, com custo). | Se o dono quiser separar, a tela pode filtrar por `destino`; os números já estão separados. |
| Q3 | Mudar a conservação de um lote vencido (ex.: congelar) deve dar validade nova? | **Não**: com motivo, a mudança é aceita, mas o lote continua vencido. | Se ele quiser "salvar" lotes congelando, terá de indicar o lote e o motivo a cada venda. |
| Q4 | Fritar cru vencido (com motivo) gera frito com validade normal? | **Sim**, validade do critério de frito; o motivo fica no consumo do cru. | Frito de cru vencido entra no FEFO normal. |
| Q5 | Ingrediente vencido na produção: só com o lote escolhido na pesagem e com motivo? | **Sim** (mesma regra da venda). O FEFO da produção nunca pega vencido. | Quem usar ingrediente vencido sem marcar o lote na pesagem vai ver "falta" — e precisa escolher o lote. |
| Q6 | Na venda com data passada, o lote feito depois daquele dia pode ser usado? | **Indicado: não** (recusa). **FEFO: sim, por último** (para não travar lançamentos antigos). | Uma venda antiga sem lote pode baixar de um lote mais novo; o dono indica o lote se souber. |
| Q7 | O sistema deve **lembrar** do lote deixado para trás até quando? | Até sair algo dele, acabar, ou entrar no aviso de validade (3 dias). | Lembrete curto demais ou longo demais; troca de prazo é simples. |
| Q8 | Por voz, o agente pode registrar venda de vencido com motivo? | **Sim, com confirmação** repetindo o lote, o dia em que venceu e o motivo (nível 2). | Venda de vencido por engano: cancela-se a venda (destino perda). |

## Contrato para a fase 2

Consultas: argumentos **keyword-only**; **não gravam**; devolvem dicts com Decimal e date. Serviços: gravam por `executar()` (auditados, idempotentes por `chave`) e **devolvem o resultado já em JSON** (Decimal e date como texto). Recusas: `nucleo.operacoes.RegraViolada` com mensagem em pt-BR. Todos os parâmetros novos são **opcionais**.

### Nome do lote (para telas e agente falarem igual)

| Função | Parâmetros | Retorno |
|---|---|---|
| `estoque.lotes.nome_lote` | `lote`, `hoje=None` | `"lote do dia 8"` / `"lote do dia 28 de outubro"` / `"segundo lote do dia 8"` |
| `estoque.lotes.dados_lote` | `lote`, `hoje=None` | `{lote_id, codigo, dia_producao, nome}` |
| `estoque.lotes.dia_producao` | `lote` | `date` |
| `estoque.etiquetas.dados_etiqueta` | sem mudança | ganha `dia_producao` (int, o dia do mês, para destaque) e `nome_lote` |

### Consultas (sem gravar)

| Consulta | Parâmetros | Retorno | Recusas |
|---|---|---|---|
| `vendas.lotes.separacao_venda` | `itens=[{apresentacao_id, quantidade, lotes?: [{lote_id, unidades}]}]`, `data_venda=None`, `motivo_vencido=""`, `hoje=None` | `{data_venda, linhas: [L], avisos: [A], completo, precisa_motivo, texto}`. **L** = `{apresentacao_id, apresentacao, produto_id, produto, forma, estado, unidades, lotes: [{lote_id, codigo, nome, dia_producao, validade, vencido, unidades, sobra}], falta, lotes_indicados, deixados: [{lote_id, estado, unidades, validade, nome, usado_nesta_venda}], texto, avisos: [A]}`. **A** = `{tipo, texto, lote_id?, precisa_motivo?}`, `tipo` ∈ `vence_hoje`, `vence_amanha`, `deixado`, `falta`, `so_vencido`, `vencido_sem_motivo` | as da venda: "Informe ao menos um item."; "Item N: apresentação não encontrada."; quantidade; "A venda não pode ter data depois de hoje"; lote indicado (ver `registrar_venda`). Vencido indicado sem motivo **não** recusa: vira aviso `vencido_sem_motivo` e `precisa_motivo=True` |
| `vendas.lotes.separacao_encomenda` | `encomenda_id`, `data_entrega=None`, `lotes=None` ([{item_encomenda_id, lotes: [...]}]), `motivo_vencido=""`, `hoje=None` | `{encomenda_id, cliente, data_venda, linhas: [L + item_encomenda_id], avisos, completo, precisa_motivo, texto}` — sem `lotes`, a separação são as reservas; avisa reserva vencida (`vencido_sem_motivo`) e "Falta reservar" | "Encomenda não encontrada."; "Esta encomenda já está entregue/cancelada."; data futura |
| `vendas.lotes.lotes_deixados` | `hoje=None`, `dias_validade=3` | `[{lote_id, estado, item_id, item, codigo, nome, dia_producao, validade, saldo, livre, venda_id, data_venda}]` | — |
| `decisoes.consultas.resumo_do_dia` | sem mudança | `validade` ganha `deixados` (= `lotes_deixados`); `totais` ganha `lotes_deixados` | — |
| `decisoes.consultas.historico_operacoes` | sem mudança | cada operação ganha `motivo_vencido` ("" quando não houve) | — |
| `custos.relatorios.relatorio_periodo` | sem mudança | `perdas.movimentos[]` ganha `destino` (antigas: "perda") | — |

### Serviços

| Serviço | Parâmetros novos | Retorno novo | Recusas novas/alteradas |
|---|---|---|---|
| `vendas.servicos.registrar_venda` | `itens[].lotes=[{lote_id, unidades}]` (opcional; o que faltar sai por FEFO), `motivo_vencido=""` | ganha `data`, `avisos: [str]` (deixado, vence hoje/amanhã); cada linha ganha `lotes: [{lote_id, nome, estado, unidades, motivo_vencido}]`, `lotes_indicados`, `deixados` | "A venda não pode ter data depois de hoje (dd/mm)."; "O lote do dia D é de 'X', não de 'Y'."; "O lote do dia D de 'X' é frito; a apresentação é cru."; "O lote do dia D de 'X' foi feito em dd/mm, depois do dia da venda (dd/mm)."; "O lote do dia D de 'X' só tem N un em congelado."; "Do lote do dia D de 'X' só N un em congelado não estão reservadas para encomendas."; "Item N: os lotes indicados somam A un, mas o item pede B un."; "Item N: lote não encontrado."; "Item N: as unidades de cada lote devem ser maiores que zero."; vencido sem motivo: "O lote do dia D de 'X', congelado, venceu em dd/mm. Lote vencido só sai com um motivo: para vender dele mesmo assim, informe o motivo." |
| `vendas.servicos.entregar_encomenda` | `lotes=[{item_encomenda_id, lotes: [{lote_id, unidades}]}]`, `motivo_vencido=""`; `data_entrega` futura agora é recusada | ganha `avisos`; linhas como acima | "Os lotes indicados citam um item que não é desta encomenda."; reserva vencida sem motivo: "O lote do dia D de 'X', congelado, venceu em dd/mm. Complete a reserva com outro lote ou, para entregar dele mesmo assim, informe o motivo."; "O lote do dia D de 'X' não tem mais N un em congelado." |
| `vendas.servicos.cancelar_venda` | `motivo_vencido=""` (destino estoque com lote vencido) | — | "O lote do dia D de 'X' venceu: a devolução vai para perda (RN-36). Venceu em dd/mm; para voltar ao estoque mesmo assim, informe o motivo." |
| `producao.fritura.registrar_fritura` | `motivo_vencido=""` | — | "O lote do dia D de 'X', congelado, venceu em dd/mm. Lote vencido não pode ser frito sem um motivo: descarte ou, para fritar mesmo assim, informe o motivo." |
| `estoque.servicos.transferir_estado` | `motivo_vencido=""` (vencido continua vencido) | `validade` = a antiga quando vencido | "O lote do dia D de 'X', resfriado, venceu em dd/mm. Lote vencido só aceita descarte, a menos que se informe o motivo para mudar a conservação mesmo assim." |
| `producao.servicos.concluir_producao` | `motivo_vencido=""` (vale para o lote fixado em `registrar_peso`) | — | "O lote do dia D de 'Farinha' venceu em dd/mm. Lote vencido só sai com um motivo: para usar na produção mesmo assim, informe o motivo." |
| `producao.servicos.conciliar_consumo` | `motivo_vencido=""` | — | idem, "para consumir dele" (era "Lote vencido não pode ser consumido.") |
| `estoque.servicos.registrar_perda` | `destino="perda"` (`perda`, `descarte`, `consumo_equipe`, `doacao`) | ganha `destino` | "Destino inválido: use perda, descarte, consumo da equipe ou doação." |
| `estoque.servicos.ajustar_contagem` (novo) | `lote_id`, `estado=""`, `contado`, `motivo`, `autor`, `canal`, `chave` | `{lote_id, estado, item, unidade_base, antes, contado, diferenca, valor, reservas_liberadas: [id]}` | "Informe o motivo do ajuste (ex.: contagem do vencido)."; "A contagem não pode ser negativa."; "Lote não encontrado."; "Estado inválido." |

### Caixa de decisões

- `lotes_vencidos` (mesmo assunto `lote_vencido:{lote}:{estado}`): texto "X venceu em dd/mm: N un no lote COD, congelado (lote do dia D) constam no estoque. Ainda estão aí? Se já foram vendidas, registre com a data em que aconteceu; se estão aqui, diga o destino com o motivo (descarte, consumo da equipe...); se não sabe, conte e ajuste." `detalhes` ganha `nome`, `dia_producao` e `conferencia: {ja_saiu: {resposta, servico, como}, estao_aqui: {resposta, servico: "registrar_perda", como, parametros: {lote_id, estado, quantidade}}, nao_sei: {resposta, servico: "ajustar_contagem", como, parametros: {lote_id, estado}}}`. Para ingrediente, `ja_saiu.servico = "ajustar_contagem"`.
- `lotes_deixados` (novo; assunto `lote_deixado:{lote}:{estado}`; aviso): "Na venda V (dd/mm) o X saiu de um lote mais novo e ficaram N un do lote do dia D, congelado, que vence em dd/mm. Venda esse primeiro."

### Mudanças em retornos já existentes

- **Só acréscimos de chaves**, exceto: (1) o texto de `lotes_vencidos` mudou depois de "N no lote COD, estado" (a frase "Lote vencido só pode ser descartado." saiu; o começo "X venceu em dd/mm: N no lote COD" foi mantido); (2) mensagens de recusa do vencido ficaram mais longas (as frases antigas continuam dentro delas); (3) `entregar_encomenda` com `data_entrega` futura agora recusa; (4) `conciliar_consumo` com lote vencido não diz mais "Lote vencido não pode ser consumido."
- `dados_etiqueta` ganhou chaves (quem compara o dicionário inteiro precisa incluí-las).
- Os parâmetros gravados na trilha só ganham `motivo_vencido`, `lotes` ou `destino` quando informados: a mesma chamada de antes gera os mesmos parâmetros (idempotência por chave intacta).

### Telas sugeridas (fase 2a)

Separação no balcão com "peguei de outro lote" · Separação na entrega · Campo "motivo" onde a recusa pedir · Conferência do vencido (três botões) · Contar lote · Destino na perda · "Venda primeiro" (deixados) na tela Hoje · Etiqueta com o dia em destaque.

### Ferramentas MCP sugeridas (fase 2b)

| Ferramenta | Nível | Serviço / consulta | Por quê |
|---|---|---|---|
| `ver_separacao(itens, data="hoje")` | 0 | `separacao_venda` | "30 coxinhas, de onde eu pego?" — fala o `texto` e os avisos |
| `ver_separacao_encomenda(encomenda)` | 0 | `separacao_encomenda` | "a encomenda do João, de quais lotes?" |
| `registrar_venda(..., lotes)` | 1 | `registrar_venda` | "peguei do lote do dia 10" → `lotes` pelo `lote_id` da separação |
| `entregar_encomenda(..., lotes)` | 1 | `entregar_encomenda` | idem na entrega |
| `motivo_vencido` em venda, entrega, fritura, transferência, devolução | 2 | os serviços acima | só depois de repetir lote + dia do vencimento + motivo e ouvir "confirmo" |
| `conferir_vencido(decisao, resposta, ...)` | 1/2 | `registrar_venda` / `registrar_perda` / `ajustar_contagem` | as três respostas da conferência |
| `contar_lote(lote, contado, motivo)` | 1 | `ajustar_contagem` | "contei, tem 12" |

### O que o agente de voz passa a poder dizer

- **De qual lote pegar**, em unidades por lote, com "vence hoje/amanhã" e quanto sobra em cada um — **só repetindo** o `texto`/`lotes` da separação.
- O lote **pelo nome falável** ("lote do dia 8"), nunca pelo código, salvo se perguntarem.
- Que ficou lote **para trás** e qual vender primeiro (do `avisos` da venda ou de `lotes_deixados`).
- Que um lote **venceu** e que dá para seguir **com um motivo** — e perguntar o motivo.
- A conferência: "o lote do dia 8 de coxinha venceu com 18 unidades; ainda estão aí?"

### O que continua proibido

- **Calcular** de onde pegar, quanto sobra ou o resto da alocação: o agente repete a consulta; o núcleo completa por FEFO.
- **Inventar motivo** de vencido ou usar o motivo sem a pessoa dizer; seguir com vencido sem confirmação.
- Vender o **reservado** de encomenda em outra venda; deixar saldo negativo; "apagar" venda ou movimento (corrige-se com lançamento novo).
- Dizer que um lote "venceu" ou "vence" sem a validade vinda da consulta.
