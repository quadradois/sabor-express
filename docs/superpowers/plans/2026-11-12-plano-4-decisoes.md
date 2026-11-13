# Plano 4 — Caixa de decisões, resumo do dia e sugestões do sistema — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O dono abre a tela (ou pergunta ao Monsieur EscofIA "o que tem para decidir?" / "como está o dia?") e encontra, guardado e em dia, tudo que pede a atenção dele: o que venceu ou vence logo, o que está abaixo do mínimo, as contas vencidas e as que vencem, a compra que não chegou, o consumo pendente que já pode ser conciliado, os avisos de ajuste e a sugestão de rever uma ficha quando as últimas produções renderam diferente do previsto. O que tem uma operação pronta ele aprova com um "ok" (e ela roda uma vez só); o que não quer ele recusa dizendo por quê; o que é só aviso ele dá ciência. E pode perguntar "o que foi feito hoje?".

**Architecture:** App novo `decisoes` (a caixa é transversal: lê estoque, compras, financeiro e produção; por isso não fica em nenhum deles nem em `agente`). Modelo único `Decisao`. Serviços em `decisoes/servicos.py` sobre `executar()`; geradores puros em `decisoes/geradores.py` que só leem as consultas existentes e devolvem o "retrato" do que deveria estar na caixa; `servicos.sincronizar` grava o retrato (uma operação por gerador). Comando `manage.py rotina_diaria` roda tudo. Consultas puras em `decisoes/consultas.py`: a caixa, o resumo do dia e o histórico de operações. Três consultas novas de estoque em `estoque/servicos.py` (`porcoes`, `disponivel`, `itens_abaixo_do_minimo`).

