# Plano 6 — Vendas, encomendas, fritura e contas a receber — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A cozinha diz o preço de cada salgado (a unidade crua congelada, a caixa com 25, a frita do balcão), vende no balcão ou no atacado e o estoque baixa sozinho pelo que vence primeiro. Quem leva fiado vira conta a receber, e o dono anota quando o cliente paga. A encomenda de sábado separa na hora o que já existe e mostra o que falta produzir; quando o estoque entra, o dono confirma e a reserva se completa; na entrega, tudo vira venda uma vez só. O cru guardado vai para a fritura com o custo certo (cru + óleo), as sobras e o vencido saem com motivo, e o resumo do dia mostra vendas, encomendas, quem está devendo e o que sobrou frito.

**Architecture:** App novo `vendas` (apresentação com preço, venda e linhas, encomenda e itens, reserva). `Cliente` em `cadastros`, ao lado de `Fornecedor` (RF-CAD-05). Contas a receber **no `financeiro` que já existe**: `Conta` ganha `tipo` ("pagar"/"receber"), `cliente` e `venda`; `Parcela` e `Pagamento` são os mesmos. Fritura em `producao` (`Fritura`, `producao/fritura.py`), ao lado da produção. Perda e descarte em `estoque.servicos.registrar_perda`. A reserva mora em `vendas` e o estoque a lê (`estoque.servicos.reservado`, `livre_porcao`, `disponivel`, `alocar_porcoes`). Toda escrita passa por `nucleo.operacoes.executar()`. Consultas puras em `vendas/consultas.py` e `financeiro/consultas.py`; a caixa ganha três geradores e a operação `completar_reserva`; o `resumo_do_dia` ganha vendas, encomendas, recebíveis e sobras.

