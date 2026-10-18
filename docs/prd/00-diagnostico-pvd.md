# Diagnóstico do PVD — Etapa 1 da fase de PRD

**Documento analisado:** `PVD_Sistema_de_Gestao_de_Salgados_v1.1_para_validacao.md` (única versão no repositório)
**Data:** 18/10/2026
**Status deste diagnóstico:** concluído; decisões incorporadas ao PRD v1.0 (aprovado em 18/10/2026)

Legenda: **D** = Definido · **AD** = A detalhar · **P** = Pendente · **C** = Conflitante
Prioridade de pendências: **Bloq** · **Alta** · **Média** · **Baixa**

---

## 1. Resumo executivo

Aplicação web responsiva (pt-BR), em rede local, servidor central com SQLite, para **um único usuário** gerir uma pequena produção de salgados: cadastros → compras (com importação de documentos via Telegram/web e aprovação humana) → recebimento físico → estoque por movimentação e lote → fichas técnicas compostas → produção em lotes → conservação e etiquetas internas → vendas/atacado/encomendas → custos estimados × reais → contas a pagar → relatórios. Princípios dominantes: histórico imutável, rastreabilidade, nenhuma automação com efeito financeiro ou de estoque sem aprovação.

## 2. Conflitos encontrados (C)

| ID | Conflito | Onde | Impacto |
|---|---|---|---|
| C-01 | O briefing desta fase trata o PVD como **aprovado**; o próprio PVD v1.1 declara "aguardando aprovação final expressa" (§12, §14). | PVD §12/§14 | **Bloq.** Sem aprovação, o PRD se apoiaria numa base não validada. |
| C-02 | O briefing inclui **assistente de cozinha com IA e voz**; o PVD não menciona voz nem assistente, e exclui do MVP "recursos de IA que não sejam necessários aos fluxos definidos" (§8). | PVD §8 | **Bloq.** Define se há um módulo inteiro de requisitos (§14 do PRD) ou apenas requisitos de extensibilidade. |
| C-03 | O PVD prevê sequência **Fase 2 (Discovery) → Fase 3 (PRD)**; o briefing une as duas nesta fase. | PVD §12 | Média. Resolvível declarando que a Etapa 2 desta fase *é* a Fase 2. |
| C-04 | Operação **"em rede local"** × extração de dados de fotos/PDFs, que provavelmente depende de serviço externo (OCR/LLM na internet). O Telegram já exige saída à internet, mas o envio de documentos fiscais a terceiros não foi decidido. | PVD §7 | Alta. Afeta privacidade de documentos fiscais e comportamento offline. |
| C-05 | "Aprovação com registro de **responsável**" e "**remetentes** autorizados" (plural) com MVP de usuário único. | §5.3, §7 | Baixa. Coerente se o modelo já registrar autor desde o início — vira requisito, não conflito real. |

## 3. Mapa de módulos e situação

| Módulo | Situação geral | Principais lacunas |
|---|---|---|
| Cadastros e unidades | **D** / AD | Conversões massa↔volume (densidade), unidades "por dúzia/pacote", embalagens são estocáveis? |
| Compras e importação | **D** fluxo; AD regras | Formatos aceitos, item não reconhecido cria cadastro?, rejeição/reabertura, frete/desconto/impostos no custo |
| Recebimento físico | **D** (DEC-F1-001) | Recebimento complementar, encerramento de pendência, devolução |
| Estoque | **D** princípio; AD regras | Estoque negativo?, política de escolha de lote (FEFO/manual), estados do lote, ajuste de inventário |
| Fichas técnicas | **D** conceito; AD versionamento | Qual versão vale para a OP; componente teórico × produzido na mesma ficha |
| Produção | **D** conceito; AD estados | Estados da OP, consumo real × padrão, OP parcial, correção pós-conclusão |
| Conservação/etiquetas | **D** (DEC-F1-002) | Congelamento como transformação (nova validade?), critérios sanitários, impressora |
| Vendas/encomendas | AD | Preço/tabela atacado, encomenda sem estoque, momento da reserva, **contas a receber** |
| Custos | AD / P | Método de custeio do estoque, rateio de indiretos, mão de obra do proprietário |
| Financeiro | **D** escopo básico (DEC-F1-003); P regras | Parcelamento, pagamento parcial, recorrência, estorno |
| Relatórios/dashboard | AD | Indicadores prioritários e fórmulas |
| Config/administração | AD | — |
| NFR (backup, segurança, desempenho) | AD | Frequência de backup/RPO, metas de desempenho dependem de hardware |
| IA/voz | **C-02** | Ver acima |

## 4. Requisitos já suficientemente definidos

