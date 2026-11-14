# Servidor MCP do agente

O agente (voz, Telegram, texto) conversa com o Sabor Express por um servidor
[MCP](https://modelcontextprotocol.io) que roda **dentro** do projeto. As
ferramentas ficam em `agente/ferramentas.py`; a lógica das consultas, em
`agente/consultas.py` (a mesma que a API REST provisória `/api/agente/` usa);
a das gravações, em `agente/acoes.py`, `agente/compras.py`, `agente/decisoes.py`,
`agente/vendas.py`, `agente/despesas.py`, `agente/lotes.py` e `agente/propostas.py`; as de custos,
margens, relatórios e estudo de preço (só leitura), em `agente/custos.py`.
São 92 ferramentas.
O sistema faz todas as contas; o modelo só escolhe a ferramenta e fala o
resultado.

## Iniciar

Transporte **stdio**: o cliente inicia o processo e fala com ele por
stdin/stdout. Não há porta nem token — quem consegue rodar o comando já tem
acesso à máquina.

```bash
uv run python manage.py mcp_agente
```

Rodado à mão ele fica parado esperando o protocolo no stdin (Ctrl+C sai). O
stdout é exclusivo do protocolo; logs saem no stderr. O banco é o do
`settings` (o `db.sqlite3` do checkout em `cwd`).

## Ferramentas

Erros voltam como `{"erro": "mensagem"}`; com ambiguidade (dois produtos,
ingrediente em dois blocos, duas produções em andamento, dois lotes) vem também
`"opcoes": [...]` para o agente perguntar qual. Quantidades vêm como
`{"valor", "unidade", "texto"}` — o `texto` é o que se fala ("1,2 kg").

A busca por nome ignora maiúsculas e acentos e casa quando **cada palavra dita**
aparece no nome ("farinha empanamento" casa "Farinha de trigo (Empanamento)").
Nome idêntico a uma opção ganha das parciais. Onde há `producao_id` opcional,
omitir vale para **a única** produção em andamento.

### Alçada

As ferramentas seguem a alçada aprovada pelo dono (design §6.2). Todas as
gravações passam por `nucleo.operacoes.executar` com `canal="agente"` e
`autor="agente-mcp"`, ficando na trilha de auditoria.

| Nível | Efeito | Devolve |
|---|---|---|
| 0 — consulta | não grava | os dados |
| 1 — faz e repete | grava na hora | `dito` (frase do que foi feito, já formatada) + `resultado` |
| 2 — repete e espera o sim | **não grava**; cria uma proposta | `confirmar` (frase terminando em "Confirma?") + `proposta_id` + `expira_em` |
| 3 — nunca | não existe ferramenta; o núcleo recusa | `{"erro": ...}` |

| Ferramenta | Nível | Parâmetros | O que faz |
|---|---|---|---|
| `consultar_estoque` | 0 | `busca=""` | itens ativos com saldo, mínimo e `abaixo_do_minimo` |
| `ver_validades` | 0 | `dias=3` | lotes com estoque vencendo até hoje+`dias` (inclui vencidos) |
| `buscar_produtos` | 0 | `busca=""` | produtos com peso da unidade e saldo em unidades |
| `calcular_receita` | 0 | `produto`, `unidades` | ingredientes necessários, falta e `da_para_produzir` |
| `ver_producoes` | 0 | `status="andamento"` | até 20 produções, mais recentes primeiro |
| `ver_producao` | 0 | `producao_id` | etapa atual, falta pesar, cronômetros, perdas, custo |
| `registrar_peso` | 1 | `item`, `quantidade`, `unidade=""`, `lote=""`, `producao_id?` | peso usado de um ingrediente ("Requeijão: 355 g registrado. Falta pesar: ...") |
| `usar_previsto` | 1 | `item=""`, `producao_id?` | "usei o previsto" num ingrediente ou em todos os que faltam |
| `proxima_etapa` | 1 | `producao_id?` | avança e lê a etapa nova |
| `ir_para_etapa` | 1 | `etapa`, `producao_id?` | vai para a etapa N (0 = pesagem) |
| `iniciar_cronometro` | 1 | `minutos?`, `nome=""`, `producao_id?` | liga cronômetro; sem minutos usa o tempo da etapa |
| `parar_cronometro` | 1 | `nome=""`, `producao_id?` | desliga o cronômetro (pelo nome, se houver vários) |
| `registrar_etiqueta` | 1 | `produto`, `conservacao=""`, `copias?`, `lote=""` | registra impressão de etiquetas (sem cópias: uma por unidade) |
| `iniciar_producao` | 2 | `produto`, `unidades`, `forma="cru"` | propõe iniciar a produção |
| `concluir_producao` | 2 | `quantidade_boa`, `conservacao`, `perdas=0`, `motivo_perdas=""`, `anotacao=""`, `validade=""`, `justificativa=""`, `producao_id?` | propõe concluir (com 0 boas, a proposta é a confirmação da perda total) |
| `cancelar_producao` | 2 | `motivo`, `producao_id?` | propõe cancelar |
| `mudar_conservacao` | 2 | `produto`, `para`, `quantidade?`, `de=""`, `lote=""`, `validade=""`, `justificativa=""` | propõe mudar a conservação (sem quantidade: o lote todo) |
| `entrada_estoque` | 2 | `item`, `quantidade`, `unidade`, `custo_total`, `motivo`, `validade=""`, `lote=""` | propõe entrada manual com valor |
| `criar_tamanho` | 2 | `salgado`, `peso_g`, `oleo_por_unidade?` | propõe criar um tamanho novo de um salgado |
| `confirmar_proposta` | 2 | `proposta_id` | **grava** a proposta — só depois do "sim" falado |
| `recusar_proposta` | 2 | `proposta_id` | descarta a proposta sem gravar |

`iniciar_producao` e `concluir_producao` aceitam também `justificativa_falta`:
com ela, a produção começa (ou fecha) mesmo faltando estoque, e o que faltar
vira **consumo pendente** de conciliar (o "Confirma?" da conclusão diz quanto).

Conservação aceita `fresco`, `resfriado` (ou "geladeira") e `congelado` (ou
"freezer"); forma, `cru` ou `frito`. Datas em `AAAA-MM-DD`.

### Compras, recebimento e contas a pagar

Lógica em `agente/compras.py` (Plano 3, fase 2b). Tudo chega pelo **nome
falado** — fornecedor e item — e o sistema acha a compra, a linha, a parcela ou
o lote; com mais de um candidato volta `opcoes` (com o número para a próxima
chamada: `compra_id`, `parcela_id`, `lote_id`...). As consultas devolvem
`texto` pronto para falar, com dinheiro por extenso ("12 reais e 50
centavos"), datas faladas ("hoje", "em 12 de dezembro") e **totais já
somados**; os números vêm também como `{"valor", "texto"}`.

**O sistema nunca paga nada:** `registrar_pagamento` só anota que o dono pagou.
Tudo que mexe com dinheiro ou com entrada/baixa de estoque é nível 2.

| Ferramenta | Nível | Parâmetros | O que faz |
|---|---|---|---|
| `buscar_fornecedores` | 0 | `busca=""` | fornecedores (nome, contato, ativo) |
| `ver_compras_em_aberto` | 0 | `fornecedor=""` | compras esperando entrega e o que falta de cada uma |
| `ver_falta_receber` | 0 | `fornecedor=""`, `item=""` | itens que não chegaram, com a idade em dias |
| `ver_compra` | 0 | `compra_id` | itens (chegou/falta/não entregue), parcelas e avisos |
| `ver_contas` | 0 | `situacao="todas"` (`vencidas`, `a_vencer`), `dias=7`, `fornecedor=""` | parcelas em aberto com `total` e `vencido` somados |
| `ver_divida_fornecedores` | 0 | `fornecedor=""` | quanto se deve a cada um, quanto venceu, total geral; com fornecedor, a parcela mais antiga |
| `ver_avisos_de_ajuste` | 0 | — | avisos em aberto (não entregue, devolução) |
| `ver_consumos_pendentes` | 0 | `item=""` | o que foi usado sem estoque e se já há lote para conciliar |
| `ultimo_preco` | 0 | `item` | custo da última compra por quilo/litro/unidade (com rateio) |
| `cadastrar_fornecedor` | 1 | `nome`, `contato=""`, `documento=""` | cadastra (recusa nome repetido, mesmo com outra caixa ou sem acento) |
| `resolver_aviso` | 1 | `observacao`, `aviso_id?` | anota o que foi feito com o aviso; sem id, o único aberto |
| `registrar_compra` | 2 | `fornecedor`, `itens=[{item, quantidade, unidade, valor, validade?, lote?}]`, `condicao` (`a_vista`/`a_prazo`), `total?`, `prazo_dias?`, `vencimento=""`, `parcelas=1`, `intervalo_dias=30`, `data_compra=""`, `forma_pagamento=""`, `frete=0`, `desconto=0`, `documento=""`, `justificativa=""`, `ja_recebido=false` | lança e aprova a compra e a conta; sem `total`, soma itens + frete − desconto; a prazo exige `prazo_dias` ou `vencimento` (as parcelas são divididas pelo sistema); `ja_recebido` dá entrada no estoque junto |
| `receber_compra` | 2 | `fornecedor=""`, `item=""`, `quantidade?`, `unidade=""`, `validade=""`, `lote=""`, `compra_id?`, `itens?=[{item, quantidade?, unidade?, validade?, lote?}]` | acha a compra em aberto pelo fornecedor/item; sem quantidade recebe o que falta; sem item, tudo o que falta da compra |
| `encerrar_pendencia` | 2 | `motivo`, `fornecedor=""`, `item=""`, `compra_id?` | o resto não vem; a conta não muda, gera aviso |
| `registrar_pagamento` | 2 | `fornecedor=""`, `valor?`, `data_pagamento=""`, `forma=""`, `compra_id?`, `parcela_id?`, `juros=0`, `multa=0`, `desconto=0`, `motivo_diferenca=""` | anota o pagamento; parcelas da mesma compra → a mais antiga; de compras diferentes → o `valor` igual ao saldo desfaz, senão `opcoes`; sem valor, o saldo todo |
| `estornar_pagamento` | 2 | `motivo`, `fornecedor=""`, `pagamento_id?` | desfaz um pagamento anotado |
| `estornar_recebimento` | 2 | `motivo`, `fornecedor=""`, `item=""`, `compra_id?`, `recebimento_id?` | desfaz um recebimento (só se o lote não foi usado) |
| `cancelar_compra` | 2 | `motivo`, `compra_id?`, `fornecedor=""` | cancela compra sem recebimento nem pagamento (pelo fornecedor, só as sem recebimento são candidatas) |
| `devolver_ao_fornecedor` | 2 | `item`, `quantidade`, `motivo`, `unidade=""`, `fornecedor=""`, `compra_id?`, `lote_id?` | baixa de lote vindo de compra + aviso de ajuste |
| `receber_bonificacao` | 2 | `item`, `quantidade`, `unidade`, `motivo`, `validade=""`, `lote=""`, `fornecedor=""`, `compra_id?` | entrada a custo zero |
| `conciliar_consumo` | 2 | `item=""`, `pendente_id?`, `lote_id?` | liga o consumo pendente a um lote (sem lote: o que vence primeiro com saldo) e fecha o custo |

Unidades faladas: "quilo(s)" → kg, "grama(s)" → g, "litro(s)" → L,
"mililitro(s)" → mL, "unidade(s)" → un; outras (saco, caixa) precisam da
conversão cadastrada no item (o núcleo recusa: "Cadastre o fator de 'saco'...").

O "Confirma?" de cada proposta traz itens, quantidades, total, condição e
vencimentos, e os **alertas de duplicata** do núcleo ("Atenção: Possível
duplicata: a compra 3 é do mesmo fornecedor, na mesma data e com o mesmo
total"). Depois de confirmar um recebimento ou bonificação, o `dito` avisa se
há consumo pendente que pode ser conciliado com o que entrou.

```
usuário: "comprei 20 quilos de farinha por 90 reais no Atacadão, pago em 30 dias"
agente → registrar_compra(fornecedor="Atacadão", condicao="a_prazo", prazo_dias=30,
                          itens=[{"item": "farinha", "quantidade": 20, "unidade": "kg", "valor": 90}])
       ← {"confirmar": "Lançar compra do fornecedor Atacadão, hoje: 20 kg de Farinha de trigo por 90 reais.
                        Total 90 reais, a prazo, vence em 12 de dezembro. Confirma?", "proposta_id": 21, ...}
usuário: "chegaram 8 dos 10 quilos de farinha do Atacadão"
agente → receber_compra(fornecedor="Atacadão", item="farinha", quantidade=8, unidade="kg")
       ← {"confirmar": "Receber da compra 5, fornecedor Atacadão: 8 kg de Farinha de trigo.
                        Fica faltando 2 kg de Farinha de trigo. Confirma?", ...}
usuário: "quanto devo ao Atacadão?"
agente → ver_divida_fornecedores(fornecedor="Atacadão")
       ← {"texto": "Com o fornecedor Atacadão, você deve 90 reais em 1 parcela, nada vencido. A mais antiga: ..."}
```

"Comprei e já chegou" (`ja_recebido`) é uma proposta só, executada como duas
operações do núcleo (`registrar_compra` com a chave da proposta e
`receber_compra` com a chave + `:receber`): se o recebimento for recusado na
confirmação, a compra fica lançada, a proposta continua pendente com o erro, e
confirmar de novo só refaz o recebimento.

O trecho para o prompt do agente e um roteiro de teste por voz estão em
[`agente-instrucoes-compras.md`](agente-instrucoes-compras.md).

### Caixa de decisões, resumo do dia, histórico e backup

Lógica em `agente/decisoes.py` (Plano 4, fase 2b), sobre as consultas e os
serviços de `decisoes` e `backup.situacao` — nenhuma regra nova. O agente de
voz **só fala quando alguém fala com ele**: não avisa sozinho. A rotina
(`manage.py rotina_diaria`) enche a caixa; o agente a lê quando perguntado
("o que tem para decidir?", "como está o dia?", "alguma novidade?", "o que foi
feito hoje?", "quando foi o último backup?").

**Fala curta:** o `texto` nunca lê lista longa. Com muitos itens, diz os
totais, os **três** mais urgentes e quantos faltam ("E tem mais 4."); o resto
fica nos dados (`itens`, `assuntos`, `operacoes`) para quando o dono pedir.
Cada item da caixa é dito pelo **número** da decisão ("Número 12, para
aprovar: ..."), para o dono responder "aprova a doze", "ciente da quinze".

| Ferramenta | Nível | Parâmetros | O que faz |
|---|---|---|---|
| `ver_resumo_do_dia` | 0 | — | `resumo_do_dia()`: abre com a caixa ("Na caixa, 1 decisão para aprovar e 3 avisos."), depois até três assuntos do mais urgente (vencido, backup atrasado ou ausente, contas vencidas, despesas vencidas sem valor, validade perto, estoque baixo, contas a vencer, despesas sem valor vencendo, compras atrasadas, consumo e custo pendentes, avisos de ajuste, produções em andamento, compras a chegar) e "Tem mais N assuntos: ... Quer que eu fale?"; dia vazio: "Dia tranquilo: ...". `assuntos` traz todas as frases |
| `ver_decisoes` | 0 | `tipo=""` (`decisao`, `aviso`), `origem=""` | pendentes da caixa: decisões antes dos avisos e, entre elas, pela urgência da origem; `origem` aceita o assunto falado ("vencido", "contas", "estoque baixo", "consumo pendente", "ficha"); desconhecido → `erro` + `opcoes` |
| `ver_decisao` | 0 | `decisao_id` | uma decisão: texto, desde quando, último erro ao aprovar, ou quem decidiu, quando e o motivo |
| `ver_historico` | 0 | `periodo="hoje"` (`ontem`, `semana`, `mes`, `AAAA-MM-DD`), `autor=""`, `canal=""` (`voz`, `tela`, `sistema`), `operacao=""`, `so_erros=false` | `historico_operacoes`: total, as três mais recentes (rótulo, hora, quem) e "E mais N"; `por_tipo` com a contagem por rótulo. Sem `canal`, a rotina automática (canal `sistema`) fica de fora; `operacao` casa com o rótulo ("compra", "pagamento", "peso") |
| `ver_backup` | 0 | — | `situacao_backup()`: último backup (dia e hora), quantos há, se está atrasado (mais de 26 h) ou se não há nenhum. Não devolve o caminho da pasta |
| `dar_ciencia` | 1 | `decisao_id` | `aprovar_decisao` num **aviso** ("Ciente do número 15: ... Saiu da caixa."); em decisão com operação → erro "precisa de aprovação" |
| `recusar_decisao` | 1 | `decisao_id`, `motivo` | `recusar_decisao` com o motivo dito pelo dono ("Recusei o número 12 (...). Motivo: ..."); sem motivo → erro pedindo o porquê; aviso não se recusa |
| `aprovar_decisao` | 2 | `decisao_id` | propõe aprovar: a aprovação (com a operação da decisão, `conciliar_consumo` ou `completar_reserva`) é **simulada** pelo núcleo e o `confirmar` repete o texto da decisão com os números ("Aprovar o número 12: ... Baixa do lote e custo de 5 reais; o custo da produção 3 fica fechado. Confirma?"); só `confirmar_proposta` grava. Aviso → erro "dê ciência" |

- **Aprovar executa uma vez só:** a proposta chama
  `decisoes.servicos.aprovar_decisao` com a chave da proposta, e o serviço roda
  a operação com a chave da decisão. Confirmar de novo devolve o mesmo
  resultado; pedir para aprovar de novo responde "já está aprovado".
- **Recusa do núcleo na confirmação** (o lote foi usado entre a pergunta e o
  "sim"): a decisão continua pendente, a proposta guarda o erro e a caixa passa
  a dizer "Da última vez não deu para aprovar: ...".
- Já decidida, expirada ou sem efeito → `erro` com a frase do que aconteceu
  (quem decidiu e o motivo).
- `dar_ciencia` e `recusar_decisao` seguem as chamadas repetidas do nível 1
  (a mesma chamada em 6 segundos volta com `"repetida": true`).
- O total de operações falado no resumo não conta a rotina automática (desde o
  Plano 7 o próprio `resumo_do_dia()["totais"]["operacoes_hoje"]` já vem sem a
  rotina; o agente usa esse número).

```
usuário: "o que tem para decidir?"
agente → ver_decisoes()
       ← {"texto": "Na caixa, 1 decisão para aprovar e 2 avisos. Número 12, para aprovar: Consumo pendente
                    de 1 kg de Farinha de trigo (produção 3): baixar do lote F1, que tem 10 kg. Número 9, aviso:
                    Leite venceu em 11/11: ...", "itens": [...]}
usuário: "aprova a doze"
agente → aprovar_decisao(decisao_id=12)
       ← {"confirmar": "Aprovar o número 12: ... Baixa do lote e custo de 5 reais. Confirma?", "proposta_id": 31}
usuário: "sim"
agente → confirmar_proposta(proposta_id=31)
usuário: "ciente da nove"
agente → dar_ciencia(decisao_id=9)
       ← {"dito": "Ciente do número 9: Leite venceu em 11/11: ... Saiu da caixa."}
```

O trecho para o prompt do agente e um roteiro de teste por voz estão em
[`agente-instrucoes-decisoes.md`](agente-instrucoes-decisoes.md).

### Vendas, encomendas, fritura e contas a receber

Lógica em `agente/vendas.py` (Plano 6, fase 2b), sobre os serviços e as
consultas de `vendas`, `producao.fritura`, `estoque` e `financeiro` — nenhuma
regra nova. O agente fala em **nomes**, nunca em ids: cada item de venda ou
encomenda é `{produto, quantidade, apresentacao?, forma?, conservacao?}` e o
sistema acha a apresentação (o jeito de vender, com preço) casando as palavras
ditas com "produto + apresentação + forma + conservação", ignorando acento,
caixa e plural ("duas caixas de coxinha congelada" casa "Coxinha 150 g — caixa
com 25 (cru, congelado)"; "crua", "frita", "geladeira", "freezer", "gramas"
também valem). Mais de um jeito de vender → `erro` + `opcoes` para perguntar.
Cliente, encomenda ("a encomenda do João"), venda, parcela e lote são achados
do mesmo jeito; com mais de um candidato volta `opcoes` com o número para a
próxima chamada (`encomenda_id`, `venda_id`, `parcela_id`, `pagamento_id`).

- **Preço não muda por voz** (plano 6, Q10): a venda e a encomenda usam o
  preço da tabela (`tabela` varejo ou atacado); não há desconto nem cadastro de
  preço por voz.
- **Venda, entrega, cancelamentos, fritura, perda e recebimento são nível 2**
  (Q1, Q11): numa cozinha barulhenta "2" e "12", "caixa" e "unidade" se
  confundem. O "Confirma?" repete quantidade, apresentação, produto, cliente,
  preço, total e condição calculados pelo núcleo na simulação.
- **O sistema nunca cobra nada:** `registrar_recebimento` só anota que o
  cliente pagou. Venda a prazo ("fiado") exige o cliente e o prazo (`prazo_dias`
  ou `vencimento`); as parcelas são divididas pelo sistema.
- Dias falados: `hoje`, `amanhã`, `depois de amanhã`, dia da semana ("sábado" =
  o próximo, hoje incluído) ou `AAAA-MM-DD`; hora `15:30` ou `15h`.
- `ver_vendas` não devolve margem: a margem (sempre **estimada**) fica só em
  `ver_margem` e nas outras ferramentas de custos (Plano 7, abaixo).

| Ferramenta | Nível | Parâmetros | O que faz |
|---|---|---|---|
| `ver_precos` | 0 | `produto=""` | `apresentacoes()`: preço de varejo e atacado de cada jeito de vender e quantas dá para vender agora |
| `ver_estoque_para_venda` | 0 | `produto=""` | `estoque_para_venda()`: por produto, forma e conservação, o livre, o reservado e o vencido |
| `buscar_clientes` | 0 | `busca=""` | clientes (nome, contato, ativo) |
| `ver_vendas` | 0 | `periodo="hoje"` (`ontem`, `semana`, `mes`, `AAAA-MM-DD`), `cliente=""` | `vendas()`: total, recebido na hora por forma de pagamento, a prazo, por produto, canceladas fora da conta; as 20 últimas vendas |
| `ver_venda` | 0 | `venda_id=None`, `cliente=""` | `detalhe_venda()`: itens, total e dia; só com cliente, a venda da conta mais antiga em aberto ou a última |
| `ver_encomendas` | 0 | `dia=""` (`hoje`, `amanhã`, dia da semana, `semana`, `AAAA-MM-DD`), `cliente=""` | `encomendas()` em aberto: prontas (tudo reservado) ou com o que falta reservar; vazio = todas, inclusive as atrasadas |
| `ver_encomenda` | 0 | `encomenda_id` | `detalhe_encomenda()`: itens, reservado e falta, total, sinal, saldo, situação, observação |
| `ver_necessidade_producao` | 0 | `dias=3` | `necessidade_producao()`: o que falta, quanto já dá para reservar do estoque livre e quanto produzir; não cria produção |
| `ver_a_receber` | 0 | `cliente=""`, `situacao="todas"` (`vencidas`, `a_vencer`), `dias=7` | com cliente: quanto deve, quanto venceu e a parcela mais antiga; sem: `devido_por_cliente()` com o total geral |
| `ver_sobras` | 0 | — | `sobras_fritas()`: fritos ainda no estoque, de quando são |
| `cadastrar_cliente` | 1 | `nome`, `contato=""` | `salvar_cliente` (recusa nome repetido, mesmo com outra caixa ou sem acento) |
| `completar_reserva` | 1 | `encomenda_id?`, `cliente=""` | `completar_reserva`: reserva o que entrou no estoque e troca o lote que venceria antes da entrega ("Encomenda 5 de João: reserva completa, está pronta para amanhã.") |
| `registrar_venda` | 2 | `itens=[{produto, quantidade, apresentacao?, forma?, conservacao?}]`, `cliente=""`, `condicao="a_vista"` (`a_prazo`/"fiado"), `forma_pagamento=""`, `tabela="varejo"`, `prazo_dias?`, `vencimento=""`, `parcelas=1`, `intervalo_dias=30` | `registrar_venda`: baixa pelo que vence primeiro; a prazo vira conta a receber |
| `cancelar_venda` | 2 | `motivo`, `venda_id?`, `cliente=""`, `destino="perda"` (`estoque`) | `cancelar_venda` inteira; sem número, pelo cliente ou entre as de hoje; cancela o recebível |
| `criar_encomenda` | 2 | `cliente`, `dia`, `itens`, `hora=""`, `modo="retirada"` (`entrega`), `observacao=""`, `sinal=0`, `sinal_forma=""`, `tabela="varejo"` | `criar_encomenda`: reserva o que há e diz o que falta produzir |
| `entregar_encomenda` | 2 | `encomenda_id?`, `cliente=""`, `condicao="a_vista"`, `forma_pagamento=""`, `prazo_dias?`, `vencimento=""`, `parcelas=1`, `intervalo_dias=30` | `entregar_encomenda`: vira venda uma vez só; o saldo (total − sinal) entra na hora ou fica a prazo |
| `cancelar_encomenda` | 2 | `motivo`, `encomenda_id?`, `cliente=""`, `devolver_sinal=true` | `cancelar_encomenda`: libera as reservas; o sinal fica anotado como devolvido ou retido |
| `registrar_fritura` | 2 | `produto`, `quantidade`, `boas?` (vazio = todas), `motivo_perdas=""`, `conservacao=""` (do cru), `destino="fresco"`, `validade=""`, `justificativa=""` | `registrar_fritura` do lote cru que vence primeiro (`lotes_para_fritar`); cru em duas conservações → `opcoes`; diz o lote, o custo por unidade e a validade do frito |
| `registrar_perda` | 2 | `produto`, `motivo`, `quantidade?` (vazio = o lote todo), `unidade=""`, `conservacao=""`, `forma=""`, `lote=""`, `vencido=false` | `registrar_perda` de salgado, ingrediente ou embalagem; mais de um lote → `opcoes`; descartar vencido libera a reserva |
| `registrar_recebimento` | 2 | `cliente=""`, `valor?`, `data_pagamento=""`, `forma=""`, `venda_id?`, `parcela_id?`, `juros=0`, `multa=0`, `desconto=0`, `motivo_diferenca=""` | `registrar_recebimento`: anota que o cliente pagou (parcelas da mesma venda → a mais antiga; vendas diferentes → o `valor` igual ao saldo desfaz, senão `opcoes`) |
| `estornar_recebimento_cliente` | 2 | `motivo`, `cliente=""`, `pagamento_id?` | `estornar_recebimento_cliente`: a parcela volta a ficar em aberto |

`estornar_recebimento` (sem `_cliente`) continua sendo o de **mercadoria** de
compra; `registrar_recebimento` é dinheiro de cliente, não `receber_compra`.

```
usuário: "vendi duas caixas de coxinha congelada pro João, fiado pra 30 dias"
agente → registrar_venda(itens=[{"produto": "coxinha", "apresentacao": "caixa", "conservacao": "congelada",
                                 "quantidade": 2}], cliente="João", condicao="fiado", prazo_dias=30)
       ← {"confirmar": "Vender 2 caixas com 25 de Coxinha 150 g, cru congelado, a 45 reais cada, para João.
                        Total 90 reais, a prazo, vence em 13 de dezembro. Confirma?", "proposta_id": 40, ...}
usuário: "sim"
agente → confirmar_proposta(proposta_id=40)
       ← {"dito": "Feito: Vender 2 caixas ... É a venda 12.", ...}
usuário: "o que tem de encomenda amanhã?"
agente → ver_encomendas(dia="amanhã")
       ← {"texto": "1 encomenda em aberto para amanhã. Encomenda 5 de Maria, para amanhã às 15h, retirada:
                    3 caixas com 25 de Coxinha 150 g, frito fresco; falta reservar 75 unidades de ..."}
```

**Caixa de decisões e resumo do dia com o Plano 6:** `ver_decisoes` reconhece
as origens novas (`origem`: "encomenda", "fiado"/"devendo", "sobra"); a
decisão de completar a reserva de uma encomenda se aprova com
`aprovar_decisao` ("Vou reservar para a encomenda 5 o que houver no estoque;
ela fica pronta, com tudo reservado. Confirma?"). `ver_resumo_do_dia` ganha os
assuntos encomendas atrasadas, encomendas de hoje (prontas e faltando),
contas a receber vencidas, o que falta produzir, sobra de frito, encomendas
dos próximos dias e vendas de hoje. O texto das decisões é falado sem
"15/11", "R$ 100,00" nem "30 un" (`agente.decisoes.falavel`); o texto
original continua em `texto_decisao` de `ver_decisao`.

O trecho para o prompt do agente e um roteiro de teste por voz estão em
[`agente-instrucoes-vendas.md`](agente-instrucoes-vendas.md).

### Custos, margens e relatórios

Lógica em `agente/custos.py` (Plano 7, fase 2b), sobre `custos.fichas`,
`custos.consultas` e `custos.relatorios` — nenhuma regra nova e **nenhuma
gravação**: as sete são de leitura (nível 0). O modelo de voz não faz conta
(design A3): toda diferença, porcentagem e ponto vem pronto no `texto`, e os
números estruturados vêm ao lado (Decimal como número, datas ISO).

- **Sempre estimado:** toda margem é dita "margem estimada" e o resultado do
  período "estimado", antes e (Plano 8) depois das despesas, com o que não
  inclui (RF-CUS-06, CA-33). A palavra "lucro" não aparece em nenhum `texto`.
  A margem **com indiretos** de referência (Plano 8) é dita à parte, como outra
  margem.
- **Dado faltante nunca vira zero:** ingrediente nunca comprado deixa o custo
  incompleto ("falta o preço de Queijo; nunca foi comprado"); venda com custo
  duvidoso fica **fora da margem** e o `texto` diz quantos itens, quanto e por
  quê; produção sem compra até o dia ou com custo pendente fica fora da
  comparação de custo.
- **Períodos falados:** `hoje`, `ontem`, `semana` ("esta semana"), `semana
  passada`, `mes` ("este mês"), `mes passado`, `ultimos 7 dias`, `ultimos 30
  dias` (os de `custos.consultas.intervalo`); outro → `erro` com as opções. A
  comparação é com o **mesmo trecho** do período anterior
  (`intervalo_anterior`: semana de segunda a hoje × a semana passada de
  segunda ao mesmo dia).
- **Fala curta:** no máximo três grupos, produtos ou apresentações no `texto`;
  o resto fica nos dados.
- **Preço, óleo e indiretos não mudam por voz**, e nenhuma ferramenta escolhe
  margem ou sugere preço; o preço calculado só aparece numa **simulação** com o
  número que o dono disser (`simular_preco`, abaixo).

| Ferramenta | Nível | Parâmetros | O que faz |
|---|---|---|---|
| `ver_custo` | 0 | `produto` (nome falado do tamanho, ou de uma preparação) | `custo_estimado` (ou `custo_preparacao`): ingredientes, indiretos, cru e frito por unidade, pela última compra de cada ingrediente, e o que não inclui; `partes` com cada preparação e item. Incompleto → diz o que falta, sem número. Dois tamanhos → `opcoes` |
| `ver_margem` | 0 | `periodo="semana"`, `agrupar="produto"` (`apresentacao`, `cliente`, `tabela`, `dia`), `comparar=true` | `intervalo` + `comparar_margens` com `intervalo_anterior` (ou `margens` sem comparar): margem estimada em %, em reais, variação em **pontos**, descontos, o que ficou fora e os três maiores grupos; depois, a margem **com indiretos** de referência ("Com os indiretos de referência por salgado ..., a margem estimada fica em N por cento") ou quantos itens não têm indireto |
| `ver_margem_tabela` | 0 | `produto=""` | `margem_apresentacoes`: custo estimado de cada jeito de vender e a margem estimada no varejo e no atacado pelo preço de tabela de hoje e, com referência, a margem com indiretos; sem custo → o que falta |
| `ver_mais_vendidos` | 0 | `periodo="mes"`, `ordem="receita"` (`unidades`, `margem`; "lucro" vira `margem`) | `ranking_produtos`: os três primeiros com a participação no total; na ordem margem, quantos ficaram fora |
| `ver_previsto_realizado` | 0 | `producao_id?`, `periodo="semana"`, `produto=""` | `previsto_realizado_producao` (uma) ou `previsto_realizado` (período): rendimento, custo previsto × real (diferença em reais e %), custo por unidade boa e os ingredientes que passaram do previsto; o que ficou fora da comparação |
| `ver_relatorio` | 0 | `periodo="mes"` | `relatorio_periodo`: vendas e margem estimada, perdas com valor, resultado estimado antes das despesas (e % da receita), produção, compras, dinheiro anotado, contas em aberto hoje, o que não desconta, o resultado **depois das despesas** (com o que falta) e as ressalvas |
| `ver_evolucao_preco` | 0 | `item` | `evolucao_preco`: preço por quilo/litro/unidade da última compra × a anterior e desde a primeira, em % |

```
usuário: "qual a minha margem esta semana? caiu?"
agente → ver_margem(periodo="semana")
       ← {"texto": "Margem estimada nesta semana: 88 por cento, 44 reais sobre 50 reais de vendas com custo.
                    Em relação ao mesmo trecho da semana passada, caiu 6 pontos; era 94 por cento. ... É margem
                    estimada: não inclui tributos sobre a venda, despesas comerciais e operacionais, indiretos
                    de fabricação e ajuste de óleo.", "totais": {...}, "variacao": {"pontos": -6.0, ...}}
usuário: "quanto me custa uma bolinha de queijo?"
agente → ver_custo(produto="bolinha de queijo")
       ← {"texto": "O custo estimado de Bolinha de queijo 20 g está incompleto: falta o preço de Queijo; nunca
                    foi comprado. Sem esse preço não dá para dizer o custo.", "completo": false, ...}
```

O trecho para o prompt do agente e um roteiro de teste por voz estão em
[`agente-instrucoes-custos.md`](agente-instrucoes-custos.md).

### Despesas, resultado depois das despesas e estudo de preço

Lógica em `agente/despesas.py` (despesas) e `agente/custos.py` (resultado,
indireto real, estudo e simulação de preço, ponto de equilíbrio) — Plano 8,
fase 2b, sobre `financeiro.despesas`, `financeiro.consultas`,
`custos.relatorios` e `custos.precos`. Nenhuma regra nova.

- **Despesa pelo nome falado:** "luz" casa com a despesa mensal Energia (ou a
  categoria Energia); "botijão" → gás, "diarista"/"faxina" → diária, "DAS" →
  impostos. Palavras como "conta", "boleto", "da" são ignoradas. Nome idêntico
  ganha das parciais; ambíguo → `erro` + `opcoes`.
- **Mês e datas falados:** `mes` vazio (este), "mês passado", "outubro",
  "AAAA-MM"; datas "hoje", "ontem", "amanhã", "dia 20" (vencimento: o próximo
  dia 20; pagamento: o último), "20 de dezembro", "AAAA-MM-DD". Na fala, o
  vencimento sai como "dia 10", "amanhã", "dia 2 de dezembro"; o mês da despesa
  como "Energia de novembro" (nunca "11/2026").
- **Sem valor nunca é zero:** despesa mensal sem valor aparece como "sem valor",
  fica fora das somas e deixa o resultado depois das despesas incompleto ("falta
  o valor de Internet de novembro"); taxa de canal não informada = "taxa não
  informada, sem conta".
- **O sistema só anota:** `pagar_despesa` acha a despesa em aberto (mensal do
  mês ou avulsa a pagar) e propõe anotar o pagamento (`pagar_despesa_do_mes` com
  o valor real, ou `registrar_pagamento` na avulsa); sem despesa em aberto com o
  nome, propõe lançar uma avulsa **já paga** (`lancar_despesa(paga=True)`) com a
  categoria pelo nome falado (sem categoria reconhecida → pergunta, com as
  categorias em `opcoes`). Já paga neste mês → `erro` (não lança em dobro).
- **Não por voz:** cadastrar/alterar despesa mensal (previsto, dia, categoria),
  categorias, canais e taxas, referências de óleo e indireto, preço.
- **Simulação é simulação:** `simular_preco` começa com "Simulação, o preço da
  tabela não muda" e termina com "É só uma simulação: o preço só muda pela
  tela, e quem decide é o dono"; a sobra pedida é a do dono, nunca escolhida
  pelo agente.

| Ferramenta | Nível | Parâmetros | O que faz |
|---|---|---|---|
| `ver_despesas` | 0 | `mes=""` | `despesas_do_mes` + `despesas_periodo` (por categoria): "Despesas de novembro: 3.280 reais lançados, 230 reais já com pagamento anotado, falta pagar 3.050 reais. Ainda sem valor, fora da conta: Internet; ... Vencidas: Energia, 850 reais, venceu dia 10. A pagar: ... Por categoria: ..." |
| `ver_despesas_a_pagar` | 0 | `situacao="todas"` (`vencidas`) | `despesas_em_aberto` (qualquer mês): "Falta pagar 3.050 reais de despesas, 850 reais já vencidos. Sem valor ainda, fora da soma: Internet de novembro. Energia de novembro, 850 reais, venceu dia 10; ..." |
| `ver_resultado` | 0 | `periodo="mes"` (como `ver_margem`) | `relatorio_periodo`: "Neste mês, de 1 a 13 de novembro, tudo estimado. Vendas: ... Resultado antes das despesas: ... Despesas do período: ..., com as mensais pela parte dos dias do período. Resultado estimado depois das despesas: ..., N por cento da receita. Ainda incompleto: falta o valor de Internet de novembro; o resultado de verdade é menor que este. ... Por categoria: ..." Sem despesa lançada: não diz número depois das despesas |
| `ver_indireto_real` | 0 | `mes=""` | `indireto_real`: "Conferência dos indiretos de novembro, de 1 a 13: N unidades boas produzidas; as despesas da produção ... somam ... Dá 82 centavos por salgado; a referência cadastrada é 74 centavos: o real está 8 centavos acima, 10,8 por cento. ... É estimado." |
| `ver_estudo_preco` | 0 | `produto=""`, `canal=""`, `tabela="varejo"` | `estudo_preco`: por jeito de vender (até três), CMV e % do preço, indiretos e, por canal (canais com a mesma taxa juntos), "sobram ..., N por cento do preço" ou "taxa não informada, sem conta"; "o preço da tabela não muda" |
| `simular_preco` | 0 | `produto`, `apresentacao=""`, `preco?` **ou** `sobra_pct?`, `canal=""` (padrão balcão), `tabela="varejo"`, `forma=""`, `conservacao=""` | `simular_preco` (rotulado "simulação"): com preço, quanto sobra; com a sobra que o dono quer, o preço que o sistema calcula (arredondado ao centavo), a diferença para o preço de hoje e o aviso de que o preço só muda pela tela. Canal sem taxa → `erro` |
| `ver_ponto_equilibrio` | 0 | `produto`, `apresentacao=""`, `canal=""`, `mes=""`, `forma=""`, `conservacao=""` | `ponto_equilibrio`: "Estimativa, como se todas as vendas fossem ...: cada venda deixa ... depois do CMV e da taxa; as despesas de novembro somam ... seria preciso vender 678 unidades, 3.390 reais de vendas no mês. Ficou fora, sem valor: Internet; com ela o número é maior." |
| `informar_valor_despesa` | 1 | `nome`, `valor`, `mes=""` | `informar_valor_despesa` na despesa mensal em aberto: "Anotado: Internet de novembro veio 99 reais e 90 centavos; estava lançada com ... Vence dia 10, ainda sem pagamento anotado." Com pagamento anotado, o núcleo recusa ("estorne o pagamento antes") |
| `pagar_despesa` | 2 | `nome`, `valor?`, `data_pagamento=""`, `forma=""`, `mes=""`, `categoria=""` | propõe **anotar** o pagamento: "Anotar o pagamento de Energia de novembro: 850 reais, paga hoje. Fica quitada. Confirma?" (com "(estava lançada com 850 reais; fica o valor real)" ou "(ela ainda não tinha valor; fica este)"); sem despesa em aberto: "Lançar a despesa Diarista, em Diária: 120 reais, paga hoje. Confirma?" |
| `lancar_despesa` | 2 | `descricao`, `valor`, `categoria=""`, `vencimento=""`, `paga=false`, `data_pagamento=""`, `forma=""` | propõe despesa avulsa a pagar ("Lançar a despesa Boleto do gás, em Gás: 230 reais, a pagar, vence dia 20. Confirma?") ou já paga; se for uma despesa mensal do mês ainda em aberto → `erro` mandando para `informar_valor_despesa`/`pagar_despesa` |
| `cancelar_despesa` | 2 | `motivo`, `nome=""`, `mes=""`, `conta_id?` | propõe cancelar (este mês ou o passado; `mes` para outro): "Cancelar a despesa Energia de novembro, 850 reais (motivo: lancei errado). O pagamento anotado de 850 reais é estornado junto. Ela sai das contas a pagar e do resultado. Confirma?". Sem motivo → `erro`; despesa sem valor → `erro` (não há conta) |

O resumo do dia (`ver_resumo_do_dia`) ganhou dois assuntos: despesas do mês
**vencidas sem valor** (logo depois das contas vencidas) e **sem valor vencendo
logo** (depois das contas a vencer); despesa com valor já entra em "contas
vencidas"/"a vencer", então não há aviso em dobro. Na caixa (`ver_decisoes`), o
assunto "despesa sem valor" filtra os lembretes da rotina, e os textos do núcleo
saem falados ("Energia de novembro", sem "11/2026" nem "parcela 1 de 1"). Em
`ver_contas`, despesa aparece como "despesa Energia de novembro, parcela única,
...".

```
usuário: "paguei 850 de luz"
agente → pagar_despesa(nome="luz", valor=850)
       ← {"confirmar": "Anotar o pagamento de Energia de novembro: 850 reais, paga hoje. Fica quitada. Confirma?",
          "proposta_id": 41, ...}
usuário: "sim"
agente → confirmar_proposta(proposta_id=41)
usuário: "quero que sobre 30 por cento na coxinha, qual o preço?"
agente → simular_preco(produto="coxinha", sobra_pct=30)
       ← {"texto": "Simulação, o preço da tabela não muda: para sobrar 30 por cento do preço no balcão, dinheiro, o
                    sistema calcula ... É só uma simulação: o preço só muda pela tela, e quem decide é o dono.", ...}
```

O trecho para o prompt do agente (com as frases antigas a substituir) e um
roteiro de teste por voz estão em
[`agente-instrucoes-despesas.md`](agente-instrucoes-despesas.md).

### Lotes na operação (Plano 9)

O lote é falado pelo nome da cozinha ("lote do dia 8", `estoque.lotes.nome_lote`), nunca pelo código, em
todas as ferramentas; o lote dito é resolvido em `agente/lotes.py` (nome, "dia 8", "segundo lote do dia 8",
código ou `lote_id` da separação; ambíguo → `opcoes`). Vencido sem motivo devolve `precisa_motivo: true` com a
pergunta pronta no `erro`; o motivo só vai ao núcleo quando há vencido, e a confirmação repete lote, dia em que
venceu e motivo. Prompt e roteiro de teste: [`agente-instrucoes-lotes.md`](agente-instrucoes-lotes.md).

| Ferramenta | Nível | Núcleo | Observação |
|---|---|---|---|
| `ver_separacao` | 0 | `vendas.lotes.separacao_venda` | `itens` como em `registrar_venda` (com `lotes` opcionais), `data` falada; `texto` + `linhas[].lotes[]` (`lote_id`, `lote`, `unidades`, `sobra`, `validade`, `vencido`) e `deixados` |
| `ver_separacao_encomenda` | 0 | `separacao_encomenda` | pela encomenda ou cliente; `lotes` como em `entregar_encomenda` |
| `contar_lote` | 2 | `estoque.servicos.ajustar_contagem` | altera saldo e valor: espera o "sim" como perda e entrada manual |
| `conferir_vencido` | 2 | `registrar_perda` / `ajustar_contagem` | resposta da decisão `lotes_vencidos`; "já foram vendidas" só devolve o `lote_id` para `registrar_venda` |
| `registrar_venda`, `entregar_encomenda` | 2 | `registrar_venda`, `entregar_encomenda` | + `lotes`, `data`, `motivo_vencido`; confirmação com "De onde sai: ..."; `dito` com os `avisos` |
| `registrar_fritura`, `mudar_conservacao`, `cancelar_venda`, `concluir_producao`, `conciliar_consumo` | 2 | os serviços de mesmo nome | + `motivo_vencido` (fritura e conservação também `lote` pelo nome) |
| `registrar_perda` | 2 | `registrar_perda` | + `destino` (perda, descarte, consumo da equipe, doação) |

### Fluxo de proposta (nível 2)

```
usuário: "começa 10 bolinhas"
agente → iniciar_producao(produto="bolinha", unidades=10)
       ← {"confirmar": "Iniciar a produção de 10 Bolinha 100 g, cru. Confirma?", "proposta_id": 7, ...}
agente: lê o "confirmar" em voz alta
usuário: "sim"
agente → confirmar_proposta(proposta_id=7)
       ← {"dito": "Feito: Iniciar a produção ... É a produção 12. Mise en place: ...", "resultado": {...}}
```

- **A confirmação está na estrutura:** a ferramenta de nível 2 nunca grava. Ela
  cria uma `agente.Proposta` pendente (quem propôs, canal, operação,
  parâmetros, resumo, validade) e só `confirmar_proposta` executa.
- **Validação antes de perguntar:** a operação é **simulada** pelo núcleo numa
  transação desfeita no fim. Toda recusa de regra (falta estoque, produção
  encerrada, sem critério de validade...) volta como `erro` já na proposta, e o
  resumo traz valores calculados pelo núcleo (validade nova, nome do tamanho).
  A simulação não deixa rastro.
- **Validade curta:** 5 minutos (`agente.propostas.VALIDADE`). Depois disso a
  proposta vira `expirada` e confirmar devolve erro ("peça de novo").
- **Confirmar duas vezes não duplica:** a execução usa a chave da proposta
  (`proposta:<uuid>`) em `executar`; a segunda chamada devolve o mesmo
  resultado. Recusada ou expirada → erro. Confirmada não pode ser recusada.
- **Se o núcleo recusar na confirmação** (o estado mudou desde a proposta), a
  proposta continua pendente com o `erro` anotado, e a recusa fica na trilha.
- As propostas aparecem no admin (só leitura). A caixa de decisões (Plano 4) é
  outra coisa — vive dias e é criada pelo sistema —, mas aprovar uma decisão por
  voz passa por uma proposta (`aprovar_decisao`).

### Chamadas repetidas (nível 1)

Modelos às vezes repetem a mesma chamada (chamadas paralelas, nova tentativa).
Cada gravação de nível 1 usa a chave `agente:<ação>:<hash>:<único>`, em que o
hash junta a ação e os argumentos **já resolvidos** (linha do preparo, gramas
na unidade base, lote, cronômetro...). Se a mesma chamada deu certo há menos de
**6 segundos** (`agente.acoes.JANELA_REPETICAO`), nada é gravado de novo: volta
o resultado anterior com `"repetida": true`. Depois da janela, o mesmo pedido
vale de novo — "próxima etapa" dita duas vezes avança duas vezes, porque entre
um pedido e outro o agente fala a etapa (mais que a janela).

## Configurar um cliente stdio

Pipecat (`MCPClient`) ou o SDK `mcp` em Python:

```python
from mcp import StdioServerParameters

parametros = StdioServerParameters(
    command="/home/quadradois/.local/bin/uv",
    args=["run", "--quiet", "python", "manage.py", "mcp_agente"],
    cwd="/home/quadradois/Sabor-Express",
    env={"SABOR_DEBUG": "1"},
)
```

- `cwd`: raiz do checkout cujo `db.sqlite3` deve ser lido.
- `env`: o SDK junta este dict com um ambiente mínimo (`HOME`, `PATH`...). Em
  produção (`SABOR_DEBUG=0`) passe também `SABOR_SECRET_KEY`. O
  `SABOR_AGENTE_TOKEN` não é usado pelo MCP.

Equivalente em JSON (Claude Desktop, Claude Code e afins):

```json
{
  "mcpServers": {
    "sabor-express": {
      "command": "/home/quadradois/.local/bin/uv",
      "args": ["run", "--quiet", "python", "manage.py", "mcp_agente"],
      "cwd": "/home/quadradois/Sabor-Express",
      "env": {"SABOR_DEBUG": "1"}
    }
  }
}
```