**Tech Stack:** Python 3.12, uv, Django 5.2, SQLite, pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-10-19-agente-cozinha-design.md` (§6.2 alçada, §6.3.4 aprendizado por estatística, §6.6 telas 1 e 3, §6.7 trabalhos proativos, §10 RF-REL-01 → "Hoje" + caixa). Regras em `docs/prd/02-prd.md`: RF-ADM-02 (trilha), RF-EST-10 (vencido destacado até o destino), RF-OP-09 (previsto × realizado), RF-REL-01 (painel), RF-FIN-08, RN-03 (disponível), RN-19, RNF-16 (nada é apagado), fórmulas "Rendimento real = quantidade boa ÷ quantidade planejada" e "Estoque baixo = disponível < mínimo". Pendências herdadas: `2026-10-19-plano-2-pendencias.md` (proposta de ajuste de ficha pelo rendimento; troca de lote pela conversa), `2026-11-12-plano-3-pendencias-agente.md` (fornecedor com acento; contas a vencer no resumo da manhã), `2026-11-12-plano-3-pendencias-telas.md` (item 7: "Hoje" só com contagens).

## O que mudou em relação ao design (realidade da voz)

O design previa um agente de texto (tela e Telegram) com uma **fila de tarefas** que acorda o agente e o faz **mandar** o resumo da manhã. O agente que existe é de **voz** (Monsieur EscofIA, Gemini Live) e **só fala quando alguém fala com ele**: não consegue avisar por conta própria. Por isso:

- A "fila de tarefas" do design vira a **rotina** (`manage.py rotina_diaria`), um comando sem IA que a coordenação agenda. Ela não decide nada nem chama modelo: só atualiza a caixa com o que as consultas mostram.
- O "resumo da manhã" deixa de ser uma mensagem enviada e vira uma **consulta** (`resumo_do_dia`) que a tela "Hoje" mostra e que o agente lê quando o dono pergunta "como está o dia?".
- Tudo que o sistema percebe sozinho fica **guardado na caixa** até o dono decidir; a tela mostra e o agente lê quando perguntado ("o que tem para decidir?").
- Quando o Telegram entrar (Plano 5), ele lê a mesma caixa para empurrar avisos; nada aqui muda.

## Divisão do plano

| Fase | Quem | Entrega | Situação |
|---|---|---|---|
| **1 — Núcleo** | esta sessão | modelo, migração, serviços sobre `executar()`, geradores, comando, consultas, admin, testes | **feita** (Tasks 1–6) |
| **2a — Telas** | sessão paralela, só `web/` | caixa de decisões, "Hoje" com o resumo, histórico de operações (Tasks 7–9) | a fazer |
| **2b — Ferramentas MCP** | sessão paralela, só `agente/` e `docs/` do agente | ferramentas de leitura e decisão, instruções do agente de voz (Tasks 10–12) | **feita** (mais `ver_backup`) |

As fases 2a e 2b não mexem em modelo nem em serviço; se precisarem de algo do núcleo, pedem à coordenação. O contrato estável está no fim deste documento.

## Decisões deste plano (revisáveis pelo dono)

| Decisão | Por quê / custo se estiver errada |
|---|---|
| **Decisão separada da `agente.Proposta`**, no app `decisoes`; o **mecanismo** é o mesmo (operação + parâmetros guardados; aprovar chama o serviço com a `chave` da decisão, então repetir não executa de novo; recusa do núcleo mantém pendente). | A proposta é a confirmação imediata de uma conversa (5 min, criada pelo agente, mora na camada do agente); a decisão é criada pelo sistema, vive dias e precisa de assunto, vigência, origem e ciência. Reaproveitar `agente/propostas.py` faria o núcleo depender da camada do agente (que importa o núcleo). O código repetido é pequeno (uma chamada com `chave`). Na fase 2b o agente **usa** a proposta para pedir o "sim" antes de chamar `aprovar_decisao` (ver alçada). |
| **Aprovar roda a operação e a aprovação na mesma transação** (`executar("aprovar_decisao")` chama o serviço por dentro). | As duas gravam ou nenhuma: nunca fica "aprovada" sem ter executado nem executada sem estar aprovada. A tentativa recusada fica na trilha (`aprovar_decisao`, status "erro", `parametros.decisao_id`), e a consulta mostra o último erro — sem gravar fora do `executar()`. |
| **Aviso = decisão sem operação**; aprovar um aviso é "dar ciência". Aviso **não se recusa**. | O PRD e o design têm o "só avisa"; ciência registra quem viu e quando. |
| **Recusar exige motivo.** | Igual a todo estorno/cancelamento do sistema (RN-34). Por voz, o agente pergunta "por quê?" e aceita uma frase curta. |
| **Um assunto vigente por vez** (restrição única condicional no banco). Enquanto a situação existir, a rotina não recria — nem depois de recusada ou de ciência dada. Quando a situação some, a decisão deixa de ser vigente (pendente vira **sem efeito**); se voltar a acontecer, nasce outra. | Idempotência estrutural: rodar a rotina 10 vezes não duplica. O dono não é importunado de novo pelo que já respondeu (o resumo do dia continua mostrando tudo). |
| **Pendente tem texto e números atualizados** a cada rotina (ex.: o saldo baixou mais); operação e parâmetros **nunca** mudam — fazem parte do assunto (ex.: `conciliar:<pendência>:<lote>`). | O dono vê sempre o número de hoje; o que ele aprova é exatamente o que leu. O texto antigo de uma pendente não é guardado (não houve decisão sobre ele). |
| **Decisão com operação expira em 7 dias**; a rotina gera de novo se ainda valer, com números novos. Aviso não expira: vale enquanto a situação existir. | Evita aprovar, semanas depois, algo calculado com outro estoque. O núcleo checa as regras de novo ao aprovar de qualquer forma. |
| **Única operação aprovável hoje: `conciliar_consumo`** (registro `decisoes.servicos.OPERACOES`). | É a única que o design manda "mostrar e esperar o ok" e que o sistema consegue montar sozinho. Ajuste de ficha não tem serviço (o dono edita pelo admin, que versiona — RN-14); descarte de vencido não existe ainda. Plano 5 acrescenta a compra lida de cupom. |
| **Conciliação proposta com o lote de validade mais próxima que cubra tudo** (`lotes_possiveis[0]`); sem lote que cubra, vira aviso. | FEFO (RN-18) e "um lote só" (Q8 do Plano 3). |
| **Sugestão de ficha só sugere, com os números**, nunca muda a ficha. Critério conservador: as **5 últimas produções concluídas da versão atual da ficha**, **todas** desviando **para o mesmo lado** em mais de **5 %** no rendimento (boas ÷ planejadas, PRD) ou em mais de **10 %** no uso de um ingrediente (usado ÷ previsto, somado por item). Uma produção dentro da faixa quebra a sequência. | Design §6.3.4 ("estatística, não IA"; "diferença consistente"). Contar só a versão atual faz a sugestão sumir quando o dono ajusta a ficha e não voltar até haver 5 produções novas. |
| **Disponível = saldo − vencido** (`estoque.servicos.disponivel`); reservas entram com as encomendas (Plano 6). | RN-03 e a fórmula de "estoque baixo" do PRD. A consulta antiga do agente (`agente.consultas.estoque`) ainda compara o saldo bruto; ver pendências. |
| **Janelas:** vencendo = até 3 dias (como a consulta de validades do agente); conta a vencer na caixa = até 3 dias, no resumo = 7 dias (como a tela Hoje); compra atrasada = 7 dias ou mais sem chegar tudo. Constantes no código (`decisoes/consultas.py`, `decisoes/geradores.py`). | Nenhum documento fixa esses números; ver perguntas Q1–Q3. Configuração pela tela é RF-ADM-03 (depois). |
| **Uma operação do núcleo por gerador** (`gerar_decisoes`, `parametros.origem`); a falha de um gerador não impede os outros e o comando sai com erro. | Trilha legível; um bug num gerador não esvazia a caixa. |
| **Histórico = consulta à trilha (`RegistroOperacao`)** com rótulos em português (`ROTULOS`); filtros por igualdade. | RF-ADM-02; serve à tela e a "o que foi feito hoje?". |
| **Fornecedor repetido ignorando acento e caixa** (pendência do Plano 3): `salvar_fornecedor` compara o nome normalizado em Python. | "ATACADÃO" e "Atacadao" agora são recusados ao lado de "Atacadão". |

## Global Constraints

- Tudo dos Planos 1 a 3 continua valendo: Decimal sempre; dinheiro 2 casas; `ROUND_HALF_UP`; toda gravação por `executar()`; nada é apagado (RN-34, RNF-16).
- Geradores e consultas **não gravam** e **não repetem regra**: usam `porcoes`, `itens_abaixo_do_minimo`, `contas_vencidas`, `contas_a_vencer`, `compras_em_aberto`, `consumos_pendentes`, `avisos_de_ajuste` e os dados de `Producao`/`LinhaPreparo`.
- Aprovar executa **uma única vez** (chave da decisão); aprovar de novo devolve o resultado guardado.
- A rotina é idempotente e pode rodar a qualquer hora, quantas vezes for.
- Textos em pt-BR, em frases curtas que o agente pode ler em voz alta; dinheiro por `dinheiro`, quantidades por `quantidade`.

## Review Focus

- Aprovar duas vezes (com e sem a mesma chave) → uma conciliação, um movimento (`test_aprovar_executa_a_operacao_uma_unica_vez`, `test_aprovar_com_a_mesma_chave_nao_duplica`).
- Núcleo recusa na aprovação (o lote foi usado) → continua pendente, nada gravado, erro visível; a rotina seguinte troca a proposta por um aviso (`test_recusa_do_nucleo_mantem_pendente_e_fica_na_trilha`).
- Rotina duas vezes → nada duplicado; situação resolvida → sem efeito (`test_rotina_e_idempotente_e_situacao_resolvida_fica_sem_efeito`).
- Recusada não volta enquanto a situação existir (`test_recusar_guarda_o_motivo_e_nao_volta_enquanto_a_situacao_existir`).
- Expirada sai da caixa antes mesmo de a rotina marcar, e volta nova (`test_expirada_sai_da_caixa_e_a_rotina_gera_de_novo`).
- Sugestão de ficha: 4 produções não bastam; uma produção normal quebra a sequência (`test_sugestao_de_ficha_pelo_rendimento`).

---

## Fase 1 — Núcleo (feita)

### Task 1: Fornecedor sem acento e sem caixa

**Files:** `cadastros/servicos.py`. Test: `tests/test_compras.py::test_fornecedor_repetido_ignora_acento_e_caixa`.

- [x] `salvar_fornecedor` compara o nome normalizado (sem acento, minúsculas, sem espaços nas pontas) com todos os outros fornecedores.

### Task 2: Consultas de estoque

**Files:** `estoque/servicos.py`.

- [x] `porcoes(item=None, ate=None, hoje=None)`: porções (lote + conservação) com saldo, validade, dias, vencido e valor.
- [x] `disponivel(item, hoje=None)` = saldo − vencido (RN-03).
- [x] `itens_abaixo_do_minimo(hoje=None)`.

### Task 3: Caixa de decisões

**Files:** `decisoes/models.py`, `decisoes/servicos.py`, `decisoes/admin.py`, `decisoes/migrations/0001_initial.py`, `sabor/settings.py`. Test: `tests/test_decisoes.py`.

- [x] `Decisao` (origem, assunto, vigente, texto, detalhes, operação + parâmetros, situação, chave, quem criou/decidiu, motivo, operação executada e resultado).
- [x] `criar_decisao`, `aprovar_decisao`, `recusar_decisao`, `expirar_decisoes`, `sincronizar`.
- [x] Admin só leitura.

### Task 4: Geradores e rotina

**Files:** `decisoes/geradores.py`, `decisoes/management/commands/rotina_diaria.py`.

- [x] `lotes_vencidos`, `lotes_vencendo`, `estoque_baixo`, `contas_vencidas`, `contas_a_vencer`, `recebimento_atrasado`, `consumo_pendente` (decisão com `conciliar_consumo` ou aviso), `avisos_ajuste`, `ficha_rendimento`.
- [x] `rodar_rotina` e `manage.py rotina_diaria [--data AAAA-MM-DD]`.

### Task 5: Resumo do dia e histórico

**Files:** `decisoes/consultas.py`.

- [x] `decisoes`, `detalhe_decisao`, `contar_pendentes`, `resumo_do_dia`, `historico_operacoes`, `ROTULOS`.

### Task 6: Fechamento da fase

- [x] `uv run pytest` verde (284); `makemigrations --check` sem mudanças.

---

## Fase 2a — Telas (`web/`)

Padrão das telas existentes: login obrigatório, `{% chave %}` em todo POST, `RegraViolada` mostrada sem perder o que foi digitado, botões de 44 px, sem rolagem horizontal a 360 px. A tela nunca calcula: totais vêm de `resumo_do_dia`.

### Task 7: Caixa de decisões
- [ ] Lista das pendentes (`decisoes()`): decisões (com operação) em cima, avisos embaixo; cada item com o texto, a origem em português, há quanto tempo e, se houver, o último erro ("Não deu para aprovar: …").
- [ ] Decisão: botões **Aprovar** → `aprovar_decisao` e **Recusar** (pede motivo) → `recusar_decisao`. Aviso: botão **Ciente** → `aprovar_decisao`.
- [ ] Filtro "decididas" (`decisoes(situacao=None)`) mostrando quem decidiu, quando, motivo e situação.
- [ ] Links para a tela de origem pelos `detalhes` (lote, compra, conta, produção, consumos pendentes).
- [ ] Test: aprovar uma conciliação grava uma vez (dois POSTs com a mesma chave), recusar sem motivo mostra a mensagem, ciente tira o aviso da lista.

### Task 8: "Hoje" com o resumo do dia
- [ ] Trocar as contagens de `web.views.inicio` por `resumo_do_dia()`: blocos de validade (vencidos e vencendo, com o valor), estoque baixo, contas (vencidas, a vencer, total devido), a chegar (atrasadas destacadas), produções em andamento e com custo pendente, consumos pendentes, avisos de ajuste e o número de itens na caixa (link). Cada bloco leva à tela de detalhe (RF-REL-01, CA-31).
- [ ] Design §6.6: a caixa é a tela inicial. Sugestão: "Hoje" começa pela caixa (pendentes) e segue com o resumo.

### Task 9: Histórico de operações
- [ ] Lista de `historico_operacoes` com filtros de período (padrão: hoje), autor, canal e operação (lista de `ROTULOS`), e só erros. Mostra o rótulo, quem, canal, hora e, aberto, os parâmetros e o resultado/erro.

---

## Fase 2b — Ferramentas MCP e instruções do agente de voz (`agente/`)

Padrão de `agente/ferramentas.py` (nível 0 lê, 1 faz e repete, 2 cria `Proposta` simulada e espera o "sim"). Na voz, o agente **não lê ids**: diz "a primeira", "a do queijo", e guarda o id para a chamada.

### Task 10: Leitura (nível 0)
- [x] `ver_resumo_do_dia` → `resumo_do_dia()` (o agente fala primeiro os totais, depois o que o dono pedir).
- [x] `ver_decisoes(tipo="")` → `decisoes(tipo=…)`; `ver_decisao(decisao_id)` → `detalhe_decisao`.
- [x] `ver_historico(periodo="hoje", autor="", canal="", operacao="")` → `historico_operacoes` (resposta curta: rótulo + hora + quem).

### Task 11: Decidir
- [x] `dar_ciencia(decisao_id)` nível 1 → `aprovar_decisao` em aviso; recusa decisão com operação ("isso precisa de aprovação").
- [x] `aprovar_decisao(decisao_id)` nível 2 → `propostas.propor("aprovar_decisao", …)`; o resumo repete o texto da decisão e os números da simulação; só `confirmar_proposta` grava. Registrar `aprovar_decisao` em `agente.propostas.OPERACOES`.
- [x] `recusar_decisao(decisao_id, motivo)` nível 1 → `recusar_decisao` (repete o que entendeu).
- [x] Testes no padrão de `tests/test_mcp_agente_escrita.py`: aprovar por voz não grava sem o "sim"; confirmar grava uma vez; ciência e recusa gravam e repetem.

### Task 12: Instruções do agente de voz
- [x] `docs/agente-instrucoes-decisoes.md` (no padrão de `docs/agente-instrucoes-compras.md`): "o que tem para decidir?" → `ver_decisoes`, diga quantas decisões e quantos avisos e leia **uma por vez**, decisões primeiro; "como está o dia?" → `ver_resumo_do_dia`, totais primeiro e no máximo três assuntos por fala; "o que foi feito hoje?" → `ver_historico`; nunca aprovar sem ter lido a decisão em voz alta naquela conversa; ao recusar, pergunte o motivo.
- [x] `docs/agente-mcp.md`: tabela das ferramentas novas.
- [ ] Opcional (não feito; ver `2026-11-12-plano-4-pendencias-agente.md`): `agente.consultas.estoque` e `validades` passam a usar `estoque.servicos.disponivel`/`porcoes` (ver pendências).

---

## Fora deste plano

- Agendamento da rotina (cron/systemd) — coordenação. Backup e restauração — sessão paralela (o alerta de backup no resumo, RF-ADM-06, entra depois dela).
- Telegram empurrando avisos da caixa — Plano 5. Compra lida de cupom como decisão — Plano 5 (acrescenta a operação em `OPERACOES`).
- Encomendas, reservas, vendas, sobras do dia (RF-FRI-03) e necessidade de produção — Plano 6 (entram no resumo e como geradores).
- Descarte de lote vencido, inventário e ajuste avulso — plano de estoque.
- Alçada ajustável pelo dono (design §6.2) e configuração das janelas (RF-ADM-03).
- Troca de lote pela conversa (pendência do Plano 2) — não é da caixa; fica para o plano do preparo por voz.

## Perguntas em aberto para o dono (com o padrão adotado)

| # | Pergunta | Padrão adotado até a resposta |
|---|---|---|
| Q1 | Com quantos dias de antecedência você quer ser avisado de uma conta para pagar? | **3 dias** na caixa. Na tela "Hoje" aparecem as da semana (7 dias). |
| Q2 | Um ingrediente ou salgado que vence em quantos dias já deve aparecer como "vence logo"? | **De hoje até daqui a 3 dias.** |
| Q3 | Depois de quantos dias uma compra que não chegou toda vira aviso? | **7 dias**. |
| Q4 | Quando as produções saem diferentes da ficha, quantas vezes seguidas precisam acontecer para o sistema sugerir rever a ficha, e quanto de diferença importa? | **5 produções seguidas** da ficha atual, todas para o mesmo lado: rendimento **5 %** abaixo ou acima, ou um ingrediente **10 %** a mais ou a menos. O sistema **só sugere**; quem muda a ficha é você. |
| Q5 | Para aprovar por voz algo que mexe no estoque ou no custo, o agente deve repetir e esperar seu "sim" antes de gravar? | **Sim, repete e espera o "sim"** (nível 2). "Ciente" de um aviso e "recusar" gravam direto, repetindo o que entendeu. |
| Q6 | Para recusar uma sugestão, você topa dizer o motivo em poucas palavras? | **Motivo obrigatório** ("vou comprar amanhã" serve). |
| Q7 | Uma sugestão com ação pronta (ex.: baixar o queijo do lote novo) deve valer por quanto tempo? | **7 dias**; se ainda fizer sentido, volta com os números de hoje. |
| Q8 | Depois que você deu ciência a um aviso (ex.: conta vencida), ele deve voltar a aparecer todo dia enquanto não resolver? | **Não volta na caixa** enquanto a situação for a mesma; continua aparecendo no resumo do dia. |
| Q9 | Em que horário a rotina deve rodar? | Sugestão para a coordenação: **antes do expediente (ex.: 6h) e de hora em hora** durante o dia (pode rodar quantas vezes for; não duplica). |
| Q10 | O sistema ainda não tem "descartar lote vencido". Até ter, tudo bem o aviso ficar até você dar ciência? | **Sim**: aviso até a ciência; o descarte entra no plano de estoque. |
| Q11 | Para saber se algo está abaixo do mínimo, o que já venceu conta como "não tenho"? | **Sim** (regra do PRD): vencido não conta. |
| Q12 | Para conciliar um consumo pendente, o sistema pode sugerir o lote que vence primeiro e cobre tudo? | **Sim**; sem lote que cubra tudo, só avisa. |

## Contrato para a fase 2

Serviços: argumentos **keyword-only**, terminando em `autor`, `canal="web"`, `chave=None`; gravam por `executar()` (idempotentes por `chave`); devolvem o dict do `executar()` (Decimal, data e hora viram texto); recusas levantam `nucleo.operacoes.RegraViolada` com mensagem em pt-BR para mostrar ou falar ao dono. Consultas não gravam e devolvem Decimal/date/datetime.

### Serviços (`decisoes.servicos`)

| Serviço | Parâmetros | Retorno | Recusas principais |
|---|---|---|---|
| `criar_decisao` | `origem`, `texto`, `assunto=""` (vazio = único), `operacao=""` (vazio = aviso), `parametros=None`, `detalhes=None`, `expira_em=None` | `{decisao_id, criada, situacao}` (`criada=False` se já há vigente com o assunto) | sem origem; sem texto; operação fora de `OPERACOES`; operação sem parâmetros |
| `aprovar_decisao` | `decisao_id` | `{decisao_id, situacao: "aprovada", tipo, operacao, texto, resultado}` (`resultado` = retorno do serviço executado; `None` em aviso) | não encontrada; já recusada ("…por X (motivo)"); não vale mais (expirada/sem efeito/prazo); qualquer recusa do serviço executado (a decisão continua pendente). Já aprovada: devolve o resultado guardado, sem erro |
| `recusar_decisao` | `decisao_id`, `motivo` | igual, com `situacao: "recusada"` | aviso ("Aviso não se recusa: dê ciência."); sem motivo; já decidida; não vale mais |
| `expirar_decisoes` | `agora=None` | `{expiradas}` | — (rotina) |
| `sincronizar` | `origem`, `itens=[{assunto, texto, detalhes?, operacao?, parametros?, expira_em?}]` | `{origem, criadas, atualizadas, sem_efeito, pendentes}` | igual a `criar_decisao` (nada grava) — uso da rotina e de geradores futuros |
| `OPERACOES` | `{"conciliar_consumo": …}` | operações que uma decisão pode executar | — |

`decisoes.geradores.rodar_rotina(hoje=None)` → `{hoje, expiradas, geradores: {origem: resultado de sincronizar | {erro}}}`; `manage.py rotina_diaria [--data AAAA-MM-DD]` (sai com erro se algum gerador falhar).

Origens (para rótulos na tela): `lotes_vencidos`, `lotes_vencendo`, `estoque_baixo`, `contas_vencidas`, `contas_a_vencer`, `recebimento_atrasado`, `consumo_pendente`, `avisos_ajuste`, `ficha_rendimento`; outras vêm de `criar_decisao` (ex.: `agente`).

`detalhes` de cada origem (para links): porção (`lote_id`, `item_id`, `estado`, `validade`, `saldo`, `valor`) · item (`item_id`, `disponivel`, `minimo`, `falta`) · parcela (`parcela_id`, `conta_id`, `compra_id`, `saldo`, `vencimento`) · compra em aberto (`compra_id`, `pendentes`) · consumo pendente (`pendente_id`, `producao_id`, `lotes_possiveis`) · aviso de ajuste (`aviso_id`, `conta_id`, `compra_id`) · ficha (`produto_id`, `ficha_id`, `versao`, `producoes: [{producao_id, unidades, boas, perdas, rendimento}]`, `rendimento_medio`, `ingredientes: [{item_id, item, razoes, media}]`).

### Consultas (sem gravar)

| Consulta | Parâmetros | Retorno |
|---|---|---|
| `decisoes.consultas.decisoes` | `situacao="pendente"` (`None` = todas), `origem=None`, `tipo=None` ("decisao"/"aviso"), `limite=None` | `[{decisao_id, origem, assunto, tipo, texto, detalhes, operacao, parametros, situacao, vigente, criada_em, criada_por, canal, expira_em, decidida_em, decidida_por, motivo, resultado, ultimo_erro: {quando, erro, autor} \| None}]`. Pendentes: decisões antes dos avisos, mais antigas primeiro, sem as que passaram do prazo; demais: mais recentes primeiro |
| `decisoes.consultas.detalhe_decisao` | `decisao_id` | o mesmo dict, ou `None` (situação "expirada" já aparece quando o prazo passou) |
| `decisoes.consultas.contar_pendentes` | — | `{total, decisoes, avisos, por_origem: {origem: n}}` |
| `decisoes.consultas.resumo_do_dia` | `hoje=None`, `dias_validade=3`, `dias_contas=7` | `{hoje, validade: {dias, vencidos, vencendo, valor_vencido, valor_vencendo}, estoque_baixo, contas: {dias, vencidas, a_vencer, total_vencido, total_a_vencer, total_devido}, a_chegar: {compras, atrasadas: [compra_id]}, producoes: {em_andamento: [{producao_id, produto, unidades, forma, etapa_atual, etapas, iniciada_em}], custo_pendente: [producao_id]}, consumos_pendentes, avisos_de_ajuste, decisoes, totais: {lotes_vencidos, lotes_vencendo, itens_abaixo_do_minimo, contas_vencidas, contas_a_vencer, valor_contas_vencidas, valor_contas_a_vencer, compras_a_chegar, compras_atrasadas, producoes_em_andamento, producoes_custo_pendente, consumos_pendentes, avisos_de_ajuste, decisoes_pendentes, avisos_pendentes, operacoes_hoje}}`. As listas são as das consultas de origem (`porcoes`, `itens_abaixo_do_minimo`, `contas_*`, `compras_em_aberto`, `consumos_pendentes`, `avisos_de_ajuste`, `decisoes`) |
| `decisoes.consultas.historico_operacoes` | `de=None`, `ate=None` (dias, inclusive), `autor=""`, `canal=""`, `nome=""`, `status=""` ("sucesso"/"erro"), `limite=200` (`None` = sem limite) | `[{operacao_id, criado_em, nome, rotulo, canal, autor, status, parametros, resultado, erro}]`, mais recentes primeiro |
| `decisoes.consultas.ROTULOS` | — | `{nome da operação: rótulo em português}` |
| `estoque.servicos.porcoes` | `item=None`, `ate=None`, `hoje=None` | `[{lote_id, item_id, item, unidade_base, codigo, estado, validade, dias, vencido, saldo, valor}]` da validade mais próxima |
| `estoque.servicos.disponivel` | `item`, `hoje=None` | Decimal (saldo − vencido) |
| `estoque.servicos.itens_abaixo_do_minimo` | `hoje=None` | `[{item_id, item, tipo, unidade_base, disponivel, minimo, falta}]`, do que proporcionalmente mais falta |

### Telas sugeridas (fase 2a)

Caixa de decisões (pendentes e decididas; aprovar, recusar com motivo, ciente) · "Hoje" com o resumo do dia (começando pela caixa, design §6.6) · Histórico de operações (filtros de período, autor, canal, operação, só erros).

### Ferramentas MCP sugeridas (fase 2b)

| Ferramenta | Nível | Serviço / consulta | Por quê |
|---|---|---|---|
| `ver_resumo_do_dia` | 0 | `resumo_do_dia` | só lê |
| `ver_decisoes`, `ver_decisao` | 0 | `decisoes`, `detalhe_decisao` | só lê |
| `ver_historico` | 0 | `historico_operacoes` | só lê ("o que foi feito hoje?") |
| `dar_ciencia` | 1 | `aprovar_decisao` (só aviso) | não mexe em estoque nem dinheiro; marca quem viu |
| `recusar_decisao` | 1 | `recusar_decisao` | não executa nada; o pior caso de um "recusa" mal ouvido é a sugestão sair da caixa (o resumo do dia continua mostrando a situação) |
| `aprovar_decisao` | **2** | `aprovar_decisao` via `Proposta` | **executa uma operação** (hoje: baixa de estoque e custo da conciliação). Numa cozinha barulhenta, "aprova" pode ser mal ouvido ou ir para a decisão errada ("a primeira" × "a segunda"); o agente repete o texto da decisão com os números da simulação e só grava com o "sim" (`confirmar_proposta`). Design §6.2: conciliação "mostra e espera o ok". |