1. Usuário único, web responsiva pt-BR, LAN, SQLite só via serviço central (§7, §10).
2. Compra importada fica pendente até aprovação explícita com data e autor (§5.3).
3. Idempotência: mesmo documento/mensagem/aprovação não efetiva compra duas vezes (§5.3).
4. Aprovação da compra ≠ recebimento físico ≠ obrigação financeira ≠ pagamento — quatro eventos distintos (§5.3, §5.10).
5. Estoque recebe só a quantidade física; diferença fica pendente, indisponível (DEC-F1-001).
6. Valor devido ao fornecedor **não** é recalculado pelo recebido sem regra comercial (§5.3).
7. Estoque por movimentações; ajuste manual exige motivo (§5.4).
8. Lote de ingrediente registrado quando houver; ausência marcada "sem lote informado"; toda produção gera lote próprio; sem origem fictícia (DEC-F1-004).
9. Preparação produzida consome o próprio estoque, nunca os ingredientes de novo (§5.5).
10. Preço novo atualiza custo estimado; custo histórico de produção concluída é imutável (§5.5, §6).
11. Custo unitário de fabricação = custo real ÷ quantidade boa (§5.6).
12. Produção concluída só muda via ajuste rastreável (§5.6).
13. Etiqueta térmica só interna; sem rótulo comercial; validade nunca inventada nem padronizada para todos (§5.7, DEC-F1-002).
14. Venda de caixa/kit converte para unidades físicas, sem baixa duplicada (§5.8).
15. Cancelamento reverte movimentos de forma rastreável respeitando o estado físico (§5.8).
16. Margem rotulada "estimada" quando incompleta (§5.9).
17. Lançamento manual de compra funciona sem Telegram; upload também pela web (§5.3, §7).
18. Telegram: bot privado, Bot API oficial, comunicação de saída (sem expor a app) (§7).
19. Backup/restauração de banco **e** arquivos, com restauração verificável (§7).

## 5. Lacunas e decisões pendentes (P / AD)

### Bloqueadoras
| ID | Decisão | Por que bloqueia | Recomendação inicial |
|---|---|---|---|
| P-01 | Aprovação do PVD v1.1 (C-01) | Base de rastreabilidade do PRD | Aprovar antes de seguir, ou aprovar com ressalvas registradas |
| P-02 | Escopo de IA/voz no MVP (C-02) | Cria ou não um módulo inteiro | Manter fora do MVP; PRD só exige requisitos de extensibilidade (ações via serviço de domínio, auditoria, nada grava direto no banco) |
| P-03 | Método de custeio do estoque: custo do lote (identificação específica) × média ponderada móvel | Define custo real da produção, de perdas e de vendas | Custo do lote consumido, já que os lotes são rastreados; média como fallback para itens sem lote |
| P-04 | Escolha do lote consumido: automática FEFO (vence primeiro sai primeiro), manual, ou FEFO sugerido com override | Define fluxo de produção, custo e rastreabilidade | FEFO sugerido, operador pode trocar |
| P-05 | Estoque negativo é permitido? | Toda baixa (produção, venda) depende disso | Bloquear por padrão; permitir "consumo pendente de conciliação" só com justificativa |

### Altas
| ID | Decisão |
|---|---|
| P-06 | **Contas a receber**: vendas a prazo/atacado/fiado existem? O PVD só cobre contas a pagar; vendas só registram "situação do pagamento". |
| P-07 | **Fritura / finalização**: o produto é vendido congelado cru, frito, ou ambos? Fritar é uma etapa de produção que transforma um lote (consome óleo, gera novo lote/validade)? |
| P-08 | **Congelamento**: é transferência de estado do mesmo lote ou gera nova validade? (critério sanitário — exige fonte competente) |
| P-09 | Encomenda sem estoque suficiente: gera necessidade de produção? Reserva acontece ao confirmar a encomenda ou ao produzir? Reserva por lote específico? |
| P-10 | Versionamento de ficha: a OP congela a versão ao ser criada ou ao ser iniciada? Ficha editada com OP aberta? |
| P-11 | Tratamento de frete, descontos e impostos no custo do ingrediente (rateio proporcional ao valor? ao peso?) |
| P-12 | Extração de documentos: serviço externo permitido (C-04)? Formatos obrigatórios no MVP (NF-e XML, QR Code NFC-e, foto de cupom, PDF)? |
| P-13 | Compra × conta a pagar: a obrigação nasce na aprovação da compra, no recebimento, ou é lançada à parte e vinculada? Como evitar que a compra de ingrediente vire também "despesa" (dupla contagem)? |
| P-14 | Recebimento complementar e encerramento de pendência (o fornecedor não vai entregar os 2 kg — o que acontece?) |

### Médias (antes do módulo correspondente)
P-15 Embalagens são itens de estoque consumidos na venda/produção? · P-16 Conversões massa↔volume com densidade · P-17 Item não reconhecido na importação pode criar ingrediente na própria revisão? · P-18 Estados e transições da OP (rascunho/planejada/em produção/concluída/cancelada; conclusão parcial) · P-19 Consumo real: operador informa tudo ou confirma o previsto e corrige exceções? · P-20 Tabelas de preço (unitário × atacado × kit) e quem autoriza desconto · P-21 Mão de obra do proprietário (pró-labore? hora estimada?) e rateio de energia/gás · P-22 Cancelamento de venda já entregue / devolução: produto volta ao estoque ou vira perda? · P-23 Regras financeiras (parcelamento, pagamento parcial, recorrência, estorno) — DEC-F1-003 · P-24 Inventário periódico (contagem e ajuste em lote) · P-25 Retenção de documentos fiscais e frequência de backup (RPO aceitável).

