# PRD — Sistema de Gestão de Produção e Vendas de Salgados

## 1. Identificação

| Campo | Valor |
|---|---|
| Documento | PRD — Documento de Requisitos do Produto |
| Versão | 1.0 — aprovada (conteúdo da v0.2, com as propostas revisadas em DEC-F2-036 a 047) |
| Data | 18/10/2026 |
| Status | **Aprovado pelo proprietário em 18/10/2026** |
| Base | PVD v1.1 (aprovado com ressalvas — DEC-F2-001); decisões DEC-F1-001 a 004 e DEC-F2-001 a 047 (`01-registro-decisoes.md`); diagnóstico (`00-diagnostico-pvd.md`) |
| Idioma | Português brasileiro |

**Convenções**

- `RF-<MÓD>-nn` requisito funcional · `RN-nn` regra de negócio · `RNF-nn` requisito não funcional · `CA-nn` critério de aceite · `PR-nn` pendência residual.
- Prioridade MoSCoW: **M** (Must), **S** (Should), **C** (Could), **W** (Won't nesta versão).
- Na v0.1, as regras que o PVD e as decisões não fixavam estavam marcadas como "(proposta)". Todas foram revisadas e viraram as decisões DEC-F2-036 a 047. Todo requisito decorre agora do PVD ou de uma decisão registrada.
- "Operador" é o único usuário do MVP (proprietário).

---

## 2. Resumo executivo e objetivos

Aplicação web responsiva, em rede local, com serviço central e banco SQLite acessado apenas por esse serviço. Ela substitui planilhas e anotações na gestão de uma pequena produção de salgados: compras e recebimento, estoque por lote, fichas técnicas compostas, produção, fritura, conservação e etiquetas internas, vendas, encomendas, custos e contas a pagar e a receber.

O produto se apoia em quatro garantias:

1. **Nada muda o estoque ou o dinheiro sem um evento explícito e rastreável.** Saldos são derivados de movimentos e correções são feitas por estorno.
2. **O passado não é reescrito.** Custo de lote, preço de venda e versão de ficha são fixados quando o fato acontece.
3. **Automação supervisionada.** Importação e recorrências preparam lançamentos; somente o operador os efetiva.
4. **Nenhum efeito em duplicidade.** Reenvios, repetições e duplo clique não geram compra, movimento ou pagamento duplicados.

**Objetivos (PVD §4) e como o PRD os mede**

| Obj. | Objetivo | Indicador de verificação |
|---|---|---|
| O1 | Centralizar compras, estoque, receitas, produção, vendas, custos e financeiro | Todos os fluxos do §8 executáveis no sistema sem planilha auxiliar |
| O2 | Automatizar entrada de documentos de compra | Foto de cupom gera compra em revisão com itens pré-preenchidos (CA-05) |
| O3 | Padronizar receitas, rendimentos e custos | Fichas versionadas com custo estimado calculado (CA-14) |
| O4 | Registrar consumo real e produção efetiva | OP concluída com consumo, quantidade boa e perdas (CA-16) |
| O5 | Controlar frescos, resfriados e congelados | Saldo por estado de conservação dentro do lote (CA-20) |
| O6 | Etiquetas a partir de dados reais | Etiqueta gerada do lote, com registro de impressão (CA-22) |
| O7 | Reduzir perdas e melhorar planejamento | Alertas de estoque mínimo, validade e necessidade de produção (CA-27) |
| O8 | Custos e margens transparentes | Custo estimado × real com critério exibido (CA-33) |
| O9 | Preservar histórico | Alteração de preço ou ficha não altera lote concluído (CA-15) |
| O10 | Evoluir sem reescrever | RF-EXT atendidos |
| O11 | Controlar despesas, contas, vencimentos e pagamentos | Contas a pagar e a receber com parcelas, parcial e estorno (CA-35 a CA-38) |

---

## 3. Problema, público e cenários de uso

**Problema (PVD §2):** informação espalhada entre notas, planilhas e anotações impede conhecer custo real, controlar validade e lotes, planejar compras e acompanhar o financeiro.

**Público do MVP:** um operador, que é o proprietário e acumula compra, produção, estoque, venda e financeiro. Ele usa o sistema no computador do escritório, no tablet ou celular da cozinha e no celular durante as compras (Telegram).

**Cenários principais**

| ID | Cenário | Contexto |
|---|---|---|
| S1 | Compra no atacarejo | Fotografa o cupom e envia pelo Telegram. Ao chegar, revisa, aprova e confirma o recebido. |
| S2 | Fornecedor entrega a menos | Registra o recebido; a diferença fica pendente até chegar ou ser encerrada. |
| S3 | Dia de produção | Cria a OP de massa, depois a de coxinha (que consome a massa produzida), conclui com a quantidade boa e etiqueta. |
| S4 | Congelar parte do lote | Transfere 200 de 250 unidades para congelado e etiqueta o que foi congelado. |
| S5 | Fritura do balcão | Registra rapidamente 40 unidades fritas do lote cru X; no fim do dia, registra as sobras. |
| S6 | Encomenda de festa | Confirma uma encomenda para sábado; o sistema reserva o disponível e mostra o que falta produzir. |
| S7 | Venda no atacado a prazo | Vende 10 caixas com preço de atacado; gera recebível em 2 parcelas. |
| S8 | Fechamento do mês | Consulta custo direto × pleno, margens estimadas, contas e estoque a vencer. |
| S9 | Erro de lançamento | Estorna o pagamento lançado errado e lança o correto. |
| S10 | Pane no servidor | Restaura o backup do dia anterior e verifica a integridade. |

---

## 4. Escopo do MVP

**Dentro do MVP:** módulos do §6, conforme o PVD §5, mais **contas a receber básicas** (ampliação aprovada, DEC-F2-018).

**Fora do MVP (W)**

| Item | Fonte |
|---|---|
| App nativo, acesso público pela internet, WhatsApp, multiempresa, portais, marketplaces, integração bancária, emissão fiscal, contabilidade completa, RH e folha | PVD §8 |
| Rótulos comerciais ao consumidor ou à revenda | PVD §8, DEC-F1-002 |
| Assistente de IA e voz (o MVP só cumpre os requisitos de extensibilidade RF-EXT) | DEC-F2-002 |
| Automação que efetiva lançamentos financeiros ou de estoque sem aprovação | PVD §8 |
| Múltiplos usuários e perfis (o modelo já registra autor) | PVD §3, §5.12 |
| Preço por cliente, cobrança, juros e multa automáticos, conciliação bancária | DEC-F2-020, 024 |
| Backup em nuvem | DEC-F2-034 |
| Produção automática a partir de encomenda | DEC-F2-019 |

---

## 5. Perfis e permissões

| Perfil | MVP | Permissões |
|---|---|---|
| Operador (proprietário) | Único perfil | Todas as operações, sempre autenticado (RF-ADM-01) |
| Remetente Telegram autorizado | Identidade de canal, não de usuário | Apenas enviar documentos para a fila de importação. Não aprova nem consulta nada. |
| Assistente futuro | Não existe no MVP | Receberá permissões por ferramenta (RF-EXT-03) |

Mesmo com um único usuário, todo evento grava **autor, data/hora e origem** (web, Telegram, sistema). Isso permite incluir perfis depois sem migrar o histórico (resolve C-05).

---

## 6. Mapa funcional

| Módulo | Sigla | Capacidades |
|---|---|---|
| Administração e segurança | ADM | Autenticação, configurações, auditoria, backup e restauração |
| Cadastros | CAD | Unidades e conversões, ingredientes e insumos, embalagens, preparações, produtos, apresentações e preços, fornecedores, clientes, categorias |
| Compras e importação | CMP | Lançamento manual, importação web e Telegram, extração, revisão, aprovação e rejeição, deduplicação |
| Recebimento | REC | Recebimento total ou parcial, complementar, encerramento de pendência |
| Estoque e lotes | EST | Movimentos, saldos por lote e estado, sugestão FEFO, ajustes, inventário, consumo pendente e conciliação |
| Fichas técnicas | FIC | Fichas simples e compostas, versões, custo estimado |
| Produção | OP | Ordens de produção, consumo, rendimento, perdas, lote produzido, custo real |
| Fritura | FRI | Registro rápido de fritura, sobras, troca de óleo |
| Conservação e etiquetas | ETQ | Transferência de estado, critérios de validade, etiquetas internas, reimpressão |
| Vendas e encomendas | VEN | Venda direta, atacado, encomendas, reservas, entrega, cancelamento e devolução |
| Custos | CUS | Custo de lote, estimado e real, indiretos por período, margem estimada |
| Financeiro | FIN | Contas a pagar e a receber, parcelas, pagamento parcial, recorrência, estorno, despesas |
| Relatórios e painel | REL | Dashboard, alertas, relatórios gerenciais |
| Integração Telegram | TLG | Bot privado, remetentes autorizados, confirmação |
| Extensibilidade | EXT | Operações de domínio auditáveis, preparo para assistente |

**Dependências entre módulos**

```
ADM ─┬─> CAD ─> CMP(manual) ─> REC ─> EST ─┬─> FIC ─> OP ─┬─> ETQ
     │                                     │              ├─> FRI
     │                                     │              └─> VEN ─> FIN(receber)
     │          CMP ─> FIN(pagar)          └─> CUS (depende de CMP, FIC, OP, FRI, VEN, FIN)
     │          CMP(importação) depende de CMP(manual) + TLG
     └─> REL depende de todos · EXT é transversal
```

---

## 7. Requisitos funcionais

Colunas: **P** = prioridade · **Origem** = PVD ou decisão · **Dep.** = dependência · **CA** = critério de aceite (§17).

### 7.1 Administração e segurança (ADM)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-ADM-01 | O sistema exige autenticação antes de qualquer tela ou operação. A sessão expira após um período de inatividade configurável. | M | PVD §7 | — | CA-01 |
| RF-ADM-02 | Todo evento que altera dados registra autor, data/hora, origem (web, Telegram, sistema), operação e identificadores afetados, em uma trilha de auditoria que não pode ser editada. | M | PVD §7, §5.12 | — | CA-02 |
| RF-ADM-03 | O operador configura: unidades e conversões, categorias de produto, categorias de custo, classificações financeiras, critérios de validade, modelos de etiqueta, estoque mínimo, referências de custo (óleo, indiretos), remetentes do Telegram e dados da operação. | M | PVD §5.12 | — | — |
| RF-ADM-04 | Backup automático diário, que copia banco e documentos de forma consistente para um destino configurado (disco externo ou outro computador da rede). | M | DEC-F2-034 | — | CA-03 |
| RF-ADM-05 | Backup manual sob demanda, feito automaticamente antes de qualquer restauração. | M | DEC-F2-034 | RF-ADM-04 | CA-03 |
| RF-ADM-06 | Alerta no painel quando o último backup bem-sucedido tiver mais de 24 h ou quando um backup falhar. | M | DEC-F2-034 | RF-ADM-04 | CA-03 |
| RF-ADM-07 | Restauração de um backup escolhido, seguida de verificação de integridade (RF-ADM-08) com relatório do resultado. | M | PVD §7, §9.12 | RF-ADM-05 | CA-04 |
| RF-ADM-08 | Verificação de integridade sob demanda: saldos derivados conferem com os movimentos; documentos referenciados existem; não há compra, movimento ou pagamento duplicado pela chave de idempotência. | M | PVD §9.12 | — | CA-04 |

### 7.2 Cadastros (CAD)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-CAD-01 | Cadastrar itens de estoque de tipo **ingrediente**, **insumo** (óleo, gás, materiais) ou **embalagem**, com unidade de controle, unidades de compra aceitas, fatores de conversão próprios, categoria, estoque mínimo, condição de armazenamento e se controla validade. | M | PVD §5.2, DEC-F2-028 | RF-CAD-02 | — |
| RF-CAD-02 | Conversões padrão fixas (kg↔g, L↔mL). Conversões entre naturezas diferentes (L↔kg, dúzia↔un, pacote↔g) só são permitidas com fator cadastrado no item; sem fator, o lançamento é bloqueado e o sistema informa o fator que falta. | M | DEC-F2-029 | — | CA-06 |
| RF-CAD-03 | Cadastrar **preparações** (massas, recheios, empanamentos) e **produtos finais**, com forma de produto (cru, frito, pré-frito, assado) e estados de conservação possíveis. | M | PVD §5.2, DEC-F2-011 | — | — |
| RF-CAD-04 | Cadastrar **apresentações comerciais** de um produto final: unidade, caixa ou kit, com quantidade de unidades físicas, embalagens consumidas por apresentação, preço de varejo e preço de atacado. | M | PVD §5.8, DEC-F2-020, 028 | RF-CAD-03 | CA-28 |
| RF-CAD-05 | Cadastrar fornecedores (nome, identificação fiscal opcional) e clientes (nome e contato, quando necessário para encomenda, atacado ou venda a prazo). | M | PVD §5.2 | — | — |
| RF-CAD-06 | Guardar **sinônimos** de item por fornecedor (descrição do documento → item), criados na revisão de importação e usados na correspondência automática. | M | DEC-F2-030 | RF-CMP-06 | CA-07 |
| RF-CAD-07 | Itens com histórico não são excluídos, apenas inativados. Itens inativos não aparecem em novos lançamentos e continuam visíveis no histórico. | M | PVD §6 | — | — |

### 7.3 Compras e importação (CMP)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-CMP-01 | Lançar compra manualmente: fornecedor, data, número ou chave do documento (opcional), itens (item, quantidade, unidade, valor), frete, desconto, acréscimo e total. | M | PVD §5.3 | RF-CAD-01 | CA-08 |
| RF-CMP-02 | Enviar documento pela interface web (foto ou arquivo). O arquivo original é armazenado e gera um registro de importação. | M | PVD §5.3 | RF-ADM-02 | CA-05 |
| RF-CMP-03 | Extrair automaticamente de **fotos de cupom fiscal**: fornecedor, identificação fiscal, data, itens, quantidades, unidades, valores, descontos, acréscimos, total e chave ou número. | M | PVD §5.3, DEC-F2-009 | RF-CMP-02 | CA-05 |
| RF-CMP-04 | Ler **XML de NF-e** localmente, sem serviço externo. | S | DEC-F2-009 | RF-CMP-02 | — |
| RF-CMP-05 | Extrair de **PDF/DANFE** (S) e por **QR Code da NFC-e** com consulta pública (C). | S/C | DEC-F2-009 | RF-CMP-03 | — |
| RF-CMP-06 | Fazer a correspondência dos itens extraídos com o cadastro (por sinônimo confirmado ou correspondência exata). Correspondências incertas ficam marcadas como "a confirmar" e nunca são aceitas sozinhas. | M | PVD §5.3, DEC-F2-030 | RF-CAD-06 | CA-07 |
| RF-CMP-07 | Na revisão, criar um item novo por cadastro rápido (nome, tipo, unidade, fator) a partir de uma linha não reconhecida, e salvar a descrição como sinônimo. | M | DEC-F2-030 | RF-CAD-01 | CA-07 |
| RF-CMP-08 | Comparar a soma dos itens (com frete, desconto e acréscimo) com o total do documento e destacar divergências. A aprovação com divergência exige justificativa. | M | PVD §5.3 | — | CA-09 |
| RF-CMP-09 | Fila de revisão com as importações aguardando ação, com a visualização do documento original ao lado dos dados extraídos. | M | PVD §5.3 | RF-CMP-02 | — |
| RF-CMP-10 | Aprovar uma compra é uma operação explícita e única. Ela registra autor e data e pede a condição de pagamento (paga na hora ou a prazo, com parcelas). | M | PVD §5.3, DEC-F2-006, 024 | RF-FIN-01 | CA-10 |
| RF-CMP-11 | Rejeitar uma importação com motivo. O documento e os dados extraídos continuam consultáveis. | M | PVD §5.3 | — | — |
| RF-CMP-12 | Impedir a efetivação duplicada: mesmo arquivo, mesma mensagem, mesma chave de documento ou segunda aprovação não geram uma segunda compra (RN-05). | M | PVD §5.3 | — | CA-11 |
| RF-CMP-13 | Calcular o custo unitário de cada linha com rateio de frete, desconto e acréscimo proporcional ao valor da linha, com impostos incluídos no valor pago (RN-20). | M | DEC-F2-008, 010 | — | CA-12 |
| RF-CMP-14 | Se a extração estiver indisponível ou falhar, o documento fica na fila com o status "falha na extração" e pode ser lançado manualmente a partir dele. | M | DEC-F2-009 | RF-CMP-01 | CA-13 |
| RF-CMP-15 | Cancelar uma compra aprovada com motivo, desde que não haja recebimento nem pagamento registrado. O cancelamento também cancela a obrigação vinculada. | S | DEC-F2-037 | RF-FIN-01 | — |

### 7.4 Recebimento (REC)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-REC-01 | Registrar o recebimento físico por linha: quantidade recebida, lote do fornecedor (ou "sem lote informado") e validade quando o item controla validade. Pode acontecer na mesma tela da aprovação, mas é registrado como evento distinto. | M | PVD §5.3, DEC-F1-001, 004 | RF-CMP-10 | CA-10 |
| RF-REC-02 | Somente a quantidade recebida entra no estoque. A diferença fica como **pendência de recebimento**, indisponível para uso. | M | DEC-F1-001 | RF-REC-01 | CA-10 |
| RF-REC-03 | Registrar uma entrega complementar contra uma pendência aberta, gerando uma nova entrada e um novo lote. | M | DEC-F2-007 | RF-REC-02 | CA-39 |
| RF-REC-04 | Encerrar a pendência como "não entregue" com motivo. Isso gera um alerta de ajuste manual na obrigação financeira, sem recalcular valores. | M | DEC-F2-007 | RF-REC-02 | CA-39 |
| RF-REC-05 | Listar compras com pendência de recebimento, com idade da pendência. | M | DEC-F2-007 | — | — |
| RF-REC-06 | Estornar um recebimento lançado errado, com motivo, somente se as unidades daquele lote ainda não tiverem sido consumidas, vendidas ou reservadas. | S | DEC-F2-037 | RF-EST-01 | — |
| RF-REC-07 | Registrar **devolução ao fornecedor**: saída de um lote recebido com motivo, mesmo que parte dele já tenha sido usada. Gera um alerta de ajuste manual na obrigação, sem recalcular valores. | S | DEC-F2-036 | RF-REC-01 | CA-41 |
| RF-REC-08 | O recebimento não aceita quantidade maior que a documentada. O excesso entra por ajuste "bonificação" a custo zero (novo lote) ou por nova compra, se for cobrado. | M | DEC-F2-038 | RF-EST-08 | CA-42 |

### 7.5 Estoque e lotes (EST)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-EST-01 | Todo saldo é derivado de movimentos. Não existe edição direta de saldo. | M | PVD §5.4 | — | CA-17 |
| RF-EST-02 | Tipos de movimento: entrada por compra, entrada por produção, consumo por produção ou fritura, saída por venda, perda/descarte, ajuste (avulso, de inventário ou bonificação), transferência de estado, devolução de cliente, devolução ao fornecedor e estorno. | M | PVD §5.4 | — | — |
| RF-EST-03 | Controlar o saldo por **item × lote × estado de conservação**, separando matérias-primas, insumos, embalagens, preparações e produtos finais. | M | PVD §5.4, DEC-F2-014 | — | CA-20 |
| RF-EST-04 | Mostrar para cada item o disponível, o reservado, o vencido e o pendente de conciliação. | M | PVD §5.4 | — | CA-29 |
| RF-EST-05 | Ao consumir, sugerir os lotes por menor validade e, em caso de empate ou sem validade, por entrada mais antiga. O operador pode trocar o lote, e a troca fica registrada. | M | DEC-F2-004, 032 | — | CA-18 |
| RF-EST-06 | Bloquear qualquer saída acima do saldo disponível. A única exceção é o **consumo pendente de conciliação**, com justificativa obrigatória, permitido apenas em consumo de produção ou fritura. | M | DEC-F2-005 | — | CA-19 |
| RF-EST-07 | Ao receber um item com consumo pendente, propor o vínculo com o lote recebido. A confirmação define lote e custo do consumo pendente uma única vez. | M | DEC-F2-033 | RF-EST-06 | CA-19 |
| RF-EST-08 | Ajuste avulso com motivo obrigatório (lista configurável mais texto livre). | M | PVD §5.4 | — | CA-17 |
| RF-EST-09 | Inventário: abrir uma contagem total ou parcial, informar quantidades por lote e estado, ver as diferenças e confirmar para gerar ajustes rastreados. | S | DEC-F2-031 | RF-EST-08 | CA-40 |
| RF-EST-10 | Lotes vencidos ficam indisponíveis para consumo, venda e reserva, e são destacados até receberem um destino (descarte). | M | PVD §5.4 | RF-ETQ-02 | CA-21 |
| RF-EST-11 | Consultar o histórico de movimentos por item, lote, período e tipo, com o documento de origem (compra, OP, venda, ajuste). | M | PVD §5.4, §6 | — | — |
| RF-EST-12 | Rastreabilidade em duas direções: do lote produzido até os lotes de ingrediente consumidos (incluindo "sem lote informado"), e do lote de ingrediente até os lotes e vendas em que foi usado. | M | DEC-F1-004 | RF-OP-05 | CA-23 |

### 7.6 Fichas técnicas (FIC)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-FIC-01 | Criar uma ficha para uma preparação ou um produto final, com componentes (itens de estoque e/ou preparações), quantidades e unidades, rendimento previsto, perda prevista, embalagens de produção e instruções. | M | PVD §5.5 | RF-CAD-03 | CA-14 |
| RF-FIC-02 | Calcular o custo estimado atual da ficha de forma recursiva pelas sub-receitas, usando o custo de referência atual de cada componente (RN-23). | M | PVD §5.5 | — | CA-14 |
| RF-FIC-03 | Impedir referência circular entre fichas. | M | DEC-F2-047 | — | CA-14 |
| RF-FIC-04 | Toda alteração de uma ficha em vigor gera uma nova versão. As versões anteriores ficam consultáveis e não são editáveis. | M | PVD §5.5 | — | CA-15 |
| RF-FIC-05 | Mudanças de preço atualizam o custo estimado das fichas dependentes e não alteram o custo de OPs concluídas. | M | PVD §5.5 | — | CA-15 |
| RF-FIC-06 | Um componente do tipo preparação é tratado como **teórico** no cálculo de custo estimado. Na produção, ele é sempre consumido do **estoque da preparação** (lote produzido), nunca dos ingredientes originais (RN-12). | M | PVD §5.5 | RF-OP-03 | CA-16 |

### 7.7 Produção (OP)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-OP-01 | Criar uma OP para uma preparação ou um produto, com a quantidade planejada. As quantidades previstas de componentes são calculadas pela ficha. | M | PVD §5.6 | RF-FIC-01 | CA-16 |
| RF-OP-02 | A OP planejada acompanha a versão vigente da ficha. Ao **iniciar**, a versão fica fixada. | M | DEC-F2-015 | RF-FIC-04 | CA-15 |
| RF-OP-03 | Na conclusão, as quantidades previstas e os lotes sugeridos (FEFO) vêm pré-preenchidos. O operador corrige o que foi diferente e informa a quantidade boa, as perdas e o estado de conservação inicial. | M | DEC-F2-016 | RF-EST-05 | CA-16 |
| RF-OP-04 | A conclusão é atômica e única: registra os consumos, a entrada do lote produzido e o custo real em uma só operação. Uma segunda tentativa não gera movimentos novos. | M | PVD §5.6 | RF-EST-01 | CA-16 |
| RF-OP-05 | Cada OP gera exatamente um lote próprio, com identificação única e vínculo aos lotes consumidos. | M | DEC-F1-004, DEC-F2-017 | — | CA-23 |
| RF-OP-06 | Custo real = soma do custo dos lotes consumidos + embalagens de produção + óleo de referência, quando aplicável. Custo unitário = custo real ÷ quantidade boa. Quantidade boa igual a zero exige confirmação e registra a perda total. | M | PVD §5.6, DEC-F2-022 | RF-CUS-01 | CA-16 |
| RF-OP-07 | Uma OP concluída não é editada. A correção é feita por um ajuste vinculado à OP, com motivo, que gera movimentos de correção. O custo original continua visível. | M | PVD §5.6 | — | CA-17 |
| RF-OP-08 | Cancelar uma OP não concluída com motivo. Como ela ainda não tem movimentos, nada no estoque muda. | M | DEC-F2-047 | — | — |
| RF-OP-09 | Mostrar o previsto × realizado por OP: consumo, rendimento, perdas e custo. | M | PVD §5.6, §5.11 | — | — |

### 7.8 Fritura (FRI)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-FRI-01 | Registro rápido de fritura: produto cru, lote de origem (sugerido por FEFO), quantidade frita e quantidade boa. Gera um lote frito vinculado ao lote de origem. | M | DEC-F2-012 | RF-EST-05 | CA-24 |
| RF-FRI-02 | Custo do lote frito = custo do cru consumido + óleo de referência por unidade frita. | M | DEC-F2-013, 023 | RF-CUS-01 | CA-24 |
| RF-FRI-03 | Lotes fritos do dia sem destino ao fim do expediente geram um alerta. O operador registra o destino das sobras: perda ou outro destino permitido por critério cadastrado (REG-02). | M | DEC-F2-012 | — | CA-24 |
| RF-FRI-04 | Registrar a troca de óleo: quantidade descartada, saída do estoque de óleo e cálculo da diferença entre o custo real do período e o custo apropriado aos lotes desde a troca anterior ("ajuste de óleo"). | M | DEC-F2-013, 023 | — | CA-25 |
| RF-FRI-05 | O pré-frito congelado é produzido por uma OP completa, cuja ficha consome o produto cru e o óleo. | M | DEC-F2-012 | RF-OP-01 | — |

### 7.9 Conservação, validade e etiquetas (ETQ)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-ETQ-01 | Transferir uma quantidade de um lote de um estado de conservação para outro (ex.: resfriado → congelado), total ou parcialmente, mantendo a identificação do lote. | M | DEC-F2-014 | RF-EST-03 | CA-20 |
| RF-ETQ-02 | Calcular a validade a partir do **critério cadastrado** para o produto e o estado (prazo e data-base). Sem critério, o operador informa a validade manualmente com justificativa, e ela fica marcada como "informada manualmente". O sistema nunca aplica um prazo padrão. | M | PVD §5.7 | RF-ADM-03 | CA-21 |
| RF-ETQ-03 | Gerar uma etiqueta interna a partir do lote e do estado: produto, lote, data de fabricação, validade, conservação, quantidade e campos configurados. | M | PVD §5.7 | RF-ETQ-02 | CA-22 |
| RF-ETQ-04 | Modelos de etiqueta configuráveis (campos e tamanho). | M | PVD §5.12 | — | — |
| RF-ETQ-05 | Registrar cada impressão e reimpressão (lote, estado, quantidade, data e autor). Reimprimir não altera dados do lote. | M | PVD §5.7 | — | CA-22 |
| RF-ETQ-06 | Etiquetas são exclusivamente internas. Nenhum modelo se apresenta como rótulo comercial. | M | DEC-F1-002 | — | — |
| RF-ETQ-07 | Imprimir em impressora térmica (o modelo e a interface dependem de PR-03). O fallback é gerar um arquivo imprimível. | M | PVD §5.7 | — | — |

### 7.10 Vendas e encomendas (VEN)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-VEN-01 | Registrar uma venda direta: apresentações, quantidades, tabela (varejo ou atacado), desconto manual registrado com preço original, cliente opcional, forma de pagamento e situação (paga ou a prazo). | M | PVD §5.8, DEC-F2-020 | RF-CAD-04 | CA-28 |
| RF-VEN-02 | Converter cada apresentação vendida em unidades físicas e embalagens consumidas, com baixa por lote (FEFO sugerido) e estado de conservação. | M | PVD §5.8, DEC-F2-028 | RF-EST-05 | CA-28 |
| RF-VEN-03 | Gravar na linha da venda o preço praticado, o fator de conversão e o custo dos lotes baixados. Mudanças posteriores de tabela ou cadastro não alteram a venda. | M | PVD §6 | — | CA-28 |
| RF-VEN-04 | Uma venda a prazo gera um recebível vinculado, com uma ou mais parcelas. | M | DEC-F2-018, 024 | RF-FIN-06 | CA-37 |
| RF-VEN-05 | Criar uma encomenda: cliente, data e forma de entrega ou retirada, itens e estado de conservação pedido. | M | PVD §5.8 | — | CA-26 |
| RF-VEN-06 | Ao confirmar a encomenda, o sistema reserva o saldo disponível e mostra a **necessidade de produção** do que falta. Nenhuma OP é criada automaticamente. O operador pode gerar uma OP a partir da necessidade. | M | DEC-F2-019 | RF-EST-04 | CA-26, CA-27 |
| RF-VEN-07 | Reservas não podem ser consumidas por outra venda. Quando entra saldo de um produto com reserva parcial pendente, o sistema avisa e o operador completa a reserva com uma confirmação. Não há preenchimento automático. | M | DEC-F2-019, 040 | — | CA-26 |
| RF-VEN-08 | Separar e entregar a encomenda: converte a reserva em saída por venda e gera recebível ou pagamento. | M | PVD §5.8 | RF-VEN-02 | CA-26 |
| RF-VEN-09 | Cancelar uma encomenda ou venda **antes da saída** libera a reserva. Cancelar **depois da saída** ou registrar uma devolução tem como destino padrão a perda; o operador pode devolver ao lote de origem com motivo, se o lote não estiver vencido. | M | DEC-F2-021 | — | CA-30 |
| RF-VEN-10 | O cancelamento ou a devolução gera o reflexo financeiro por estorno: cancelamento do recebível em aberto ou registro de devolução de valor. | M | DEC-F2-021, 027 | RF-FIN-09 | CA-30 |
| RF-VEN-11 | Listar pedidos pendentes, atendidos e cancelados e as próximas entregas. | M | PVD §5.8 | — | — |

### 7.11 Custos (CUS)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-CUS-01 | O custo de consumo usa o custo do lote consumido. Itens sem lote informado usam a média ponderada móvel do saldo sem lote do item. | M | DEC-F2-003 | — | CA-12, CA-16 |
| RF-CUS-02 | O custo de produção com consumo pendente fica com o status "custo pendente" até a conciliação. | M | DEC-F2-033 | RF-EST-07 | CA-19 |
| RF-CUS-03 | Configurar categorias de custo e despesa com método de apropriação (fixo, percentual, por unidade, por lote, por pedido, por período). | M | PVD §5.9 | — | — |
| RF-CUS-04 | Ratear mão de obra, energia, gás e demais indiretos de fabricação nos relatórios do período (RN-24). O custo dos lotes não é alterado. | M | DEC-F2-022 | RF-FIN-02 | CA-34 |
| RF-CUS-05 | O custo estimado da ficha inclui os valores de referência configuráveis por unidade para indiretos e óleo, e os mostra separados do custo de ingredientes. | M | DEC-F2-022, 013 | RF-FIC-02 | CA-14 |
| RF-CUS-06 | A margem por produto é exibida sempre com o rótulo "estimada" e a lista do que está e do que não está incluído. | M | PVD §5.9 | — | CA-33 |
| RF-CUS-07 | Separar custos de fabricação, despesas comerciais, despesas operacionais e recuperação de investimento. Uma compra de item estocável nunca é contada como despesa. | M | PVD §5.9, DEC-F2-006 | — | CA-34 |

### 7.12 Financeiro (FIN)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-FIN-01 | Aprovar uma compra cria uma obrigação vinculada pelo valor do documento: "paga na hora" (já quitada, com forma e data de pagamento) ou "a prazo" (com parcelas). | M | DEC-F2-006 | — | CA-10 |
| RF-FIN-02 | Lançar despesas operacionais avulsas com classificação, valor, competência, vencimento e situação. | M | PVD §5.10 | — | CA-35 |
| RF-FIN-03 | Dividir obrigações e recebíveis em parcelas com valor e vencimento. A soma das parcelas deve ser igual ao total. | M | DEC-F2-024 | — | CA-36 |
| RF-FIN-04 | Registrar o pagamento total ou parcial de uma parcela, com data, forma e diferença classificada (juros, multa ou desconto) com motivo. | M | DEC-F2-025 | — | CA-36 |
| RF-FIN-05 | Cadastrar despesas recorrentes. O sistema gera a conta do período como **prevista**; ela só vira obrigação quando o operador confirma ou ajusta. | S | DEC-F2-026 | — | CA-38 |
| RF-FIN-06 | Recebíveis de venda a prazo: registro de recebimento total ou parcial e consulta de pendentes e vencidos. | M | DEC-F2-018 | — | CA-37 |
| RF-FIN-07 | Situação de cada conta e parcela: prevista, em aberto, parcialmente paga, paga, cancelada. "Vencida" é derivada (em aberto ou parcial com vencimento passado). | M | PVD §5.10 | — | CA-36 |
| RF-FIN-08 | Alerta de ajuste quando uma pendência de recebimento for encerrada como não entregue (RF-REC-04). | M | DEC-F2-007 | — | CA-39 |
| RF-FIN-09 | Corrigir lançamentos financeiros somente por estorno com motivo. O original continua visível e a conta volta ao estado anterior. | M | DEC-F2-027 | — | CA-38 |
| RF-FIN-10 | Consultar despesas, obrigações, recebíveis e pagamentos por período, situação, classificação, fornecedor ou cliente. | M | PVD §5.10 | — | — |

### 7.13 Relatórios e painel (REL)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-REL-01 | O painel mostra vendas do dia e do período, encomendas pendentes e próximas entregas, OPs abertas, importações aguardando revisão, estoque abaixo do mínimo, lotes a vencer e vencidos, divergências e alertas abertos, contas a pagar e a receber vencidas e a vencer, e o status do backup. Cada item leva à tela de detalhe. | M | PVD §5.1 | — | CA-31 |
| RF-REL-02 | Relatórios: compras por fornecedor e período; evolução de preço por item; estoque atual e movimentos; vencimentos; produção prevista × realizada; consumo e perdas; custo previsto × real; vendas por produto, período e tabela (varejo/atacado); encomendas; margens estimadas; despesas e pagamentos; contas a pagar e a receber por vencimento. Todos com filtros de data e, quando pertinente, de produto ou item. | M | PVD §5.11 | — | CA-32 |
| RF-REL-03 | Relatório do custo do período: custo direto dos lotes, indiretos rateados, ajuste de óleo e custo pleno gerencial, com o critério de rateio exibido. | M | DEC-F2-022, 023 | RF-CUS-04 | CA-34 |
| RF-REL-04 | Exportar em CSV os relatórios financeiros e de compras. | S | DEC-F2-046 | — | — |

### 7.14 Integração Telegram (TLG)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-TLG-01 | Bot privado pela Bot API oficial, com comunicação de saída (o serviço consulta o Telegram). A aplicação não fica exposta à internet. | M | PVD §7 | — | — |
| RF-TLG-02 | Aceitar documentos somente de remetentes cadastrados. Mensagens de outros remetentes são descartadas sem processamento e registradas. | M | PVD §5.3, §7 | RF-ADM-03 | CA-05 |
| RF-TLG-03 | Responder ao remetente só depois de o arquivo estar armazenado ("recebido, aguardando revisão") e avisar em caso de falha ("não foi possível receber, reenvie"). | M | PVD §7 | — | CA-05 |
| RF-TLG-04 | Reprocessar a mesma mensagem (mesmo identificador) não cria uma segunda importação. | M | PVD §5.3 | — | CA-11 |
| RF-TLG-05 | Se o Telegram estiver indisponível, o restante do sistema continua funcionando, inclusive o lançamento manual e o envio pela web. | M | PVD §7 | — | CA-13 |

### 7.15 Extensibilidade para assistente (EXT)

| ID | Requisito | P | Origem | Dep. | CA |
|---|---|---|---|---|---|
| RF-EXT-01 | Toda alteração de dados ocorre por operações de domínio nomeadas (ex.: "aprovar compra", "concluir OP"), com validação de regras dentro da própria operação, independentemente do canal que a chamou. | M | DEC-F2-002 | — | CA-02 |
| RF-EXT-02 | Cada operação registra a sequência pedido → validação → execução → resultado, com o resultado final (sucesso ou erro). Uma interface ou canal só exibe sucesso depois da confirmação da operação. | M | Briefing §6, DEC-F2-002 | RF-ADM-02 | CA-02 |
| RF-EXT-03 | Operações que alteram dados aceitam uma chave de idempotência fornecida pelo chamador. | M | PVD §7 | — | CA-11 |
| RF-EXT-04 | Assistente de IA e voz: consultas, comandos, confirmação, feedback e permissões por ferramenta. | W | DEC-F2-002 | RF-EXT-01..03 | — |

---

## 8. Fluxos operacionais

Cada fluxo tem o caminho principal (P), as alternativas (A) e os erros (E).

### FL-01 — Compra por importação (Telegram ou web)

- **P1.** O operador envia a foto do cupom pelo Telegram (ou pela web).
- **P2.** O sistema verifica o remetente, armazena o original, cria a importação "recebida" e confirma ao remetente (RF-TLG-03).
- **P3.** A extração preenche cabeçalho e linhas e faz a correspondência dos itens. A importação passa a "aguardando revisão".
- **P4.** O operador abre a revisão (documento ao lado dos dados), confirma as linhas "a confirmar", cria itens por cadastro rápido e corrige valores.
- **P5.** O sistema confere a soma com o total (RF-CMP-08) e verifica duplicidade (RN-05).
- **P6.** O operador aprova e informa a condição de pagamento. A compra é criada como "aprovada" e a obrigação vinculada nasce (RF-FIN-01).
- **P7.** Recebimento: segue o FL-02 (na mesma tela ou depois).

Alternativas e erros:

- **A1.** Remetente não autorizado: a mensagem é descartada e registrada, sem resposta de conteúdo.
- **A2.** Mesmo arquivo ou mesma chave já importados: a importação é marcada "possível duplicata", com link para a original. A aprovação fica bloqueada se a original já foi aprovada.
- **A3.** Divergência de total: a aprovação exige justificativa.
- **A4.** O operador rejeita com motivo: a importação fica "rejeitada" e o original é preservado.
- **E1.** Extração indisponível ou ilegível: "falha na extração". O operador lança manualmente a partir do documento (RF-CMP-14).
- **E2.** Falha ao armazenar o arquivo: nada é registrado como recebido e o remetente é avisado para reenviar.
- **E3.** Duplo clique ou reenvio da aprovação: a segunda tentativa retorna a compra já aprovada, sem novo efeito.

### FL-02 — Recebimento físico

- **P1.** Para cada linha, o operador informa a quantidade recebida, o lote do fornecedor ou "sem lote informado" e a validade (se o item controla validade).
- **P2.** O sistema cria as entradas de estoque com o custo unitário da linha (RN-20).
- **P3.** A compra fica "recebida" (tudo entregue) ou "parcialmente recebida", com pendência por linha.

Alternativas e erros:

- **A1.** Entrega complementar: novo recebimento contra a pendência (RF-REC-03).
- **A2.** Fornecedor não vai entregar: encerrar a pendência com motivo. O alerta financeiro é criado e a compra fica "encerrada com pendência".
- **A3.** Há consumo pendente do item: o sistema propõe a conciliação com o lote recebido (FL-08).
- **E1.** Quantidade recebida maior que a documentada: bloqueado. O excesso entra por ajuste "bonificação" a custo zero ou por nova compra (RF-REC-08).
- **A4.** Devolução ao fornecedor depois do recebimento: RF-REC-07.
- **E2.** Conversão sem fator cadastrado: bloqueado até o fator ser cadastrado.

### FL-03 — Produção (OP)

- **P1.** O operador cria a OP (produto ou preparação, quantidade planejada). O status é "planejada", com a versão vigente da ficha.
- **P2.** O operador inicia a OP: o status passa a "em produção" e a versão da ficha fica fixada.
- **P3.** Na conclusão, o sistema pré-preenche componentes × quantidade escalada × lotes sugeridos. Preparações são consumidas do estoque da preparação (RN-12).
- **P4.** O operador corrige as diferenças e informa a quantidade boa, as perdas (com motivo), o estado inicial de conservação e a data/hora.
- **P5.** O sistema conclui de forma atômica: consumos, lote novo, custo real e validade calculada. Em seguida oferece a impressão de etiquetas.

Alternativas e erros:

- **A1.** Falta de saldo de um componente: o operador registra um consumo pendente com justificativa (RF-EST-06). O custo fica "pendente".
- **A2.** A preparação necessária não tem estoque: o sistema avisa e oferece criar a OP da preparação. O consumo direto dos ingredientes da preparação não é permitido (RN-12).
- **A3.** Cancelar a OP antes de concluir: nenhum movimento é gerado.
- **E1.** Falha durante a conclusão: nenhum movimento parcial é persistido (RN-08).
- **E2.** Quantidade boa igual a zero: exige confirmação e registra tudo como perda.

### FL-04 — Fritura do dia

- **P1.** O operador registra a fritura: produto cru, lote sugerido, quantidade frita e quantidade boa.
- **P2.** O sistema baixa o cru, cria o lote frito vinculado e aplica o custo (cru + óleo de referência).
- **P3.** No fim do dia, o sistema alerta sobre os lotes fritos com saldo. O operador registra o destino (perda ou outro destino permitido).

Alternativas e erros:

- **A1.** Troca de óleo: registrar a saída do óleo. O sistema calcula o ajuste de óleo do período.
- **E1.** Lote cru vencido: bloqueado.

### FL-05 — Conservação e etiqueta

- **P1.** O lote nasce no estado informado na conclusão (pode ser congelado).
- **P2.** Transferência de estado: o operador escolhe lote, quantidade e novo estado. O sistema move o saldo e calcula a validade do novo estado pelo critério cadastrado.
- **P3.** O operador imprime as etiquetas da quantidade transferida ou produzida. A impressão é registrada.

Alternativas e erros:

- **A1.** Sem critério de validade para o produto e o estado: o operador informa a validade com justificativa, marcada como "manual".
- **A2.** Reimpressão: registrada como reimpressão.
- **E1.** Impressora indisponível: o sistema gera um arquivo imprimível e a impressão não é registrada como feita até a confirmação (DEC-F2-047).

### FL-06 — Venda direta

- **P1.** O operador escolhe apresentações e quantidades e a tabela (varejo ou atacado). Pode aplicar um desconto.
- **P2.** O sistema converte em unidades físicas e embalagens e sugere os lotes por estado.
- **P3.** O operador informa o pagamento: pago (forma) ou a prazo (parcelas).
- **P4.** O sistema registra a venda, as saídas, o custo dos lotes baixados e o pagamento ou recebível.

Erros:

- **E1.** Saldo insuficiente no estado pedido: bloqueado. Venda não aceita consumo pendente.
- **E2.** Lote vencido: não é sugerido nem aceito.

### FL-07 — Encomenda

- **P1.** O operador cria a encomenda (cliente, data, entrega ou retirada, itens e estado).
- **P2.** Ao confirmar, o sistema reserva o disponível e mostra a necessidade de produção do que falta.
- **P3.** O operador gera as OPs a partir da necessidade (opcional). Quando os lotes entram, ele completa a reserva.
- **P4.** Separação e entrega: a reserva vira saída por venda e o sistema gera o recebível ou registra o pagamento.

Alternativas:

- **A1.** Cancelar antes da saída: as reservas são liberadas.
- **A2.** Devolução depois da entrega: segue o FL-09.
- **A3.** O lote reservado vence antes da entrega: a reserva é liberada e o sistema alerta para substituir o lote.

### FL-08 — Consumo pendente e conciliação

- **P1.** Na conclusão de uma OP ou fritura, falta saldo. O operador registra um consumo pendente (item, quantidade, justificativa).
- **P2.** O alerta fica aberto e o custo da produção fica "pendente".
- **P3.** No recebimento do item, o sistema propõe vincular o pendente ao lote recebido. O operador confirma, o lote e o custo são definidos uma única vez e o custo da produção é fechado.

Alternativa:

- **A1.** O item aparece num ajuste de inventário (achado): o sistema propõe a conciliação com esse lote. Se o lote for desconhecido, usa "sem lote informado" com o custo médio (DEC-F2-041).

### FL-09 — Cancelamento, devolução e estorno

- **P1.** O cancelamento antes da saída libera as reservas e cancela os recebíveis em aberto.
- **P2.** Depois da saída, o padrão é registrar a perda. Se o operador escolher "devolver ao estoque", informa o motivo e o lote de origem, que precisa estar dentro da validade.
- **P3.** Financeiro: o sistema estorna ou cancela o recebível em aberto. Se o valor já foi pago, registra a devolução de valor ao cliente.

Para estornar um pagamento lançado errado: o estorno com motivo devolve a conta ao estado anterior, e o operador lança o pagamento correto.

### FL-10 — Contas a pagar e a receber

- **P1.** Uma obrigação ou recebível nasce de uma compra, uma venda ou um lançamento avulso, ou como prevista a partir de uma recorrência.
- **P2.** As parcelas são definidas, e a soma precisa ser igual ao total.
- **P3.** O operador registra o pagamento ou recebimento total ou parcial. A diferença é classificada.
- **P4.** A situação muda conforme RN-31.

### FL-11 — Inventário

- **P1.** O operador abre uma contagem (todos os itens ou uma seleção).
- **P2.** Informa as quantidades por lote e estado e vê as diferenças.
- **P3.** Confirma e o sistema gera um ajuste por diferença, com o motivo "inventário".
- **A1.** Durante uma contagem aberta, os movimentos continuam. A diferença é calculada contra o saldo no momento em que cada item é confirmado. Recomendação de uso: contar e confirmar cada item de uma vez (DEC-F2-042).

### FL-12 — Backup e restauração

- **P1.** Todos os dias, no horário configurado, o sistema gera uma cópia consistente do banco e dos documentos e a envia ao destino.
- **P2.** O resultado aparece no painel.
- **A1.** Restauração: o sistema faz um backup do estado atual, restaura o backup escolhido, roda a verificação de integridade e mostra o relatório.
- **E1.** Destino indisponível: falha registrada e alerta. O sistema tenta de novo no próximo ciclo Nova tentativa a cada hora até dar certo (DEC-F2-047).

---

## 9. Catálogo de regras de negócio

| ID | Regra | Origem | Verificação |
|---|---|---|---|
| RN-01 | Saldo de estoque = soma dos movimentos. Nenhuma operação altera o saldo sem gerar movimento. | PVD §5.4 | CA-17 |
| RN-02 | Saídas não podem exceder o saldo disponível do lote e estado, exceto o consumo pendente de produção ou fritura com justificativa. | DEC-F2-005 | CA-19 |
| RN-03 | Disponível = saldo − reservado − vencido. O saldo pendente de recebimento não entra no estoque. | PVD §5.4, DEC-F1-001 | CA-29 |
| RN-04 | Aprovação da compra, recebimento físico, obrigação financeira e pagamento são eventos distintos, com registros distintos. | PVD §5.3, §5.10 | CA-10 |
| RN-05 | Uma compra é duplicata se coincidir em: (a) hash do arquivo, (b) identificador da mensagem, (c) chave ou número do documento + fornecedor, ou (d) fornecedor + data + total (DEC-F2-039). Os casos (a) a (c) bloqueiam a aprovação se já existir compra aprovada; (d) só alerta. | PVD §5.3 | CA-11 |
| RN-06 | Toda operação que altera dados é idempotente pela sua chave. A repetição devolve o resultado original. | PVD §7 | CA-11 |
| RN-07 | Somente a quantidade fisicamente recebida entra no estoque. A compra mantém a quantidade documentada. | DEC-F1-001 | CA-10 |
| RN-08 | Conclusões (OP, fritura, venda, recebimento, inventário) são atômicas: todos os movimentos são gravados ou nenhum. | PVD §7 | CA-16 |
| RN-09 | O encerramento de pendência não altera o valor devido. Ele gera um alerta de ajuste manual. | DEC-F2-007 | CA-39 |
| RN-10 | Correspondências incertas de importação nunca são confirmadas sem ação do operador. | PVD §5.3 | CA-07 |
| RN-11 | Um sinônimo só vira correspondência automática depois de confirmado pelo operador. | DEC-F2-030 | CA-07 |
| RN-12 | Um componente do tipo preparação, na produção, é consumido apenas do estoque da preparação. Os ingredientes da sub-receita nunca são baixados na OP do produto. | PVD §5.5 | CA-16 |
| RN-13 | Fichas não podem formar ciclo (A usa B, B usa A, direta ou indiretamente). | DEC-F2-047 | CA-14 |
| RN-14 | Editar uma ficha cria uma nova versão. Versões usadas por OP iniciada ou concluída são imutáveis. | PVD §5.5, DEC-F2-015 | CA-15 |
| RN-15 | A OP fixa a versão da ficha ao ser iniciada. Antes disso, acompanha a vigente. | DEC-F2-015 | CA-15 |
| RN-16 | Uma OP gera exatamente um lote e é concluída uma única vez. | DEC-F2-017 | CA-16 |
| RN-17 | Lote produzido vincula todos os lotes consumidos. Consumo de saldo sem lote é registrado como "sem lote informado", sem identificação fictícia. | DEC-F1-004 | CA-23 |
| RN-18 | Sugestão de lote: menor validade; em empate ou sem validade, entrada mais antiga. A troca é registrada. | DEC-F2-004, 032 | CA-18 |
| RN-19 | Lote vencido não pode ser consumido, vendido, reservado nem devolvido ao estoque. Só aceita destino de descarte. | PVD §5.4 | CA-21 |
| RN-20 | Custo unitário de uma linha de compra = (valor da linha + rateio de frete e acréscimo − rateio de desconto) ÷ quantidade documentada na unidade de controle. O rateio é proporcional ao valor da linha sobre a soma das linhas. Impostos destacados estão incluídos no valor. | DEC-F2-008, 010 | CA-12 |
| RN-21 | O custo do lote recebido é o custo unitário da linha × quantidade recebida. Recebimento parcial não muda o custo unitário. | DEC-F1-001, RN-20 | CA-12 |
| RN-22 | Consumo de lote identificado usa o custo desse lote. Consumo de saldo sem lote usa a média ponderada móvel, recalculada a cada entrada sem lote. | DEC-F2-003 | CA-16 |
| RN-23 | Custo de referência atual de um item (para custo estimado) = custo unitário (RN-20) da **última compra aprovada** do item. Item nunca comprado não tem referência, e a ficha mostra o custo estimado como "incompleto". | PVD §5.5, DEC-F2-044 | CA-14 |
| RN-24 | Os indiretos de fabricação do período são rateados entre os lotes produzidos no período, proporcionalmente ao custo direto de cada lote. O resultado aparece só em relatório e nunca altera o lote. | DEC-F2-022, 045 | CA-34 |
| RN-25 | O custo real e o custo unitário de uma OP são gravados na conclusão e não mudam, exceto (a) por fechamento de custo pendente (uma única vez) e (b) por ajuste de correção vinculado, que mantém o valor original visível. | PVD §5.5, §5.6, DEC-F2-033 | CA-15 |
| RN-26 | Ajuste de óleo = custo do óleo descartado na troca − Σ(óleo de referência × unidades fritas desde a troca anterior). Lançado no período da troca. | DEC-F2-023 | CA-25 |
| RN-27 | Validade = data-base do critério + prazo do critério para o produto e o estado. Sem critério, a validade é manual, justificada e marcada. Nunca há prazo padrão global. | PVD §5.7 | CA-21 |
| RN-28 | Transferência de estado mantém a identificação do lote e recalcula a validade daquela quantidade pelo critério do novo estado. A data-base segue o critério cadastrado (REG-02). | DEC-F2-014 | CA-20 |
| RN-29 | Uma apresentação vendida baixa exatamente (unidades da apresentação × quantidade) do produto e as embalagens da apresentação. | PVD §5.8, DEC-F2-028 | CA-28 |
| RN-30 | Preço, desconto, fator de conversão e custo baixado são gravados na linha da venda e não mudam depois. | PVD §6 | CA-28 |
| RN-31 | Situação da parcela: prevista → em aberto (confirmação) → parcialmente paga ou paga. "Vencida" é derivada. Um estorno volta a parcela à situação anterior. Cancelamento só é possível sem pagamento registrado. | DEC-F2-025, 026, 027 | CA-36 |
| RN-32 | Soma das parcelas = total da obrigação ou recebível. | DEC-F2-024 | CA-36 |
| RN-33 | Compra de item estocável gera obrigação, não despesa. O custo é reconhecido no consumo ou na venda. | DEC-F2-006 | CA-34 |
| RN-34 | Correções financeiras e de estoque são feitas por estorno ou ajuste com motivo. Nada é apagado nem editado. | DEC-F2-027, PVD §6 | CA-17, CA-38 |
| RN-35 | A encomenda reserva ao ser confirmada. Reserva não pode ser usada por outra saída. Cancelar antes da saída a libera. | DEC-F2-019 | CA-26 |
| RN-36 | Devolução ou cancelamento depois da saída vai para perda por padrão. A volta ao estoque exige motivo e lote dentro da validade. | DEC-F2-021 | CA-30 |
| RN-37 | Conta prevista (recorrência) não aparece como obrigação nem como despesa realizada até ser confirmada. | DEC-F2-026 | CA-38 |
| RN-38 | Apenas remetentes cadastrados criam importações pelo Telegram. | PVD §7 | CA-05 |
| RN-39 | O sistema só reporta sucesso de uma operação depois de ela ser efetivada no banco. | Briefing §6, PVD §7 | CA-02 |
| RN-40 | Quantidades são guardadas na unidade de controle do item. A conversão acontece na entrada do dado com o fator vigente, e o movimento guarda o fator usado. | DEC-F2-029 | CA-06 |

---

## 10. Modelo conceitual de dados

Entidades e relações relevantes. Não é um esquema físico.

| Entidade | Atributos essenciais | Relações |
|---|---|---|
| Item de estoque | tipo (ingrediente, insumo, embalagem, preparação, produto), unidade de controle, controla validade, estoque mínimo, ativo | tem conversões, sinônimos, lotes e fichas (se preparação ou produto) |
| Conversão | unidade origem, unidade destino, fator | pertence a um item (ou é padrão do sistema) |
| Sinônimo | fornecedor, descrição, confirmado | aponta para um item |
| Apresentação comercial | unidades por apresentação, embalagens consumidas, preço de varejo, preço de atacado | pertence a um produto |
| Fornecedor / Cliente | identificação, contato | compras / vendas, encomendas, recebíveis |
| Importação | origem (Telegram/web), remetente, id da mensagem, hash, arquivo original, dados extraídos, status | gera 0..1 compra |
| Compra | fornecedor, data, chave do documento, totais, frete, desconto, acréscimo, status, aprovação (autor, data) | tem linhas e 1 obrigação |
| Linha de compra | item, quantidade documentada, unidade, valor, custo unitário calculado | tem 0..n recebimentos e 0..1 pendência |
| Recebimento | linha, quantidade recebida, lote do fornecedor ou "sem lote", validade | gera entrada de estoque e lote |
| Lote | identificação, origem (compra, OP, fritura), custo unitário, fabricação ou recebimento, sem-lote | tem saldos por estado e vínculos de origem (lotes consumidos) |
| Saldo por estado | lote, estado de conservação, validade daquela porção | derivado de movimentos |
| Movimento de estoque | tipo, item, lote, estado, quantidade (unidade de controle), fator usado, custo, documento de origem, chave de idempotência, autor e data | pertence a um evento (compra, OP, venda etc.) |
| Consumo pendente | item, quantidade, justificativa, OP ou fritura, status, lote conciliado | resolvido por recebimento ou ajuste |
| Ficha técnica / Versão | produto, versão, componentes, rendimento, perdas previstas, vigência | usada por OPs |
| Componente da ficha | item (ingrediente, insumo, embalagem ou preparação), quantidade, unidade | pertence a uma versão |
| Ordem de produção | produto, versão da ficha, quantidade planejada, quantidade boa, perdas, status, custo real, custo pendente | consome lotes, gera 1 lote |
| Fritura | lote cru, quantidade frita, quantidade boa | consome lote, gera lote frito |
| Troca de óleo | data, quantidade, custo, ajuste calculado | movimento de saída de óleo |
| Critério de validade | produto, estado, prazo, data-base, fonte de validação | usado no cálculo da validade |
| Etiqueta impressa | lote, estado, quantidade, modelo, reimpressão, autor e data | — |
| Venda / Encomenda | cliente, tabela, itens, status, entrega | linhas, reservas, movimentos, recebível |
| Linha de venda | apresentação, quantidade, preço praticado, desconto, fator, custo baixado | movimentos de saída |
| Reserva | encomenda, item, lote, estado, quantidade, status | — |
| Obrigação / Recebível | origem (compra, venda, avulso, recorrência), total, classificação | tem parcelas |
| Parcela | valor, vencimento, situação | tem pagamentos |
| Pagamento / Recebimento financeiro | valor, data, forma, diferença e motivo, estorno de | pertence a uma parcela |
| Despesa recorrente | descrição, valor de referência, periodicidade, classificação | gera contas previstas |
| Categoria de custo | nome, natureza (fabricação, comercial, operacional, investimento), método de apropriação | classifica despesas |
| Inventário | escopo, status, contagens | gera ajustes |
| Registro de auditoria | operação, autor, origem, data, pedido, resultado, entidades | transversal |
| Backup | data, destino, status, verificação | — |

---

## 11. Estados e transições

| Entidade | Estados | Transições permitidas | Restrições |
|---|---|---|---|
| Importação | recebida → em extração → aguardando revisão → aprovada / rejeitada; falha na extração → (lançamento manual) aprovada / rejeitada | Só "aguardando revisão" ou "falha na extração" podem ser aprovadas | Aprovada e rejeitada são finais |
| Compra | aprovada → parcialmente recebida → recebida; aprovada/parcial → encerrada com pendência; aprovada → cancelada | Cancelamento só sem recebimento e sem pagamento (RF-CMP-15) | — |
| OP | rascunho → planejada → em produção → concluída; rascunho/planejada/em produção → cancelada | Concluída é final (só ajuste vinculado) | A versão da ficha fica fixada em "em produção" |
| Lote (por porção) | disponível, reservado, vencido (derivado da data), baixado (saldo zero) | — | Vencido só aceita descarte |
| Consumo pendente | aberto → conciliado | — | Conciliação única |
| Encomenda | rascunho → confirmada (reserva) → separada → entregue; rascunho/confirmada/separada → cancelada | Devolução depois de entregue segue o FL-09 | — |
| Venda direta | concluída → cancelada ou devolvida (total ou parcial) | — | — |
| Parcela | prevista → em aberto → parcialmente paga → paga; prevista/em aberto → cancelada | O estorno desfaz a última transição de pagamento | "Vencida" é derivada |
| Inventário | aberto → confirmado / descartado | — | — |
| Backup | agendado → em execução → concluído / falhou | — | — |

---

## 12. Requisitos não funcionais

| ID | Requisito | Meta / verificação | Origem |
|---|---|---|---|
| RNF-01 | Interface em pt-BR, com moeda R$, data dd/mm/aaaa e vírgula decimal | Inspeção de todas as telas e relatórios | PVD §7 |
| RNF-02 | Web responsiva: as tarefas de chão de cozinha (fritura, transferência de estado, etiqueta, recebimento, venda direta) funcionam em tela de 360 px de largura sem rolagem horizontal | Teste em 360 px, 768 px e 1366 px | PVD §7 |
| RNF-03 | Funciona na rede local sem internet. Só a extração externa e o Telegram dependem de internet e degradam conforme o §15 | Teste com o link de internet desligado | PVD §7, DEC-F2-009 |
| RNF-04 | O banco é acessado somente pelo serviço central. Vários dispositivos podem operar ao mesmo tempo sem saldo inconsistente. Edições concorrentes do mesmo registro são detectadas e a segunda é recusada com mensagem, sem sobrescrever | Teste com 2 dispositivos concluindo vendas do mesmo lote ao mesmo tempo: a soma das saídas nunca passa do saldo | PVD §7 |
| RNF-05 | Desempenho para o volume de uma pequena operação. (DEC-F2-047, a confirmar com o hardware — PR-05): operações de lançamento < 2 s e relatórios de 1 mês < 5 s, com 2 anos de dados | Medição no servidor definitivo | PVD §7 |
| RNF-06 | Backup com perda máxima de 24 h. Restauração verificável. Restauração concluída em até 1 h seguindo o procedimento documentado | Restauração de ensaio antes de entrar em operação e a cada trimestre | DEC-F2-034, PVD §7 |
| RNF-07 | Senha guardada com hash forte e bloqueio temporário após tentativas falhas. Segredos (token do bot, credencial de extração) ficam fora do código, protegidos no servidor e não são exibidos na interface | Revisão de segurança | PVD §7 |
| RNF-08 | Documentos fiscais acessíveis só a usuário autenticado. O envio ao serviço externo de extração se limita ao arquivo da compra, sem outros dados do sistema | Revisão de segurança | PVD §7, DEC-F2-009 |
| RNF-09 | Comunicação entre dispositivos e servidor protegida na LAN por HTTPS com certificado local (DEC-F2-047) | — | PVD §7 |
| RNF-10 | Observabilidade: painel de saúde com último backup, fila de importação, conexão com Telegram e com a extração e erros recentes. Cada erro tem um identificador mostrado ao operador e registrado em log | Inspeção | PVD §7 |
| RNF-11 | Acessibilidade básica: contraste WCAG AA, alvos de toque ≥ 44 px, formulários navegáveis por teclado, erros descritos em texto (não só por cor) | Checagem automatizada e manual | Briefing |
| RNF-12 | Precisão: valores monetários sem erro de ponto flutuante. Quantidades com 3 casas na unidade de controle e custo unitário com 4 casas, com arredondamento só na exibição | Testes de cálculo (§17) | PVD §5.2 |
| RNF-13 | Um fuso horário da operação, configurado. Validade tratada como data local | Teste | — |
| RNF-14 | Separação entre interface, regras de negócio, persistência e integrações | Revisão de arquitetura | PVD §7 |
| RNF-15 | Reiniciar o serviço não perde importações recebidas nem deixa operações pela metade | Teste de interrupção durante a conclusão de uma OP | PVD §7 |
| RNF-16 | Retenção: nenhum documento, auditoria ou movimento é excluído automaticamente | Inspeção | DEC-F2-035 |

---

## 13. Integração e importação de documentos

**Canais de entrada:** Telegram (bot privado) e envio pela web. A interface interna de importação é a mesma para os dois canais, o que permite trocar ou acrescentar canais no futuro (PVD §7).

| Aspecto | Requisito |
|---|---|
| Formatos | **M:** foto de cupom fiscal (JPG/PNG/HEIC). **S:** XML de NF-e (leitura local), PDF/DANFE. **C:** QR Code da NFC-e. Outros formatos são rejeitados com mensagem clara. |
| Tamanho | Limite configurável, padrão 20 MB (DEC-F2-047). Acima disso, rejeita e avisa. |
| Armazenamento | O original é gravado antes de qualquer processamento e de qualquer confirmação ao remetente. |
| Extração | Assíncrona. O status é visível na fila. Tempo limite configurável. Falha ou tempo excedido levam a "falha na extração" com opção de tentar de novo ou lançar manualmente. |
| Serviço externo | Permitido para foto e PDF (DEC-F2-009). O fornecedor é escolha de arquitetura e deve ser substituível sem mudar o fluxo. |
| Confiança | Cada campo extraído traz um indicador de confiança. Campos de baixa confiança ficam destacados na revisão. |
| Deduplicação | RN-05 e RN-06. |
| Telegram | Comunicação de saída (consulta periódica). Remetentes autorizados por identificador do Telegram. Com o Telegram fora do ar, as mensagens são processadas quando o serviço voltar e nada é perdido no lado do sistema. |

---

## 14. IA, voz e automação

Conforme a DEC-F2-002, **o assistente de cozinha com IA e voz está fora do MVP**. As automações do MVP são:

| Automação | Comportamento |
|---|---|
| Extração de documentos | Prepara a compra. Nunca aprova nem recebe (RN-10, PVD §6). |
| Correspondência por sinônimo | Só aplica sinônimos confirmados (RN-11). |
| Sugestão de lote (FEFO) | Sugere, e o operador confirma ou troca. |
| Necessidade de produção | Sugere, e o operador decide criar a OP. |
| Recorrência financeira | Gera contas previstas, que o operador confirma. |
| Backup | Automático, com alerta de falha. |

**Preparação para o assistente (RF-EXT-01 a 03):** operações de domínio nomeadas e validadas, registro do ciclo pedido → validação → execução → resultado, idempotência e sucesso informado só depois de efetivado.

**Temas que ficam para a especificação futura do assistente** (vindos do briefing; não são requisitos do MVP):

- separar comandos de consulta dos que alteram dados;
- operações que exigem confirmação explícita ou que são proibidas por voz;
- feedback visual e sonoro;
- falhas de reconhecimento e interrupção da fala;
- permissões por ferramenta;
- funcionamento sem internet;
- dependência de modelos externos.

---

## 15. Erros, exceções e recuperação

| Situação | Comportamento esperado |
|---|---|
| Duplo clique ou reenvio de uma operação | Retorna o resultado original, sem novo efeito (RN-06) |
| Falha no meio de uma conclusão | Nada é gravado e o operador vê o erro com identificador (RN-08) |
| Saldo insuficiente | Bloqueio com o saldo disponível exibido. Em produção ou fritura, oferece o consumo pendente |
| Conversão sem fator | Bloqueio com indicação do fator que falta e atalho para cadastrá-lo |
| Lote vencido selecionado | Bloqueio |
| Edição concorrente | A segunda gravação é recusada com aviso para recarregar (RNF-04) |
| Extração indisponível | Documento em "falha na extração", com lançamento manual possível |
| Telegram fora do ar | Painel indica "Telegram desconectado". O restante funciona normalmente |
| Impressora indisponível | Gera arquivo imprimível. A impressão só é registrada quando confirmada |
| Destino de backup indisponível | Falha registrada, alerta e nova tentativa |
| Servidor reiniciado | Fila de importação e operações retomadas sem perda nem duplicidade (RNF-15) |
| Restauração | Backup automático do estado atual antes de restaurar e verificação de integridade depois |
| Divergência detectada na verificação de integridade | Relatório com os itens divergentes. Nenhuma correção automática |

---

## 16. Relatórios, indicadores e critérios de cálculo

| Indicador | Cálculo |
|---|---|
| Custo unitário da linha de compra | RN-20 |
| Custo estimado da ficha (por unidade de rendimento) | Σ(quantidade do componente × custo de referência, RN-23) ÷ rendimento previsto, mais as referências de óleo e indiretos por unidade, mostradas separadamente |
| Custo real da OP | Σ custo dos consumos (RN-22) + embalagens + óleo de referência |
| Custo unitário real | Custo real ÷ quantidade boa |
| Rendimento real | Quantidade boa ÷ quantidade planejada |
| Perda da OP | Quantidade planejada − quantidade boa, e perdas registradas por motivo |
| Custo do lote frito (unidade) | (custo unitário do cru × quantidade frita + óleo de referência × quantidade frita) ÷ quantidade boa |
| Ajuste de óleo | RN-26 |
| Custo pleno gerencial do período | Custo direto dos lotes do período + indiretos rateados (RN-24) + ajuste de óleo |
| Custo da mercadoria vendida | Σ custo dos lotes baixados nas vendas (RN-30) |
| Margem estimada por produto | (receita líquida de descontos − custo direto baixado) ÷ receita. Sempre rotulada "estimada", com a lista do que não inclui (tributos sobre venda, despesas comerciais e indiretos, salvo quando o relatório indicar) |
| Previsto × realizado | Por OP e por período: quantidade, consumo por componente, custo |
| Evolução de preço | Custo unitário (RN-20) por item ao longo do tempo, por fornecedor |
| Itens a vencer | Lotes com validade em até N dias, com N configurável por estado de conservação. Padrões: fresco e frito 1, resfriado 2, congelado 15, ingredientes 7 (DEC-F2-043) |
| Estoque baixo | Disponível (RN-03) < estoque mínimo |
| Contas | Em aberto, vencidas e pagas por período de vencimento ou pagamento |

---

## 17. Critérios de aceite

Formato Dado / Quando / Então. Os valores numéricos são exemplos de teste.

- **CA-01 (RF-ADM-01):** Dado um dispositivo sem sessão, quando ele acessa qualquer URL do sistema, então é levado ao login e nenhuma informação é exibida.
- **CA-02 (RF-ADM-02, RF-EXT-01/02, RN-39):** Dada uma aprovação de compra, quando ela é efetivada, então a auditoria registra operação, autor, origem, data/hora e resultado "sucesso". Dada uma falha forçada no banco durante a operação, então a interface mostra erro (nunca sucesso) e a auditoria registra "erro".
- **CA-03 (RF-ADM-04 a 06):** Dado o backup agendado, quando o horário chega, então um arquivo consistente com banco e documentos aparece no destino. Dado o destino desconectado, então o painel mostra o alerta de backup falho, e ele também aparece quando o último sucesso tem mais de 24 h.
- **CA-04 (RF-ADM-07/08):** Dado um backup de ontem, quando o operador o restaura, então um backup do estado atual é criado antes, a restauração termina, a verificação de integridade roda e o relatório mostra zero divergências entre saldos e movimentos.
- **CA-05 (RF-CMP-02/03, RF-TLG-02/03, RN-38):** Dado um remetente autorizado, quando ele envia a foto de um cupom legível, então recebe "recebido, aguardando revisão" depois de o arquivo estar armazenado, e a fila mostra a compra com fornecedor, data, itens e total pré-preenchidos. Dado um remetente não cadastrado, então nenhuma importação é criada e o evento é registrado.
- **CA-06 (RF-CAD-02, RN-40):** Dado o óleo com unidade de controle "L" e sem fator L↔kg, quando o operador lança uma compra de 15 kg de óleo, então o lançamento é bloqueado e o sistema pede o fator. Dado o fator cadastrado, então o movimento guarda a quantidade em L e o fator usado.
- **CA-07 (RF-CMP-06/07, RN-10/11):** Dado o cupom com a linha "FAR TRIGO ESP 5KG" sem sinônimo, quando a revisão abre, então a linha aparece "a confirmar" ou "não reconhecida", e a aprovação fica bloqueada até ela ser resolvida. Quando o operador cria um item por cadastro rápido e aprova, então na próxima compra do mesmo fornecedor a linha é reconhecida automaticamente.
- **CA-08 (RF-CMP-01):** Dado o Telegram indisponível, quando o operador lança uma compra manual completa e aprova, então a compra e a obrigação são criadas normalmente.
- **CA-09 (RF-CMP-08):** Dado itens que somam R$ 98,00 e total do documento de R$ 100,00, quando o operador tenta aprovar, então o sistema mostra a divergência de R$ 2,00 e exige justificativa.
- **CA-10 (RF-CMP-10, RF-REC-01/02, RF-FIN-01, RN-04/07):** Dada uma compra documentada de 10 kg de farinha, quando o operador aprova "a prazo, 1 parcela" e registra o recebimento de 8 kg, então a compra mostra 10 kg documentados, o estoque mostra +8 kg disponíveis, a pendência é de 2 kg (não disponível), a obrigação tem o valor integral do documento e existem eventos separados de aprovação, recebimento e obrigação.
- **CA-11 (RF-CMP-12, RF-TLG-04, RN-05/06):** Dada uma compra aprovada a partir do cupom X, quando o mesmo arquivo é reenviado pelo Telegram, então a nova importação é marcada "possível duplicata" e a aprovação fica bloqueada. Quando o botão "aprovar" é enviado duas vezes seguidas, então existe uma única compra, uma única obrigação e nenhum movimento duplicado.
- **CA-12 (RF-CMP-13, RN-20/21):** Dada uma compra com farinha 10 kg a R$ 60,00, óleo 5 L a R$ 40,00, frete de R$ 10,00 e desconto de R$ 5,00, quando aprovada, então o custo unitário é R$ 6,30/kg para a farinha e R$ 8,40/L para o óleo. Com recebimento de 8 kg de farinha, o lote vale R$ 50,40.
- **CA-13 (RF-CMP-14, RF-TLG-05):** Dado o serviço de extração indisponível, quando uma foto chega, então a importação fica em "falha na extração", com o original visível e a opção "lançar manualmente", e nenhum documento é perdido.
- **CA-14 (RF-FIC-01 a 03, RF-CUS-05, RN-13/23):** Dada a ficha "massa" (rendimento de 10 kg, custo de ingredientes de R$ 30,00) e a ficha "coxinha" usando 0,05 kg de massa por unidade, quando o custo estimado é calculado, então a parcela de massa por coxinha é R$ 0,15, e as referências de óleo e indiretos aparecem separadas. Quando o operador tenta incluir "coxinha" na ficha "massa", então o sistema recusa por referência circular.
- **CA-15 (RF-FIC-04/05, RF-OP-02, RN-14/15/25):** Dada uma OP concluída com custo unitário de R$ 0,79, quando o preço do frango sobe e a ficha é editada, então a OP continua com R$ 0,79 e versão 3, o custo estimado da ficha muda e a ficha passa à versão 4. Dada uma OP "planejada", então ela passa a mostrar a versão 4. Dada uma OP "em produção", então ela continua na versão 3.
- **CA-16 (RF-FIC-06, RF-OP-03 a 06, RN-08/12/16/22):** Dado o lote de massa M1 (10 kg a R$ 3,00/kg) e o frango F1 a R$ 20,00/kg, quando a OP de 100 coxinhas é concluída consumindo 5 kg de M1 e 3 kg de F1, com 95 unidades boas, então o custo real é R$ 75,00, o custo unitário é R$ 0,7895, existe um único lote novo vinculado a M1 e F1, o saldo de farinha (ingrediente da massa) **não** muda e uma segunda submissão da conclusão não gera movimentos.
- **CA-17 (RF-EST-01/08, RF-OP-07, RN-01/34):** Dada qualquer tela de estoque, então não existe campo para editar saldo. Quando o operador faz um ajuste sem motivo, então ele é recusado. Dado um ajuste em uma OP concluída, então o custo original e o ajuste aparecem separados.
- **CA-18 (RF-EST-05, RN-18):** Dados os lotes de frango A (validade 20/10) e B (validade 25/10), quando a OP sugere o consumo, então A vem primeiro. Dados dois lotes de sal sem validade, então o de entrada mais antiga vem primeiro. Quando o operador troca para B, então a troca fica registrada.
- **CA-19 (RF-EST-06/07, RF-CUS-02, RN-02):** Dado um saldo de 0 kg de queijo, quando a OP precisa de 2 kg, então a conclusão é bloqueada, a menos que o operador registre um consumo pendente com justificativa. Nesse caso o alerta abre e o custo da OP fica "pendente". Quando chega o lote Q1 de queijo e o operador confirma a conciliação, então o pendente é vinculado a Q1 com o custo de Q1, o saldo de Q1 é reduzido em 2 kg e o custo da OP é fechado.
- **CA-20 (RF-ETQ-01, RF-EST-03, RN-28):** Dado o lote L com 250 unidades resfriadas, quando o operador transfere 200 para congelado, então L mostra 200 congeladas e 50 resfriadas, com a mesma identificação, e a validade das 200 segue o critério de congelado.
- **CA-21 (RF-ETQ-02, RF-EST-10, RN-19/27):** Dado um produto sem critério de validade para "resfriado", quando um lote é concluído nesse estado, então o sistema exige a validade manual com justificativa e a marca como "manual". Dado um lote vencido, então ele não aparece para consumo, venda ou reserva e só aceita descarte.
- **CA-22 (RF-ETQ-03/05):** Dado um lote concluído, quando o operador imprime 10 etiquetas e depois reimprime 2, então os dois registros existem (o segundo marcado como reimpressão), os dados impressos são iguais aos do lote e nenhum dado do lote muda.
- **CA-23 (RF-EST-12, RF-OP-05, RN-17):** Dado o lote de coxinha C1 produzido com M1 e com frango "sem lote informado", quando o operador consulta a origem de C1, então vê M1 (e os ingredientes de M1) e "frango — sem lote informado". Quando consulta o destino de M1, então vê C1 e as vendas de C1.
- **CA-24 (RF-FRI-01 a 03):** Dado o lote cru K1 (custo de R$ 0,60 por unidade) e o óleo de referência de R$ 0,05 por unidade, quando o operador frita 40 com 38 boas, então o lote frito tem custo de R$ 26,00 (R$ 0,6842 por unidade), está vinculado a K1 e K1 cai 40 unidades. No fim do dia, com 5 fritas sobrando, o alerta aparece até o destino ser registrado.
- **CA-25 (RF-FRI-04, RN-26):** Dadas 1.000 unidades fritas desde a última troca (óleo apropriado de R$ 50,00), quando o operador registra uma troca de 18 L a R$ 8,40/L (R$ 151,20), então o ajuste de óleo de R$ 101,20 aparece no relatório do período e nenhum lote frito muda.
- **CA-26 (RF-VEN-05 a 08, RN-35):** Dadas 60 coxinhas congeladas disponíveis, quando uma encomenda de 100 é confirmada, então 60 ficam reservadas, a necessidade de produção mostra 40 e uma venda direta de coxinha congelada só enxerga 0 disponível. Quando a encomenda é entregue, então as reservas viram saídas e é gerado o recebível ou o pagamento.
- **CA-27 (RF-VEN-06, RF-REL-01):** Dada a necessidade de 40 unidades, quando o operador escolhe "gerar OP", então uma OP planejada de 40 é criada. Nenhuma OP é criada sem essa ação.
- **CA-28 (RF-CAD-04, RF-VEN-01 a 03, RN-29/30):** Dada a apresentação "caixa com 25", que consome 1 caixa de papelão, quando o operador vende 2 caixas no atacado a R$ 40,00 cada, então o estoque do produto baixa 50 unidades, o estoque de caixas de papelão baixa 2, e a linha guarda R$ 40,00, fator 25 e o custo dos lotes. Quando o preço de atacado muda depois, então a venda continua mostrando R$ 40,00.
- **CA-29 (RF-EST-04, RN-03):** Dado um item com saldo 10, 3 reservados, 2 vencidos e uma pendência de recebimento de 5, então o disponível mostrado é 5 e a pendência aparece à parte.
- **CA-30 (RF-VEN-09/10, RN-36):** Dada uma venda a prazo entregue, quando o cliente devolve e o operador não altera o destino, então as unidades vão para perda e o recebível em aberto é cancelado por estorno. Quando o operador escolhe "devolver ao estoque" com um lote vencido, então a ação é recusada.
- **CA-31 (RF-REL-01):** Dado um ambiente com uma pendência de cada tipo listado em RF-REL-01, quando o painel abre, então cada uma aparece e leva à tela correspondente.
- **CA-32 (RF-REL-02):** Dado um mês com dados, quando o operador gera cada relatório da lista com filtro de período, então os totais batem com a soma dos registros do período.
- **CA-33 (RF-CUS-06):** Dado qualquer relatório ou tela com margem, então o valor é rotulado "estimada" e mostra o que está incluído e o que não está.
- **CA-34 (RF-CUS-04/07, RF-REL-03, RN-24/33):** Dado um mês com R$ 1.000,00 de custo direto produzido (lote A R$ 600,00 e lote B R$ 400,00) e R$ 500,00 de indiretos de fabricação, então o relatório do período mostra o rateio de R$ 300,00 para A e R$ 200,00 para B, o custo pleno de R$ 1.500,00 e nenhum lote alterado. A compra de farinha do mês não aparece como despesa.
- **CA-35 (RF-FIN-02):** Dada uma despesa avulsa de gás, quando lançada com vencimento, então aparece em contas a pagar e no relatório de despesas da competência.
- **CA-36 (RF-FIN-03/04/07, RN-31/32):** Dada uma obrigação de R$ 300,00, quando o operador tenta parcelas de 100 + 100 + 90, então o sistema recusa. Com 3 parcelas de R$ 100,00, quando paga R$ 60,00 da primeira, então ela fica "parcialmente paga" com saldo de R$ 40,00. Depois do vencimento sem quitação, ela aparece como vencida.
- **CA-37 (RF-FIN-06, RF-VEN-04):** Dada uma venda a prazo de R$ 400,00 em 2 parcelas, quando o operador registra o recebimento de R$ 200,00, então a parcela 1 fica paga e a parcela 2 continua em aberto, e as duas aparecem na consulta de recebíveis.
- **CA-38 (RF-FIN-05/09, RN-31/34/37):** Dado um pagamento lançado errado, quando o operador o estorna com motivo, então o original continua visível, o estorno é registrado e a parcela volta ao estado anterior. Dada uma recorrência de aluguel, quando o mês começa, então surge uma conta "prevista" que não aparece em contas a pagar até ser confirmada.
- **CA-39 (RF-REC-03/04, RF-FIN-08, RN-09):** Dada uma pendência de 2 kg, quando chega 1 kg complementar, então entra um novo lote de 1 kg e a pendência cai para 1 kg. Quando o restante é encerrado como "não entregue", então a compra fica "encerrada com pendência", o alerta de ajuste financeiro aparece e o valor da obrigação não muda.
- **CA-41 (RF-REC-07):** Dado o lote de frango F2 com 5 kg recebidos e 1 kg já consumido, quando o operador devolve 4 kg ao fornecedor com motivo, então F2 fica com saldo 0, o movimento é do tipo "devolução ao fornecedor", aparece o alerta de ajuste na obrigação e o valor da obrigação não muda.
- **CA-42 (RF-REC-08):** Dada uma linha documentada de 10 kg, quando o operador tenta receber 11 kg, então o sistema recusa e oferece registrar 1 kg como bonificação. Confirmada a bonificação, surge um lote de 1 kg a custo zero, separado do lote de 10 kg.
- **CA-40 (RF-EST-09):** Dado um saldo de 12 kg de farinha, quando a contagem confirma 11,5 kg, então é gerado um ajuste de −0,5 kg com motivo "inventário", vinculado à contagem.

---

## 18. Dependências, riscos e pendências residuais

### 18.1 Pendências residuais

| ID | Pendência | Prioridade | Bloqueia | Quando resolver |
|---|---|---|---|---|
| ~~PR-01~~ | Resolvida: DEC-F2-036 e 037 (RF-CMP-15, RF-REC-06, RF-REC-07) | — | — | — |
| ~~PR-02~~ | Resolvida: propostas revisadas em DEC-F2-038 a 047 | — | — | — |
| PR-03 | Modelo de impressora térmica, dimensões e campos da etiqueta (P-26) | Baixa | RF-ETQ-07 | Antes da entrega E2 |
| PR-04 | Recuperação da senha do único usuário sem e-mail (procedimento local no servidor) | Média | — | Fase de arquitetura |
| PR-05 | Hardware do servidor e metas definitivas de desempenho (P-29) | Baixa | RNF-05 | Fase de arquitetura |
| PR-06 | Motivos padrão de perda, ajuste e devolução (lista inicial) | Baixa | — | UX/UI |
| REG-01 | Impostos da compra no custo (contador) | Média | Nada: o comportamento padrão já está definido (DEC-F2-010) | Antes de usar margens para preço |
| REG-02 | Critérios sanitários de validade por produto e estado, data-base após congelamento, destino de sobras de frito | **Alta para operação** | Não bloqueia o desenvolvimento (o sistema funciona com critérios cadastrados). Bloqueia a **entrada em operação** de etiquetas e validade | Antes de entrar em produção real |
| REG-03 | Prazo legal de guarda de documentos (contador) | Baixa | Nada: nada é apagado (DEC-F2-035) | Qualquer momento |

### 18.2 Riscos

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Baixa qualidade da extração de fotos de cupom (papel térmico, amassado) | Alta | Médio | Revisão obrigatória, fallback manual, sinônimos aprendidos, métrica de campos corrigidos por importação |
| Atrito no dia a dia leva a parar de registrar consumo, fritura e sobras | Média | Alto | Pré-preenchimento, FEFO sugerido, registro rápido de fritura, metas de responsividade (RNF-02) |
| Consumos pendentes acumulados sem conciliação | Média | Médio | Alerta persistente no painel e custo marcado "pendente" nos relatórios |
| Perda física do servidor e do backup local juntos (incêndio, roubo) | Baixa | Alto | Destino de backup em outro dispositivo. Backup em nuvem como evolução |
| Critérios de validade não cadastrados | Média | Alto | Validade manual obrigatória e marcada. REG-02 antes de entrar em operação |
| Escopo do MVP grande para uma primeira entrega | Alta | Médio | Entregas incrementais (§19), cada uma utilizável sozinha |
| Dependência de serviço externo de extração (custo, disponibilidade) | Média | Baixo | Componente substituível e fallback manual |

---

## 19. Priorização e divisão por entregas

Cada entrega pode ser usada sozinha e respeita as dependências do §6. O fluxo manual de compras vem antes da importação.

| Entrega | Objetivo | Requisitos |
|---|---|---|
| **E1 — Fundação: compras, estoque e contas a pagar** | Registrar compras e recebimentos e ter estoque confiável por lote | RF-ADM-01 a 08 · RF-CAD-01, 02, 05, 07 · RF-CMP-01, 08, 10 a 13 · RF-REC-01 a 05, 08 · RF-REC-06, 07 (S) · RF-EST-01 a 08, 10, 11 · RF-FIN-01, 03, 04, 07, 09, 10 · RF-EXT-01 a 03 · RF-CUS-01 |
| **E2 — Produção** | Fichas, OP, lotes, conservação e etiquetas | RF-CAD-03 · RF-FIC-01 a 06 · RF-OP-01 a 09 · RF-ETQ-01 a 07 · RF-EST-12 · RF-CUS-02, 05 · RF-EST-09 (S) |
| **E3 — Comercial** | Vender, reservar, fritar e receber | RF-CAD-04 · RF-VEN-01 a 11 · RF-FIN-06 · RF-FRI-01 a 05 · RF-CUS-06 |
| **E4 — Automação e gestão** | Importação inteligente, Telegram, custos do período, relatórios | RF-CAD-06 · RF-CMP-02, 03, 06, 07, 09, 14 · RF-TLG-01 a 05 · RF-CUS-03, 04, 07 · RF-FIN-02, 05 (S), 08 · RF-REL-01 a 03 · RF-REL-04 (S) |
| **Depois do MVP (S/C)** | — | RF-CMP-04, 05, 15, se não couberem nas entregas acima |

O painel (RF-REL-01) cresce a cada entrega com os indicadores dos módulos já entregues.

**Justificativa da ordem**

- E1 é pré-requisito de tudo, porque todo custo vem da compra e todo movimento depende do estoque.
- E2 entrega o centro do produto (PVD §5.5).
- E3 depende de produtos em estoque.
- E4 automatiza fluxos que já existem e funcionam manualmente.

A importação é Must no MVP (PVD §9.3), mas fica por último porque depende do fluxo manual. Se ela for crítica no dia a dia, pode ser antecipada para depois de E1 sem quebrar as dependências.

---

## 20. Rastreabilidade

### 20.1 PVD → requisitos → regras → critérios

| PVD | Requisitos | Regras | Critérios |
|---|---|---|---|
| §5.1 Dashboard | RF-REL-01 | — | CA-31 |
| §5.2 Cadastros e unidades | RF-CAD-01 a 07 | RN-40 | CA-06, CA-07, CA-28 |
| §5.3 Compras e importação | RF-CMP-01 a 15, RF-TLG-01 a 05 | RN-04 a 06, RN-10, RN-11, RN-20, RN-38 | CA-05, CA-07 a CA-13 |
| §5.3 Recebimento físico | RF-REC-01 a 08 | RN-07, RN-09, RN-21 | CA-10, CA-39, CA-41, CA-42 |
| §5.4 Estoque | RF-EST-01 a 12 | RN-01 a 03, RN-17 a 19, RN-34 | CA-17 a CA-21, CA-23, CA-29, CA-40 |
| §5.5 Fichas | RF-FIC-01 a 06 | RN-12 a 14, RN-23 | CA-14 a CA-16 |
| §5.6 Produção | RF-OP-01 a 09, RF-FRI-01 a 05 | RN-08, RN-15, RN-16, RN-22, RN-25, RN-26 | CA-15, CA-16, CA-24, CA-25 |
| §5.7 Conservação e etiquetas | RF-ETQ-01 a 07 | RN-27, RN-28 | CA-20 a CA-22 |
| §5.8 Vendas e encomendas | RF-VEN-01 a 11 | RN-29, RN-30, RN-35, RN-36 | CA-26 a CA-30 |
| §5.9 Custos | RF-CUS-01 a 07 | RN-20 a 26, RN-33 | CA-12, CA-14, CA-16, CA-33, CA-34 |
| §5.10 Financeiro | RF-FIN-01 a 10 | RN-31 a 34, RN-37 | CA-10, CA-35 a CA-39 |
| §5.11 Relatórios | RF-REL-02 a 04 | §16 | CA-32, CA-34 |
| §5.12 Configurações | RF-ADM-03, RF-ETQ-04 | — | — |
| §6 Princípios (histórico, rastreabilidade, automação supervisionada) | RF-EST-01, RF-EST-12, RF-FIC-04, RF-OP-07, RF-VEN-03, RF-FIN-09 | RN-01, RN-10, RN-14, RN-25, RN-30, RN-34 | CA-15, CA-17, CA-23 |
| §7 Não funcionais | RNF-01 a 16, RF-ADM-01 a 08 | RN-06, RN-08, RN-39 | CA-01 a CA-04 |
| §9 Critérios de sucesso 1 a 14 | ver 20.3 | — | — |

### 20.2 Decisões → requisitos

| Decisão | Requisitos e regras |
|---|---|
| DEC-F1-001 | RF-REC-01/02, RN-07, RN-21 |
| DEC-F1-002 | RF-ETQ-06 |
| DEC-F1-003 | RF-FIN-01 a 10 |
| DEC-F1-004 | RF-OP-05, RF-EST-12, RN-17 |
| DEC-F2-001 | Este documento (base) |
| DEC-F2-002 | §14, RF-EXT-01 a 04 |
| DEC-F2-003 | RF-CUS-01, RN-22 |
| DEC-F2-004 | RF-EST-05, RN-18 |
| DEC-F2-005 | RF-EST-06, RN-02 |
| DEC-F2-006 | RF-CMP-10, RF-FIN-01, RN-33 |
| DEC-F2-007 | RF-REC-03/04, RF-FIN-08, RN-09 |
| DEC-F2-008 | RF-CMP-13, RN-20 |
| DEC-F2-009 | RF-CMP-03 a 05, RF-CMP-14, §13 |
| DEC-F2-010 | RN-20, REG-01 |
| DEC-F2-011 | RF-CAD-03 |
| DEC-F2-012 | RF-FRI-01, 03, 05 |
| DEC-F2-013 | RF-FRI-02, 04, RF-CUS-05 |
| DEC-F2-014 | RF-ETQ-01, RF-EST-03, RN-28 |
| DEC-F2-015 | RF-OP-02, RN-15 |
| DEC-F2-016 | RF-OP-03 |
| DEC-F2-017 | RF-OP-05, RN-16 |
| DEC-F2-018 | RF-VEN-04, RF-FIN-06 |
| DEC-F2-019 | RF-VEN-06/07, RN-35 |
| DEC-F2-020 | RF-CAD-04, RF-VEN-01 |
| DEC-F2-021 | RF-VEN-09/10, RN-36 |
| DEC-F2-022 | RF-CUS-04/05, RF-REL-03, RN-24 |
| DEC-F2-023 | RF-FRI-04, RN-26 |
| DEC-F2-024 | RF-FIN-03, RN-32 |
| DEC-F2-025 | RF-FIN-04 |
| DEC-F2-026 | RF-FIN-05, RN-37 |
| DEC-F2-027 | RF-FIN-09, RN-34 |
| DEC-F2-028 | RF-CAD-01, RF-CAD-04, RN-29 |
| DEC-F2-029 | RF-CAD-02, RN-40 |
| DEC-F2-030 | RF-CAD-06, RF-CMP-06/07, RN-11 |
| DEC-F2-031 | RF-EST-09 |
| DEC-F2-032 | RF-EST-05, RN-18 |
| DEC-F2-033 | RF-EST-07, RF-CUS-02 |
| DEC-F2-034 | RF-ADM-04 a 06, RNF-06 |
| DEC-F2-035 | RNF-16, REG-03 |
| DEC-F2-036 | RF-REC-07 |
| DEC-F2-037 | RF-CMP-15, RF-REC-06 |
| DEC-F2-038 | RF-REC-08 |
| DEC-F2-039 | RN-05 |
| DEC-F2-040 | RF-VEN-07 |
| DEC-F2-041 | FL-08 A1 |
| DEC-F2-042 | FL-11 A1 |
| DEC-F2-043 | §16 (itens a vencer) |
| DEC-F2-044 | RN-23 |
| DEC-F2-045 | RN-24 |
| DEC-F2-046 | RF-REL-04 |
| DEC-F2-047 | RF-FIC-03, RN-13, RF-OP-08, FL-05 E1, FL-12 E1, RNF-05, 06, 09, 12, §13 |

### 20.3 Critérios de sucesso do PVD (§9) → critérios de aceite

| Sucesso PVD | Critérios de aceite |
|---|---|
| 1. Cadastrar ingredientes, produtos e fichas | CA-06, CA-14 |
| 2. Sub-receitas com custo proporcional | CA-14, CA-16 |
| 3. Importar pelo Telegram e pela web | CA-05, CA-13 |
| 4. Preparar para revisão, sinalizar incertos, impedir duplicidade | CA-07, CA-09, CA-11 |
| 5. Aprovação preserva o documento, recebimento parcial e pendência | CA-10, CA-39 |
| 6. Produção com consumo, rendimento, perdas e lotes sem duplicidade | CA-16, CA-24 |
| 7. Identificação, estado de conservação e etiqueta | CA-20 a CA-22 |
| 8. Vendas e encomendas movimentam estoque corretamente | CA-26, CA-28, CA-30 |
| 9. Custos estimados e reais compreensíveis | CA-14, CA-16, CA-33, CA-34 |
| 10. Histórico não reescrito | CA-15, CA-28 |
| 11. Relatórios | CA-32 |
| 12. Backup restaurável e verificável | CA-03, CA-04 |
| 13. Despesas, contas e pagamentos rastreáveis | CA-35 a CA-38 |
| 14. Vínculo com lotes e ausência sinalizada | CA-23 |

---

## 21. Parecer de prontidão

**Situação:** o PRD v1.0 cobre todos os módulos do MVP. As regras críticas de estoque, produção, custos, compras, financeiro e rastreabilidade estão especificadas, com critérios de aceite testáveis e rastreáveis até o PVD e as decisões. Não há contradição conhecida entre PVD e PRD sem registro: a única ampliação, contas a receber, foi aprovada (DEC-F2-018).

**Parecer:** **pronto para seguir para UX/UI e arquitetura, com ressalvas.** PRD aprovado pelo proprietário em 18/10/2026.

**Ressalvas:**

1. **REG-02:** os critérios sanitários de validade precisam ser obtidos de fonte competente antes de o sistema entrar em operação real. Isso não impede o desenvolvimento.
2. **PR-04 e PR-05** ficam para a fase de arquitetura.

**Fora desta fase:** escolha de tecnologia, esquema físico, design de telas e backlog detalhado.

## Histórico de versões

| Versão | Data | Descrição | Situação |
|---|---|---|---|
| 0.1 | 18/10/2026 | Primeira versão completa, com as regras não decididas marcadas como proposta | Substituída |
| 0.2 | 18/10/2026 | Propostas revisadas (DEC-F2-036 a 047); PR-01 e PR-02 encerradas | Substituída |
| 1.0 | 18/10/2026 | Aprovação do proprietário | **Aprovada** |