**Tech Stack:** Python 3.12, uv, Django 5.2, SQLite, pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-10-19-agente-cozinha-design.md` (§3 o agente só registra dinheiro; §6.2 alçada — "Vendi 2 caixas pro João a prazo" e "registrar sobra como perda"; §6.3.6 forma final e fritura; §6.3.7 um produto por tamanho; §6.7 necessidade de produção e sobras do dia). Regras em `docs/prd/02-prd.md`: RF-CAD-04/05, RF-VEN-01 a 11, RF-FRI-01 a 03, RF-FIN-03/04/06/07/09/10, RF-EST-02/04/05/06/10, RF-CUS-06, RN-03, RN-18, RN-19, RN-29 a 32, RN-34 a 36, FL-04, FL-06, FL-07, FL-09, FL-10, CA-24, CA-26 a 30, CA-37. Pendências herdadas: `2026-10-19-plano-2-pendencias.md` (fritura de lotes crus guardados e troca de óleo), `2026-11-12-plano-3-compras.md` (contas a receber pendurando em `financeiro`), `2026-11-12-plano-4-pendencias.md` (reservas no disponível, encomendas, vendas, sobras do dia e necessidade de produção no resumo e na caixa; descarte de lote vencido).

## O que muda em relação ao PRD (realidade do produto)

- **Apresentação no lugar de "produto com apresentações".** O design (§6.3.7) já fez de cada tamanho um produto. A apresentação diz **como** esse tamanho é vendido: nome ("unidade", "caixa com 25"), **forma** (cru/frito), **conservação** (fresco/resfriado/congelado), unidades por apresentação, embalagem consumida e os preços de varejo e atacado. É o "preço por produto/tamanho e estado" pedido.
- **Encomenda confirmada ao ser criada.** O PRD tem "rascunho → confirmada"; aqui o rascunho é a proposta do agente (nível 2) ou o formulário. "Separada" virou **"pronta"**, que é **derivada** (tudo reservado), sem passo manual: menos um botão (design A4).
- **A fritura do balcão é um registro rápido** separado da produção. A fritura como última etapa de um preparo continua como está (Plano 2).

## Divisão do plano

| Fase | Quem | Entrega | Situação |
|---|---|---|---|
| **1 — Núcleo** | esta sessão | modelos, migrações, serviços sobre `executar()`, consultas, geradores, resumo do dia, admin, testes | **feita** (Tasks 1–8) |
| **2a — Telas** | sessão paralela, só `web/` | vender, encomendas, necessidade de produção, fritura e sobras, clientes, preços, contas a receber, blocos novos em "Hoje" (Tasks 9–14) | a fazer |
| **2b — Ferramentas MCP** | sessão paralela, só `agente/` e `docs/` do agente | ferramentas de leitura e de escrita com alçada, instruções do agente de voz (Tasks 15–18) | a fazer |

As fases 2a e 2b não mexem em modelo nem em serviço; se precisarem de algo do núcleo, pedem à coordenação. O contrato estável está no fim deste documento.

## Decisões deste plano (revisáveis pelo dono)

| Decisão | Por quê / custo se estiver errada |
|---|---|
| **Contas a receber reaproveitam `financeiro`** (`Conta.tipo = "receber"`, `cliente`, `venda`; mesmas `Parcela` e `Pagamento`). `registrar_recebimento`/`estornar_recebimento_cliente` usam o mesmo código de `registrar_pagamento`/`estornar_pagamento` e **recusam a parcela do outro tipo**. As consultas antigas continuam de contas a pagar (`tipo="pagar"` por padrão). | Parcelas, saldo derivado, parcial, juros/desconto, estorno e "vencida" são as mesmas regras (RN-31/32, RF-FIN-03/04/07/09). Duplicar seria dobrar o código e os testes. O risco — misturar pagar e receber numa tela ou ferramenta antiga — está coberto pelo padrão `tipo="pagar"` e pela recusa cruzada (testado). |
| **Venda à vista não abre conta**; o que entrou fica em `Venda.recebido_na_hora` (com a forma). **A prazo** abre conta a receber com parcelas somando o total. | Balcão é o caso mais comum; uma conta quitada por pastel vendido é burocracia. Custo: o "caixa do dia" soma `recebido_na_hora` das vendas + recebimentos anotados + sinais do dia (três fontes, todas nas consultas). |
| **Encomenda:** preços gravados na criação; **sinal** anotado (0 até o total); na entrega, o **saldo** (total − sinal) entra na hora ou vira conta a receber. A entrega **exige tudo reservado** e dentro da validade. | RN-30; RF-VEN-08. Entrega parcial não existe ainda (ver perguntas). |
| **Reserva por porção** (lote + conservação), FEFO, **só em porções que valem até o dia da entrega**; não gera movimento (o saldo só muda na entrega). Disponível = saldo − reservado − vencido (a reserva em porção vencida não conta duas vezes). | RN-03, RN-35, CA-26/29. Reservar um frito de hoje para daqui a 3 dias seria reservar o que vai vencer. |
| **Venda, fritura, perda e transferência de estado não tocam no reservado.** Descartar uma porção **vencida** libera as reservas dela. | RN-35 ("reserva não pode ser usada por outra saída"); FL-07 A3. |
| **Completar a reserva é um comando** (`completar_reserva`), nunca automático: libera o que venceria antes da entrega e reserva o que faltar. A rotina **propõe** na caixa quando há estoque livre que serve. | RF-VEN-07 / DEC-F2-040: "o operador completa a reserva com uma confirmação. Não há preenchimento automático". |
| **Cancelar venda:** unidades vão para **perda** por padrão; "volta ao estoque" devolve aos lotes de origem se a porção não venceu (embalagem não volta). O recebível em aberto é cancelado e o que o cliente já pagou (à vista, sinal, recebimentos) fica anotado em `valor_devolvido`. Só cancelamento **total**. | RN-36, FL-09, CA-30. A perda não gera movimento novo: as unidades já saíram na venda. |
| **Cancelar encomenda** (antes da entrega) libera as reservas; o sinal é **anotado como devolvido** por padrão (`devolver_sinal=False` para reter). Depois da entrega, cancela-se a **venda**. | RN-35; o documento não decide o sinal (pergunta Q5). |
| **Fritura:** lote cru (não vencido, não reservado) → lote frito novo, `codigo` `AAMMDD-F<n>`, vinculado à origem (`Fritura.lote_origem`, `producao.servicos.origem`). Custo = (cru × fritas + óleo de referência × fritas) ÷ boas. Validade pelo critério de "frito" do produto (sem critério, manual e justificada). Perdas exigem motivo; zero boas exige confirmar perda total. | RF-FRI-01/02, CA-24, RN-27, FL-04 E1. Consumo pendente na fritura não entra (não há cru sem lote). |
| **Perda/descarte = `registrar_perda`** (movimento "perda" com motivo, na unidade informada). Vale para qualquer item (ingrediente, embalagem, salgado). | RF-EST-02/10, RN-19, pendência do Plano 4. Não vira decisão da caixa ainda (o aviso de vencido continua aviso; ver pendências). |
| **Venda não aceita consumo pendente**: faltando, recusa sem gravar nada. | FL-06 E1. |
| **Necessidade de produção** = por produto/forma/conservação, o que falta reservar nas encomendas abertas até hoje + 3 dias, menos o estoque livre. **Não cria produção** (a tela/agente oferece "começar produção" com `iniciar_producao`). | RF-VEN-06, DEC-F2-019, CA-27. |
| **Sobras fritas** (RF-FRI-03): consulta de fritos com saldo; a rotina avisa os fritos **de dias anteriores** ainda com saldo. | Avisar durante o dia, enquanto ainda se vende, seria ruído (design A5). Pergunta Q8. |
| **Geradores novos:** `encomenda_sem_estoque` (decisão `completar_reserva` se há estoque livre que serve; senão aviso "é preciso produzir"), `receber_vencidas` (aviso), `sobras_fritas` (aviso). | Pedido explícito (encomendas sem estoque, contas a receber vencidas). "Encomendas do dia" ficam **só no resumo**: não há o que decidir. |
| **Apresentação já vendida** não muda de produto, forma, conservação nem unidades (cria-se outra e inativa-se esta); nome, preços e embalagem podem mudar. | RN-30: a linha guarda preço e fator, mas forma e conservação vêm da apresentação. |
| **Cliente** sem repetir nome ignorando acento e caixa (mesma regra do fornecedor). Venda de balcão não precisa de cliente; a prazo e encomenda precisam. | RF-CAD-05. |

## Global Constraints

- Tudo dos Planos 1 a 4 continua valendo: Decimal sempre; dinheiro 2 casas, custo unitário 4 casas, quantidade 3 casas; `ROUND_HALF_UP`; toda gravação por `executar()`; nada é apagado (RN-34).
- Venda e entrega são atômicas: todas as linhas ou nenhuma (RN-08).
- Estoque nunca negativo; o reservado e o vencido nunca saem por venda (RN-02, RN-19, RN-35).
- O sistema nunca cobra nem paga: recebimento é anotação (design §3).
- Consultas não gravam e não repetem regra; devolvem Decimal/date/time. Serviços devolvem o dict do `executar()` (Decimal e data como texto).

## Review Focus

- FEFO na venda pela porção certa (forma + conservação), sem vencido (`test_venda_baixa_pelo_que_vence_primeiro_na_forma_e_conservacao`).
- Sem estoque → nada gravado, erro na trilha (`test_venda_sem_estoque_recusa_sem_gravar_nada`).
- CA-26/29: reserva × disponível × venda direta (`test_encomenda_reserva_o_que_ha_e_mostra_o_que_falta_produzir`, `test_disponivel_desconta_reservado_e_vencido`).
- Entrega uma única vez, com e sem a mesma chave (`test_entrega_vira_venda_uma_unica_vez`).
- Reserva só em lote que vale até a entrega; completar troca o lote que venceria (`test_reserva_so_em_lote_que_vale_ate_a_entrega_e_troca_o_que_venceria`).
- Reservado não se transfere, não se frita, não se perde; vencido descartado libera a reserva (`test_transferencia_e_perda_nao_tocam_no_reservado`, `test_descarte_de_vencido_libera_a_reserva`, `test_fritura_nao_usa_vencido_nem_reservado`).
- CA-24 (`test_fritura_gera_lote_frito_com_custo_e_origem`), CA-28 (`test_caixa_baixa_unidades_e_embalagem_e_preco_fica_gravado`), CA-30, CA-37.
- Pagar × receber não se misturam (`test_venda_a_prazo_vira_conta_a_receber`, `test_recebivel_vencido_e_sobra_frita_viram_aviso_e_entram_no_resumo`).

---

## Fase 1 — Núcleo (feita)

### Task 1: Cliente
**Files:** `cadastros/models.py`, `cadastros/servicos.py`, `cadastros/admin.py`, `cadastros/migrations/0005_cliente.py`.
- [x] `Cliente` (nome único, contato, ativo); `salvar_cliente` com nome normalizado (`_repetido`, compartilhado com `salvar_fornecedor`); admin pelo núcleo.

### Task 2: Contas a receber no financeiro
**Files:** `financeiro/models.py`, `financeiro/servicos.py`, `financeiro/consultas.py`, migrações `0002`/`0003`.
- [x] `Conta.tipo`, `cliente`, `venda`. `abrir_conta_receber`, `cancelar_conta_da_venda`.
- [x] `registrar_recebimento`, `estornar_recebimento_cliente` (mesmo código de pagar; recusa cruzada).
- [x] Consultas com `tipo` (padrão "pagar") e `receber_em_aberto`, `receber_vencidas`, `receber_a_vencer`, `devido_por_cliente`, `recebimentos`.

### Task 3: Estoque — reservado, livre, disponível, FEFO por porção, perda
**Files:** `estoque/servicos.py`.
- [x] `reservado`, `livre_porcao`, `disponivel` (= saldo − reservado − vencido), `alocar_porcoes`.
- [x] `transferir_estado` não move o reservado. `registrar_perda` (descarte de vencido libera reservas).

### Task 4: Apresentações e venda direta
**Files:** `vendas/models.py`, `vendas/servicos.py`, `vendas/admin.py`, `vendas/migrations/0001_initial.py`, `sabor/settings.py`.
- [x] `Apresentacao`, `Venda`, `LinhaVenda` (preço de tabela e praticado, fator, custo, baixas por lote).
- [x] `salvar_apresentacao`, `registrar_venda`, `cancelar_venda`.

### Task 5: Encomendas e reservas
- [x] `Encomenda`, `ItemEncomenda`, `Reserva`; `criar_encomenda`, `completar_reserva`, `cancelar_encomenda`, `entregar_encomenda`.

### Task 6: Fritura
**Files:** `producao/models.py` (`Fritura`), `producao/fritura.py`, `producao/servicos.py` (`origem` do frito), `producao/admin.py`, `producao/migrations/0004_fritura.py`.
- [x] `registrar_fritura`.

### Task 7: Consultas, caixa e resumo do dia
**Files:** `vendas/consultas.py`, `decisoes/geradores.py`, `decisoes/servicos.py`, `decisoes/consultas.py`.
- [x] `clientes`, `estoque_para_venda`, `apresentacoes`, `vendas`, `vendas_do_dia`, `detalhe_venda`, `encomendas`, `encomendas_do_dia`, `detalhe_encomenda`, `necessidade_producao`, `frituras`, `sobras_fritas`, `lotes_para_fritar`.
- [x] Geradores `encomenda_sem_estoque`, `receber_vencidas`, `sobras_fritas`; `completar_reserva` em `OPERACOES`; blocos `vendas`, `encomendas`, `receber`, `sobras_fritas` e totais novos no `resumo_do_dia`; rótulos novos em `ROTULOS`.

### Task 8: Testes e fechamento
**Files:** `tests/test_vendas.py`, `tests/test_vendas_decisoes.py`.
- [x] `uv run pytest` verde (348); `makemigrations --check` sem mudanças.

---

## Fase 2a — Telas (`web/`)

Padrão das telas existentes: login obrigatório, `{% chave %}` em todo POST, `RegraViolada` mostrada sem perder o que foi digitado, botões de 44 px, sem rolagem horizontal a 360 px (RNF-02: venda direta e fritura são tarefas de chão de cozinha). A tela nunca calcula: totais e "livre" vêm das consultas.

### Task 9: Vender (balcão)
- [ ] Botões grandes por apresentação (`apresentacoes()`, mostrando `livre_apresentacoes`), quantidade com +/−, tabela varejo/atacado, preço editável por linha (desconto manual), cliente opcional (obrigatório se "a prazo"), forma de pagamento, parcelas (`financeiro.servicos.dividir_parcelas`) → `registrar_venda`.
- [ ] Vendas do dia (`vendas_do_dia`) com os totais e, por venda, **Cancelar** (motivo + destino perda/volta ao estoque) → `cancelar_venda`.
- [ ] Test: dois POSTs com a mesma chave → uma venda; sem estoque mostra a mensagem e não grava.

### Task 10: Encomendas
- [ ] Lista (`encomendas()`; filtros situação e período) com situação (aberta/pronta) e o que falta; nova encomenda (cliente, dia, hora opcional, retirada/entrega, itens, sinal) → `criar_encomenda`.
- [ ] Detalhe (`detalhe_encomenda`): **Completar reserva** → `completar_reserva`; **Entregar** (à vista/forma ou a prazo/parcelas do saldo) → `entregar_encomenda`; **Cancelar** (motivo, devolver o sinal?) → `cancelar_encomenda`.

### Task 11: Necessidade de produção
- [ ] `necessidade_producao()`: por produto/forma/conservação, falta, livre e a produzir; botão "começar produção" leva à tela de produção com o produto e `a_produzir` preenchidos (forma "cru" ou "frito" conforme a linha; nenhuma OP é criada sem o clique, CA-27).

### Task 12: Fritura e sobras
- [ ] Registro rápido: produto → `lotes_para_fritar` (o primeiro já escolhido), fritas, boas, motivo das perdas → `registrar_fritura`; mostra o custo por unidade.
- [ ] Sobras (`sobras_fritas()`): por porção, **Perda** → `registrar_perda` (motivo padrão "sobra do dia").
- [ ] Descarte de vencido: na tela de lote e no bloco de vencidos do Hoje, botão **Descartar** → `registrar_perda`.

### Task 13: Clientes, preços e contas a receber
- [ ] Clientes (`clientes`, `salvar_cliente`). Preços (`apresentacoes(ativas=False)`, `salvar_apresentacao`).
- [ ] Contas a receber: vencidas, a vencer (`receber_vencidas`, `receber_a_vencer`), por cliente (`devido_por_cliente`), recebimentos (`recebimentos`); **Anotar recebimento** → `registrar_recebimento`; **Estornar** → `estornar_recebimento_cliente`.

### Task 14: Hoje
- [ ] Blocos novos do `resumo_do_dia`: vendas de hoje (quantidade, total), encomendas de hoje e próximas (prontas/abertas, sem estoque destacadas), o que falta produzir, a receber (vencidas e a vencer), sobras fritas. Rótulos das origens novas na caixa (`encomenda_sem_estoque`, `receber_vencidas`, `sobras_fritas`).

---

## Fase 2b — Ferramentas MCP e instruções do agente de voz (`agente/`)

Padrão de `agente/ferramentas.py` (nível 0 lê, 1 faz e repete, 2 cria `Proposta` e espera o "sim"). Quem fala é a equipe da cozinha. O agente nunca calcula preço, total ou falta: repete os números do retorno.

### Task 15: Leitura (nível 0)
- [ ] `ver_precos(produto="")` → `apresentacoes`; `ver_estoque_para_venda` → `estoque_para_venda`.
- [ ] `ver_vendas(periodo="hoje")` → `vendas` (fala os `totais`).
- [ ] `ver_encomendas(dia="")`, `ver_encomenda(encomenda_id)` → `encomendas`/`encomendas_do_dia`/`detalhe_encomenda`.
- [ ] `ver_necessidade_producao` → `necessidade_producao`.
- [ ] `ver_a_receber(cliente="")` → `receber_vencidas`, `receber_a_vencer`, `devido_por_cliente`.
- [ ] `ver_sobras` → `sobras_fritas`.

### Task 16: Escrita
- [ ] Ferramentas da tabela "Ferramentas MCP sugeridas" abaixo, com o nível proposto; registrar em `agente.propostas.OPERACOES` as de nível 2.
- [ ] Cliente e apresentação por **nome falado**, sem acento e sem caixa (como `agente.compras` faz com fornecedor); ambíguo → pergunta (design §6.2).

### Task 17: Ver e decidir a caixa nova
- [ ] `agente.decisoes._efeito` ganha a frase de `completar_reserva` ("vou reservar para a encomenda N o que houver no estoque").

### Task 18: Instruções
- [ ] `docs/agente-instrucoes-vendas.md` (padrão de `docs/agente-instrucoes-compras.md`): "vendi…", "encomenda do…", "fritei…", "joga fora…", "o João pagou…", "quanto o João deve?", "o que tem de encomenda amanhã?", "o que falta produzir?". Sempre repetir apresentação, quantidade, preço e total do retorno; nunca dizer "vendido" antes do retorno do núcleo (RN-39).
- [ ] `docs/agente-mcp.md`: tabela das ferramentas novas.

---

## Fora deste plano

- **Troca de óleo e ajuste de óleo** (RF-FRI-04, RN-26, CA-25) — desenho pronto: `TrocaOleo` (data, item óleo, quantidade, operação) em `producao`; o serviço baixa o óleo do estoque (`alocar_fefo`) e calcula ajuste = custo do óleo baixado − Σ(`oleo_ref_un` × unidades fritas desde a troca anterior), somando `Fritura.quantidade` e as produções `forma="frito"` (boas + perdas) do período. Só relatório: nenhum lote muda.
- **Devolução parcial** de venda (RF-VEN-09 "total ou parcial") — hoje só o cancelamento total; desenho: `devolver_venda(venda_id, linhas=[{linha_id, unidades}], destino)` gerando o mesmo movimento `devolucao_cliente` e abatendo do recebível por aviso de ajuste.
- **Alterar encomenda** (itens, dia) — hoje: cancelar e criar de novo (as reservas voltam e são refeitas).
- **Entrega parcial** de encomenda.
- Escolher o lote na venda (RF-EST-05 "o operador pode trocar o lote") — hoje sempre FEFO (design §6.4: sem escolha de lote na tela).
- Preço por cliente, cobrança, juros automáticos (PRD §4, W).
- Descarte de vencido **aprovável pela caixa** (o gerador `lotes_vencidos` passar a propor `registrar_perda`) — muda textos e testes já entregues da caixa e do agente.
- Relatórios de margem por produto e período (RF-REL-02/03, RF-CUS-06) além dos totais de `vendas()` — Plano 7.
- Alerta de reserva parcial "quando entra saldo" no momento da entrada (RF-VEN-07): hoje vem pela rotina (`encomenda_sem_estoque`), de hora em hora.

## Perguntas em aberto para o dono (com o padrão adotado)

| # | Pergunta | Padrão adotado até a resposta | Custo de estar errado |
|---|---|---|---|
| Q1 | Quando alguém fala "vendi 2 caixas pro João", o agente deve gravar na hora e repetir, ou repetir e esperar o seu "sim"? | **Repete e espera o "sim"** (nível 2), contra o design, que punha venda como "faz direto". Numa cozinha barulhenta, "2" e "12" se confundem, e desfazer uma venda manda as unidades para perda por padrão. | Um "sim" a mais por venda falada. Se o dono preferir rapidez, muda-se para nível 1 numa linha. |
| Q2 | A forma de pagamento (dinheiro, pix, cartão) precisa ser dita em toda venda à vista? | **Não é obrigatória**; o total do dia por forma só soma o que foi dito ("não informada" no resto). | O fechamento por forma de pagamento fica incompleto. |
| Q3 | Uma encomenda pode ser entregue faltando alguma coisa (entrega parcial)? | **Não**: só entrega com tudo reservado; para entregar menos, cancela e cria outra menor. | Um passo a mais nos dias em que faltar salgado. |
| Q4 | Reservar para uma encomenda um lote que vence antes do dia da entrega? | **Não reserva**: só lote que ainda vale no dia da entrega. Frito do dia nunca fica reservado para outro dia. | Encomenda aparece "faltando" mesmo havendo estoque que vence antes; é o sinal certo para produzir mais perto da data. |
| Q5 | Se o cliente cancela a encomenda, o sinal volta para ele? | **Volta** (anotado como devolvido); dá para marcar "fica com o sinal". | Anotação errada do dinheiro devolvido; o sistema não movimenta dinheiro. |
| Q6 | Quando uma venda é cancelada depois que o salgado saiu, ele volta para o estoque? | **Vai para perda** (regra do PRD); "volta ao estoque" só se o lote não venceu e alguém escolher. A caixa de papelão nunca volta. | Estoque a menos se o salgado voltou intacto e ninguém escolheu "volta ao estoque". |
| Q7 | Com quantos dias de antecedência a encomenda sem estoque deve aparecer na caixa e o "falta produzir" considerar? | **3 dias** (hoje, amanhã e depois, mais as atrasadas). | Aviso tarde demais para encomendas grandes. Constante `DIAS_ENCOMENDAS` em `decisoes/consultas.py`. |
| Q8 | Salgado frito que sobrou: quando avisar? | **No dia seguinte**, pela rotina; durante o dia a sobra aparece no resumo (`sobras_fritas`). Destino padrão: perda (REG-02 decide se pode ter outro). | Sobra de ontem vendida hoje sem ninguém perceber, se o aviso for ignorado. |
| Q9 | Preço de atacado é obrigatório em toda apresentação? | **Não**; vender no atacado sem preço de atacado é recusado ("não tem preço de atacado"). | Uma recusa no balcão até cadastrar o preço. |
| Q10 | Quem pode mudar preço por voz? | **Ninguém por voz por enquanto** (só tela); se quiser, vira ferramenta nível 2. | Ter de abrir a tela para mudar preço. |
| Q11 | Perda e descarte ditos pela cozinha ("joga fora 10 coxinhas que caíram") gravam na hora? | **Repete e espera o "sim"** (nível 2): é estoque saindo sem volta. | Um "sim" a mais. |
| Q12 | Na venda, dá para escolher o lote? | **Não**: sempre o que vence primeiro (FEFO), sem perguntar. | Se alguém pegou do lote errado, o estoque por lote fica trocado; corrige-se por perda/entrada. |

## Contrato para a fase 2

Serviços: argumentos **keyword-only**, terminando em `autor`, `canal="web"`, `chave=None`; gravam por `executar()` (idempotentes por `chave`); devolvem o dict do `executar()` (Decimal, data e hora viram texto); recusas levantam `nucleo.operacoes.RegraViolada` com mensagem em pt-BR para mostrar ou falar. Números e datas podem vir como texto (`"4.50"`, `"2026-11-15"`, hora `"15:30"`). Consultas não gravam e devolvem Decimal/date/time.

### Serviços

| Serviço | Parâmetros | Retorno | Recusas principais |
|---|---|---|---|
| `cadastros.servicos.salvar_cliente` | `nome`, `contato=""`, `ativo=True`, `cliente_id=None` | `{cliente_id, nome}` | sem nome; nome repetido (sem acento/caixa); não encontrado |
| `vendas.servicos.salvar_apresentacao` | `produto_id`, `nome`, `forma` (cru/frito), `estado` (fresco/resfriado/congelado), `unidades`, `preco_varejo`, `preco_atacado=None`, `embalagem_id=None`, `embalagens=0`, `ativo=True`, `apresentacao_id=None` | `{apresentacao_id, nome}` | não é produto; sem nome; forma/estado inválidos; unidades < 1; sem preço de varejo; atacado ≤ 0; embalagem sem quantidade; nome repetido no produto; já vendida e mudou produto/forma/estado/unidades |
| `vendas.servicos.registrar_venda` | `itens=[{apresentacao_id, quantidade, preco?}]`, `tabela="varejo"`, `cliente_id=None`, `condicao="a_vista"`, `forma_pagamento=""`, `parcelas=None` (`[{valor, vencimento}]`, a prazo), `data_venda=None` | `{venda_id, cliente, condicao, total, custo, recebido_na_hora, conta_id, parcelas: [{parcela_id, valor, vencimento}], linhas: [{apresentacao_id, apresentacao, quantidade, unidades, preco, preco_tabela, total}]}` | condição inválida; a prazo sem cliente; cliente inativo; apresentação inativa/não encontrada; quantidade < 1; sem preço de atacado; "Só há N un de 'X' cru congelado para vender…"; falta de embalagem ("Falta … de 'Caixa…'"); parcelas não somam o total |
| `vendas.servicos.cancelar_venda` | `venda_id`, `motivo`, `destino="perda"` ("estoque") | `{venda_id, destino, unidades_devolvidas, valor_devolvido, conta_cancelada}` | não encontrada; já cancelada; sem motivo; destino inválido; "lote … venceu: a devolução vai para perda" |
| `vendas.servicos.criar_encomenda` | `cliente_id`, `entrega_data`, `itens` (como na venda), `entrega_hora=None`, `tabela="varejo"`, `modo="retirada"` ("entrega"), `observacao=""`, `sinal=0`, `sinal_forma=""` | `{encomenda_id, cliente, entrega_data, entrega_hora, situacao ("aberta"/"pronta"), total, sinal, saldo, falta, itens: [{item_encomenda_id, apresentacao_id, apresentacao, quantidade, unidades, preco, total, reservado, falta}]}` | sem cliente; dia passado; modo inválido; sinal fora de 0..total; recusas dos itens |
| `vendas.servicos.completar_reserva` | `encomenda_id` | o mesmo da encomenda + `reservas_liberadas: [id]` | não encontrada; já entregue; cancelada |
| `vendas.servicos.cancelar_encomenda` | `encomenda_id`, `motivo`, `devolver_sinal=True` | `{encomenda_id, situacao, reservas_liberadas, sinal, sinal_devolvido}` | não encontrada; já entregue ("cancele a venda"); cancelada; sem motivo |
| `vendas.servicos.entregar_encomenda` | `encomenda_id`, `condicao="a_vista"`, `forma_pagamento=""`, `parcelas=None` (somando o saldo), `data_entrega=None` | `{venda_id, encomenda_id, cliente, condicao, total, sinal, saldo, recebido_na_hora, custo, conta_id, parcelas, linhas}` | já entregue ("(venda N)"); cancelada; "Falta reservar N un de 'X'…"; lote reservado venceu; falta embalagem; parcelas ≠ saldo |
| `producao.fritura.registrar_fritura` | `lote_id`, `quantidade`, `boas`, `estado=""` (conservação do cru), `estado_destino="fresco"`, `perda_motivo=""`, `validade_manual=None`, `justificativa=""`, `confirmar_perda_total=False` | `{fritura_id, lote_id, lote_origem_id, produto, fritas, boas, perdas, custo_total, custo_unitario, validade, validade_manual}` | não é lote cru de salgado; sem óleo de referência; boas > fritas; perdas sem motivo; zero boas sem confirmar; vencido; mais que o saldo; reservado; sem critério de validade de "frito" e sem validade manual justificada |
| `estoque.servicos.registrar_perda` | `lote_id`, `estado=""`, `quantidade`, `unidade=""` (padrão: unidade base), `motivo` | `{movimento_id, lote_id, item, quantidade, unidade_base, vencido, reservas_liberadas, valor, saldo}` | sem motivo; lote não encontrado; unidade sem fator; quantidade ≤ 0; mais que o saldo da porção; reservado (fora do vencido) |
| `financeiro.servicos.registrar_recebimento` | como `registrar_pagamento`: `parcela_id`, `valor=None` (saldo), `data_pagamento=None`, `forma=""`, `diferenca=0`, `diferenca_tipo=""`, `diferenca_motivo=""` | `{pagamento_id, parcela_id, valor, valor_pago, situacao, saldo}` | parcela a pagar ("anote como pagamento"); as de `registrar_pagamento` |
| `financeiro.servicos.estornar_recebimento_cliente` | `pagamento_id`, `motivo` | `{pagamento_id, parcela_id, situacao, saldo}` | não encontrado (ou é de conta a pagar); sem motivo; já estornado |
| `financeiro.servicos.registrar_pagamento` / `estornar_pagamento` | sem mudança | — | **novo:** recusam parcela/pagamento de conta a receber |

`decisoes.servicos.OPERACOES` ganha `completar_reserva` (decisões da origem `encomenda_sem_estoque`).

### Consultas (sem gravar)

| Consulta | Parâmetros | Retorno |
|---|---|---|
| `vendas.consultas.clientes` | `ativos=True` | `[{cliente_id, nome, contato, ativo}]` |
| `vendas.consultas.apresentacoes` | `produto_id=None`, `ativas=True`, `hoje=None` | `[{apresentacao_id, produto_id, produto, nome, descricao, forma, estado, unidades, preco_varejo, preco_atacado, embalagem_id, embalagem, embalagens, ativo, livre_unidades, livre_apresentacoes}]` |
| `vendas.consultas.estoque_para_venda` | `produto_id=None`, `hoje=None` | `[{produto_id, produto, forma, estado, saldo, reservado, vencido, livre}]` |
| `vendas.consultas.vendas` | `de=None`, `ate=None`, `cliente_id=None`, `incluir_canceladas=False` | `{vendas: [{venda_id, data, cliente_id, cliente, tabela, condicao, forma_pagamento, total, recebido_na_hora, a_prazo, custo, encomenda_id, situacao, motivo_cancelamento, destino, valor_devolvido, conta_id, linhas: [{apresentacao_id, apresentacao, produto_id, produto, quantidade, unidades, preco_tabela, preco, total, custo}]}], totais: {vendas, total, custo, recebido_na_hora, a_prazo, margem_estimada, por_forma_pagamento: {forma: valor}, por_produto: [{produto, unidades, total}], canceladas}}` (canceladas fora dos totais; `margem_estimada` rotulada "estimada", sem tributos/despesas/indiretos) |
| `vendas.consultas.vendas_do_dia` / `detalhe_venda` | `hoje=None` / `venda_id` | como acima / um dict de venda ou `None` |
| `vendas.consultas.encomendas` | `situacao="abertas"` ("aberta", "pronta", "entregue", "cancelada", `None`), `de=None`, `ate=None` (dia da entrega), `cliente_id=None`, `hoje=None` | `[{encomenda_id, cliente_id, cliente, entrega_data, entrega_hora, dias, modo, observacao, tabela, total, sinal, sinal_forma, saldo, situacao, falta, itens: [{item_encomenda_id, apresentacao_id, apresentacao, produto_id, produto, forma, estado, quantidade, unidades, preco, preco_tabela, total, reservado, falta}], venda_id, criada_em, motivo_cancelamento, sinal_devolvido}]`, por dia e hora |
| `vendas.consultas.encomendas_do_dia` / `detalhe_encomenda` | `hoje=None` / `encomenda_id` | abertas e prontas de hoje / um dict ou `None` |
| `vendas.consultas.necessidade_producao` | `dias=3`, `hoje=None` | `[{produto_id, produto, forma, estado, falta, livre, a_produzir, primeira_entrega, encomendas: [id]}]` |
| `vendas.consultas.frituras` | `de=None`, `ate=None` | `[{fritura_id, produto, lote_origem_id, lote_id, fritas, boas, perdas, perda_motivo, custo_total, custo_unitario, criado_em}]` |
| `vendas.consultas.sobras_fritas` | `hoje=None`, `ate_ontem=False` | porções de lotes fritos com saldo (campos de `porcoes`) + `frito_em`, `reservado` |
| `vendas.consultas.lotes_para_fritar` | `produto_id`, `hoje=None` | porções cruas não vencidas com livre > 0, FEFO (campos de `porcoes`) + `livre`, `custo_unitario`; a primeira é a sugestão |
| `estoque.servicos.reservado` / `livre_porcao` / `disponivel` | `item=`/`lote=`/`estado=` · `lote, estado` · `item, hoje=None` | Decimal (disponível agora desconta o reservado, RN-03) |
| `financeiro.consultas.receber_em_aberto` / `receber_vencidas` / `receber_a_vencer` | `cliente_id=None` · — · `dias=7` (+ `hoje`) | parcelas como as de pagar, com `tipo`, `venda_id`, `cliente_id`, `cliente` |
| `financeiro.consultas.devido_por_cliente` | `hoje=None` | `[{cliente_id, cliente, devido, vencido, parcelas}]`, do maior para o menor |
| `financeiro.consultas.recebimentos` | `de=None`, `ate=None`, `cliente_id=None`, `incluir_estornados=False` | como `pagamentos` (+ `cliente`, `venda_id`) |
| `financeiro.consultas.parcelas_em_aberto` / `contas_vencidas` / `contas_a_vencer` / `pagamentos` | ganham `tipo="pagar"` (e `cliente_id`) | sem mudança para quem já usa |
| `decisoes.consultas.resumo_do_dia` | ganha `dias_encomendas=3` | blocos novos: `vendas: {hoje: totais de vendas()}`, `encomendas: {dias, hoje, proximas, atrasadas, sem_estoque: [id], necessidade}`, `receber: {dias, vencidas, a_vencer, total_vencido, total_a_vencer, total_a_receber}`, `sobras_fritas`; `totais` ganha `vendas_hoje`, `valor_vendas_hoje`, `encomendas_hoje`, `encomendas_proximas`, `encomendas_atrasadas`, `encomendas_sem_estoque`, `receber_vencidas`, `valor_receber_vencidas`, `receber_a_vencer`, `valor_receber_a_vencer`, `sobras_fritas`. `contas` continua só a pagar |

Origens novas da caixa: `encomenda_sem_estoque` (decisão `completar_reserva` com `parametros={encomenda_id}`, ou aviso), `receber_vencidas` (aviso; `detalhes` = parcela), `sobras_fritas` (aviso; `detalhes` = porção + `frito_em`). Para a encomenda, `detalhes` = o dict de `encomendas()`.

Tipos de movimento novos (para telas de histórico): `saida_venda`, `devolucao_cliente`, `consumo_fritura`, `entrada_fritura`, `perda`.

### Telas sugeridas (fase 2a)

Vender (balcão) e vendas do dia · Encomendas (lista, nova, detalhe com completar/entregar/cancelar) · Necessidade de produção · Fritura rápida e sobras (perda) · Descartar vencido (lote e Hoje) · Clientes · Preços (apresentações) · Contas a receber (vencidas, a vencer, por cliente, recebimentos, anotar e estornar) · blocos novos em Hoje.

### Ferramentas MCP sugeridas (fase 2b)

| Ferramenta | Nível | Serviço / consulta | Por quê |
|---|---|---|---|
| `ver_precos`, `ver_estoque_para_venda`, `ver_vendas`, `ver_encomendas`, `ver_encomenda`, `ver_necessidade_producao`, `ver_a_receber`, `ver_sobras` | 0 | consultas acima | só leem |
| `cadastrar_cliente` | 1 | `salvar_cliente` | não mexe em estoque nem dinheiro; repete o nome (o núcleo recusa repetido) |
| `completar_reserva` | 1 | `completar_reserva` | o próprio pedido é a confirmação de RF-VEN-07; só separa estoque, não tira nada; desfaz-se cancelando |
| `registrar_fritura` | 1 | `registrar_fritura` | comando explícito da cozinha ("fritei 40, 38 boas"), como "congela 200 do lote de hoje" no design §6.2; o lote vem de `lotes_para_fritar` e é **dito** na repetição; se o produto ou a conservação for ambíguo, pergunta |
| `vender` | **2** | `registrar_venda` | dinheiro + baixa de estoque; numa cozinha barulhenta "2" e "12", "caixa" e "unidade" se confundem, e desfazer manda para perda (RN-36). O "Confirma?" lê apresentação, quantidade, preço, total e condição do retorno simulado. Ver Q1 (o design punha nível 1) |
| `nova_encomenda` | **2** | `criar_encomenda` | reserva estoque, guarda preço, dia e sinal; dia e quantidade mal ouvidos custam caro |
| `entregar_encomenda` | **2** | `entregar_encomenda` | baixa estoque e fecha o dinheiro (saldo à vista ou a prazo) |
| `cancelar_venda`, `cancelar_encomenda` | **2** | idem | sem volta; "qual venda" precisa ser repetida |
| `registrar_perda` | **2** | `registrar_perda` | estoque sai sem volta; design §6.2 põe "registrar sobra como perda" em "mostra e espera o ok" |
| `registrar_recebimento` | **2** | `registrar_recebimento` | mesmo critério de `registrar_pagamento` (Plano 3, Q1): dinheiro e cliente certo |
| `estornar_recebimento` | **2** | `estornar_recebimento_cliente` | desfaz uma anotação de dinheiro |
| `salvar_preco` | — (só tela) | `salvar_apresentacao` | Q10: preço por voz fica para depois |