### Baixas (podem esperar)
P-26 Modelo da impressora e dimensões da etiqueta · P-27 Indicadores do dashboard · P-28 Filtros extras de relatórios · P-29 Metas de desempenho (dependem do hardware do servidor) · P-30 Estratégia de autenticação detalhada (usuário único simplifica).

### Pesquisa regulatória (não inventar — validar com fonte competente)
- Prazos de validade e condições por produto/conservação (vigilância sanitária local; referência a confirmar, ex.: RDC ANVISA 216/2004 para boas práticas em serviços de alimentação).
- Situações em que o lote do ingrediente é obrigatório.
- Obrigações para venda a revendedores/atacado (rotulagem comercial está fora do MVP, mas a venda pode exigir algo).
- Retenção de documentos fiscais de compra.

## 6. Riscos de integridade

| Risco | Origem | Mitigação a especificar |
|---|---|---|
| Dupla baixa de ingredientes | Sub-receita teórica × produzida | Regra de que a ficha referencia a *preparação*; a OP decide consumir estoque da preparação ou explodir ingredientes, nunca ambos |
| Dupla contagem de custo | Compra de ingrediente vira estoque **e** despesa | Conta a pagar de compra não é despesa operacional; custo entra via consumo |
| Compra efetivada duas vezes | Reenvio de documento, retry do Telegram, duplo clique | Chave de idempotência (chave fiscal/hash do arquivo + id de mensagem) e transição de estado única |
| Custo histórico reescrito | Recalcular OP concluída com preço atual | Custo da OP gravado na conclusão; correções geram ajuste datado |
| Saldo divergente do histórico | Edição direta de saldo | Saldo sempre derivado de movimentos; só ajustes com motivo |
| Caixa baixando 1 unidade | Conversão de apresentação | Fator de conversão obrigatório e congelado na linha de venda |
| Validade errada em etiqueta | Prazo padrão para tudo | Sem critério validado cadastrado → produto não imprime validade (bloqueia ou exige preenchimento manual) |
| Perda de documento | Falha entre receber no Telegram e gravar | Arquivo persistido antes de confirmar recebimento ao operador |
| Backup inconsistente | Banco e arquivos copiados em momentos diferentes | Procedimento único com verificação de restauração |

## 7. Dependências entre funcionalidades

```
Unidades/conversões → Cadastros (ingredientes, preparações, produtos, apresentações)
   → Compras (manual) → Recebimento → Movimentos de estoque + lotes
      → Importação (Telegram/web) [depende de Compras manual pronta]
   → Fichas técnicas (+ versões) → Ordens de produção → Lotes produzidos
      → Conservação/validade → Etiquetas
      → Vendas/encomendas/reservas
Custos: depende de Compras (preço) + Fichas (estimado) + Produção (real)
Financeiro: depende de Compras (vínculo) e Classificações
Relatórios/Dashboard: dependem de todos
Backup: transversal, desde a primeira entrega
```

Consequência: a importação inteligente **não** deve ser a primeira entrega — o fluxo manual de compra/recebimento é pré-requisito.

## 8. Decisões que podem ser tomadas depois sem comprometer o projeto

Impressora e layout de etiqueta; indicadores do dashboard; filtros de relatório; WhatsApp; multiusuário e perfis (desde que todo registro já guarde autor); assistente de voz (desde que toda ação passe por serviços de domínio auditáveis); stack técnica (fase de arquitetura).

## 9. Próximo passo

Resolver P-01 a P-05 com o proprietário; depois P-06 a P-14 em grupos por domínio (compras → estoque → produção → vendas → custos/financeiro), registrando cada resposta em `docs/prd/01-registro-decisoes.md`.

---

## 10. Situação após a Discovery (atualizado 18/10/2026)

Decisões registradas em `01-registro-decisoes.md` (DEC-F2-001 a 035).

- **Conflitos:** C-01 a C-04 resolvidos (DEC-F2-001, 002, 009). C-05 vira requisito: todo registro guarda o autor.
- **Bloqueadoras (P-01 a P-05):** todas resolvidas.
- **Altas (P-06 a P-14):** todas resolvidas.
- **Médias (P-15 a P-25):** todas resolvidas.
- **Baixas (P-26 a P-30):** em aberto, sem bloquear o PRD. Entram no PRD como pendências residuais.
- **Ampliação de escopo aprovada:** contas a receber básicas (DEC-F2-018).
- **Regulatórias, para fonte competente:** REG-01 (impostos no custo, contador), REG-02 (critérios sanitários de validade e sobras), REG-03 (guarda de documentos, contador). O PRD trata as três como dependências externas: o sistema funciona com critérios cadastrados e não presume regras.
- **Itens que o PRD vai propor para validação:** critério de rateio dos indiretos (DEC-F2-022); reserva vinculada a lote ou a produto (DEC-F2-019); estados e transições da OP, da compra, da venda e das contas; estorno também para movimentos de estoque (DEC-F2-027).
