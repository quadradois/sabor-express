# PVD — Sistema de Gestão de Produção e Vendas de Salgados

**Versão:** 1.1 — consolidada para validação final  
**Data de consolidação:** 18/10/2026  
**Status:** Fase 1 aberta — aguardando aprovação final do proprietário  
**Idioma:** Português brasileiro  
**Produto:** Sistema próprio de gestão de compras, estoque, fichas técnicas, produção, custos, controle financeiro operacional e vendas.

Esta versão incorpora quatro decisões expressas do proprietário e ajustes de coerência entre módulos. Os detalhes não aprovados permanecem identificados como pendências. A consolidação não representa a aprovação final do PVD.

## 1. Visão do produto

Desenvolver uma aplicação web responsiva para administrar a operação de produção e comercialização de salgados, desde a compra dos ingredientes até a produção, armazenamento, etiquetagem interna, venda, controle financeiro operacional e análise de custos.

O sistema deverá reduzir lançamentos manuais, melhorar a precisão dos custos, facilitar o planejamento da produção e oferecer rastreabilidade dos ingredientes e produtos acabados.

A aplicação será utilizada inicialmente pelo proprietário e operador do negócio, em uma rede local, com possibilidade de expansão futura para outros perfis e operações comerciais.

O produto deverá nascer simples para operar, mas com uma estrutura extensível que permita acrescentar funcionalidades, categorias de custos, integrações e novos modelos de negócio sem precisar reconstruir o sistema.

## 2. Problema que o produto resolve

A operação de uma pequena produção de salgados envolve informações que normalmente ficam distribuídas entre notas de compra, anotações, planilhas, receitas e controles manuais.

Essa fragmentação dificulta:

- Conhecer o custo real de cada produto.
- Atualizar os custos quando os preços dos ingredientes mudam.
- Controlar ingredientes e produtos acabados.
- Registrar perdas durante a produção.
- Planejar compras e evitar faltas ou desperdícios.
- Controlar produtos congelados e seus prazos de validade.
- Padronizar receitas e rendimentos.
- Gerenciar encomendas, vendas unitárias e vendas no atacado.
- Identificar quais produtos oferecem melhores resultados financeiros.
- Acompanhar despesas, contas a pagar, vencimentos e pagamentos.
- Recuperar o histórico de compras, produções e movimentações.

O sistema deverá centralizar essas informações e automatizar as tarefas repetitivas sem retirar do operador o controle das decisões importantes.

## 3. Público-alvo

### Público inicial

Proprietário e operador de uma pequena produção de salgados, responsável pelas compras, produção, estoque, vendas e gestão financeira operacional.

### Público futuro

- Pequenos fabricantes de alimentos.
- Revendedores de salgados.
- Lanchonetes e estabelecimentos que compram produtos para revenda.
- Operações com mais de um usuário ou ponto de venda.

O MVP será desenvolvido para uma única operação e um único usuário. A expansão para outros usuários, empresas ou unidades será planejada posteriormente, sem exigir que o produto seja deliberadamente limitado a uma estrutura impossível de ampliar.

## 4. Objetivos do produto

1. Centralizar compras, estoque, receitas, produção, vendas, custos e controle financeiro operacional.
2. Automatizar a entrada de dados de documentos de compra.
3. Padronizar receitas, sub-receitas, rendimentos e custos.
4. Registrar o consumo real de ingredientes e a produção efetiva.
5. Controlar produtos frescos, resfriados e congelados.
6. Gerar etiquetas térmicas a partir dos dados reais de produção.
7. Reduzir perdas e melhorar o planejamento de compras.
8. Apurar custos e margens estimadas com critérios transparentes.
9. Preservar o histórico operacional e financeiro gerencial.
10. Permitir a evolução do sistema sem reescrever seus módulos centrais.
11. Controlar despesas operacionais, contas a pagar, vencimentos e pagamentos.

## 5. Escopo funcional do MVP

### 5.1. Dashboard e visão operacional

O sistema deverá apresentar uma visão resumida da operação, com informações como:

- Vendas do dia e do período selecionado.
- Encomendas pendentes e próximas entregas.
- Ordens de produção abertas.
- Documentos de compra aguardando aprovação.
- Itens com estoque baixo.
- Produtos próximos do vencimento ou vencidos.
- Alertas de divergências que exigem intervenção.
- Contas a pagar próximas do vencimento ou vencidas.

O dashboard deverá permitir acesso rápido às principais tarefas, sem substituir as telas detalhadas de gestão.

### 5.2. Cadastros de produtos, ingredientes e unidades

O sistema deverá permitir cadastrar:

- Ingredientes e matérias-primas.
- Preparações intermediárias e sub-receitas.
- Produtos finais comercializados.
- Categorias e classificações.
- Fornecedores.
- Clientes, quando necessário para vendas e encomendas.
- Embalagens, unidades de venda e apresentações comerciais.

Cada ingrediente deverá possuir unidade de controle, unidade de compra quando aplicável, regras de conversão, identificação e informações de armazenamento pertinentes.

As conversões entre quilogramas e gramas, litros e mililitros, unidades, pacotes e caixas deverão ser consistentes. A conversão não poderá alterar indevidamente a quantidade física ou o custo do item.

O sistema deverá permitir ajustar os cadastros sem depender de alterações no código para cada novo ingrediente, produto ou unidade suportada.

### 5.3. Compras e importação inteligente de documentos

O sistema deverá oferecer duas formas de registrar uma compra:

1. Importação de documento para extração automática dos dados.
2. Lançamento manual, para exceções ou correções.

#### Entrada pelo Telegram

O MVP deverá disponibilizar um bot privado no Telegram para receber documentos enviados pelo operador.

O bot poderá receber fotos de cupons, imagens de notas, PDFs e arquivos fiscais estruturados compatíveis com a implementação.

O fluxo previsto será:

1. O operador envia o documento pelo Telegram.
2. O sistema identifica a mensagem e o remetente autorizado.
3. O arquivo original é armazenado e vinculado a um registro de importação.
4. O sistema extrai os dados disponíveis.
5. Os itens são associados aos ingredientes já cadastrados quando houver correspondência confiável.
6. O sistema apresenta a compra em uma fila de revisão.
7. O operador confere, corrige e aprova ou rejeita o lançamento.
8. Após a aprovação, o sistema efetiva o registro da compra. A entrada de estoque depende da confirmação das quantidades efetivamente recebidas, que poderá ocorrer no mesmo fluxo operacional.

A extração deverá buscar, quando disponíveis:

- Fornecedor e identificação fiscal.
- Data da compra.
- Descrição dos itens.
- Quantidades e unidades.
- Preços unitários e totais.
- Descontos e acréscimos identificados.
- Valor total do documento.
- Número ou chave identificadora do documento, quando disponível.

O sistema deverá comparar os valores extraídos com os totais do documento e destacar divergências.

Itens não reconhecidos, conversões incertas, documentos ilegíveis e possíveis inconsistências deverão ser apresentados para correção manual. O sistema não poderá presumir correspondências incertas como se fossem dados confirmados.

#### Aprovação e efetivação

A aprovação deverá ser uma operação explícita, com registro de data e responsável.

O sistema deverá impedir que a mesma compra seja efetivada duas vezes por reenvio do documento, repetição de mensagens ou tentativa duplicada de aprovação.

O documento original e os dados extraídos deverão permanecer disponíveis para consulta.

A importação não deverá depender exclusivamente do Telegram: o operador também poderá enviar documentos diretamente pela interface web.

#### Recebimento físico

O sistema deverá distinguir os dados informados na compra das quantidades efetivamente recebidas.

Quando houver divergência entre o documento e o recebimento físico, o operador deverá registrar a quantidade efetivamente recebida. Somente essa quantidade ingressará no estoque, enquanto o saldo não entregue permanecerá como pendência de recebimento, sem disponibilidade para consumo ou venda.

Exemplo aprovado: compra documentada de 10 kg, recebimento físico de 8 kg e pendência de 2 kg. A compra mantém a quantidade documentada; o estoque recebe apenas 8 kg.

A confirmação do recebimento físico e a aprovação dos dados da compra são eventos distintos, ainda que possam ocorrer na mesma operação. O valor devido ao fornecedor não deverá ser recalculado automaticamente apenas pela quantidade recebida, sem regra comercial definida.

O tratamento de entregas complementares, devoluções, abatimentos, documentos complementares e reflexos financeiros será levantado na Fase 2 — Product Discovery, antes de detalhamento no PRD. (DEC-F1-001)

### 5.4. Estoque de ingredientes e produtos acabados

O sistema deverá controlar separadamente os estoques de matérias-primas, preparações intermediárias e produtos finais.

Deverá registrar:

- Entradas por compra ou produção.
- Consumos por produção.
- Saídas por venda.
- Perdas, descartes e ajustes.
- Transferências entre estados de conservação, quando aplicáveis.
- Quantidades reservadas para encomendas.
- Lotes, datas e prazos de validade pertinentes.
- Histórico de movimentações.

O estoque deverá distinguir produtos disponíveis, reservados, vencidos, descartados e outras situações necessárias à operação.

Produtos frescos, resfriados e congelados deverão ter controles compatíveis com suas condições de conservação.

O sistema deverá permitir consultar saldos atuais e reconstruir o histórico das movimentações. Alterações manuais de estoque deverão exigir motivo e ficar registradas.

O sistema deverá registrar os lotes de origem dos ingredientes sempre que essa informação estiver disponível. Sua ausência não impedirá automaticamente o cadastro ou recebimento do ingrediente, mas deverá ficar explicitamente identificada como "sem lote informado", respeitadas as exigências sanitárias aplicáveis.

Cada lote de produção deverá possuir identificação própria. O sistema deverá preservar o vínculo entre os lotes conhecidos dos ingredientes efetivamente consumidos e os lotes de preparações ou produtos resultantes, sem criar identificação de origem fictícia. (DEC-F1-004)

### 5.5. Fichas técnicas simples, compostas e sub-receitas

As fichas técnicas serão uma parte central do produto.

O sistema deverá permitir cadastrar receitas de produtos finais e preparações intermediárias, como massas, recheios, molhos, misturas e empanamentos.

Cada ficha poderá conter ingredientes, outras preparações cadastradas ou ambos.

Cada ficha deverá contemplar:

- Ingredientes e componentes utilizados.
- Quantidades e unidades de medida.
- Rendimento previsto.
- Rendimento efetivo, quando produzido.
- Perdas previstas e reais, quando aplicáveis.
- Custo calculado.
- Histórico de versões.
- Instruções e observações operacionais pertinentes.

Exemplo: uma massa de coxinha poderá ter sua própria ficha técnica, rendimento e custo por quilograma. A ficha da coxinha poderá utilizar determinada quantidade dessa massa, somando o custo proporcional ao recheio, empanamento e demais componentes.

O sistema deverá distinguir dois cenários:

**Componente teórico:** a preparação é utilizada para calcular uma receita, sem que exista necessariamente um lote físico em estoque.

**Preparação produzida:** a preparação é fabricada, gera um lote e entra no estoque. Quando utilizada posteriormente, o sistema deverá consumir o estoque dessa preparação e não voltar a consumir os ingredientes originais.

Essa distinção é obrigatória para impedir dupla baixa de ingredientes e distorções de custos.

Alterações nos preços dos ingredientes deverão atualizar os custos estimados atuais das fichas dependentes. Entretanto, as alterações não poderão modificar os custos históricos das produções concluídas.

O detalhamento de versionamento e de como as fichas entram em vigor nas ordens de produção será definido no PRD.

### 5.6. Produção em lotes

O sistema deverá permitir planejar, iniciar, acompanhar e concluir produções de diferentes produtos e preparações.

Cada ordem de produção deverá registrar, conforme aplicável:

- Produto ou preparação produzida.
- Ficha técnica e versão utilizada.
- Quantidade planejada.
- Quantidades de ingredientes previstas.
- Quantidades efetivamente consumidas.
- Quantidade boa efetivamente produzida.
- Perdas e descartes.
- Datas e horários relevantes.
- Lote gerado.
- Estado de conservação e destino do produto.
- Observações e divergências.

O sistema deverá calcular o custo previsto e o custo real da produção, conforme os dados disponíveis.

O custo unitário de fabricação deverá considerar a quantidade boa efetivamente produzida, e não apenas a quantidade planejada.

A conclusão da ordem deverá registrar a saída dos insumos e a entrada dos produtos resultantes de forma consistente, evitando movimentações duplicadas.

Produções concluídas não poderão ser alteradas silenciosamente. Correções deverão gerar histórico e ajustes rastreáveis.

### 5.7. Conservação, validade e etiquetagem térmica

O MVP deverá permitir registrar lotes de produtos frescos, resfriados e congelados, mantendo as informações relevantes para identificação, conservação e controle de validade.

No MVP, a impressão térmica será utilizada exclusivamente para etiquetas internas de identificação, produção, conservação e armazenamento. Os modelos internos deverão permitir apresentar, conforme aplicável:

- Nome do produto.
- Identificação do lote.
- Data de fabricação ou preparação.
- Prazo de validade.
- Condições de conservação.
- Quantidade produzida ou armazenada, quando pertinente.
- Outras informações configuradas para o produto.

As datas deverão ser calculadas ou preenchidas a partir de critérios previamente definidos e validados para cada produto e condição de conservação. O sistema não deverá inventar prazos de validade nem aplicar automaticamente o mesmo prazo a todos os produtos.

A impressão e a reimpressão deverão manter registro suficiente para rastreabilidade operacional.

As etiquetas do MVP serão exclusivamente para controle interno, não constituindo rótulos comerciais destinados ao consumidor ou a revendedores. A emissão de rótulos comerciais completos permanece fora do escopo do MVP. (DEC-F1-002)

Os critérios de validade, identificação interna e conservação deverão ser previamente validados conforme as exigências sanitárias aplicáveis; etiquetas internas não substituem outras obrigações eventualmente exigíveis para comercialização.

### 5.8. Vendas, encomendas e entregas

O sistema deverá registrar vendas diretas, vendas no atacado e encomendas.

Deverá permitir:

- Vender por unidade ou por apresentação comercial.
- Utilizar embalagens, caixas e kits compostos por quantidades definidas.
- Registrar cliente, quando pertinente.
- Informar quantidades, preços e descontos autorizados.
- Registrar forma e situação do pagamento.
- Registrar entrega, retirada e situação do pedido.
- Reservar produtos para encomendas.
- Acompanhar pedidos pendentes, atendidos e cancelados.

As embalagens e apresentações comerciais deverão converter corretamente para as quantidades físicas movimentadas no estoque.

O sistema deverá impedir que a venda de uma caixa desconte apenas uma unidade quando a caixa contém várias unidades, ou que desconte as mesmas unidades mais de uma vez.

O cancelamento de vendas e encomendas deverá reverter as movimentações correspondentes de forma rastreável, respeitando o estado físico real dos produtos.

### 5.9. Custos e despesas configuráveis

O sistema deverá calcular custos de ingredientes, preparações intermediárias, produtos acabados e produções.

As categorias de custos deverão ser configuráveis, evitando listas rígidas que impeçam a evolução da operação.

O modelo inicial deverá contemplar:

- Ingredientes e matérias-primas.
- Embalagens.
- Óleo e outros insumos de fritura.
- Materiais de produção e separação.
- Mão de obra.
- Energia e gás.
- Comissões de venda.
- Entregas e logística.
- Marketing.
- Despesas operacionais pertinentes.
- Amortização ou depreciação gerencial de investimentos.

O sistema deverá permitir definir métodos de apropriação compatíveis com a natureza de cada custo, como valor fixo, percentual, por unidade, lote, pedido ou período, conforme aplicável.

Custos de fabricação deverão ser apresentados separadamente das despesas comerciais, operacionais e da recuperação gerencial de investimentos.

O sistema deverá diferenciar custo estimado e custo efetivamente apurado com base nos dados registrados, informando os critérios utilizados. O custo de fabricação e as despesas financeiras ou operacionais deverão permanecer conceitualmente distintos, evitando que um pagamento gere duplicação de custos já reconhecidos.

A margem apresentada deverá ser identificada como estimada quando não incluir todas as despesas, tributos, taxas e demais componentes necessários para apurar o resultado líquido.

A metodologia de custos, o tratamento de frete, descontos, impostos e despesas indiretas deverá ser levantada na Fase 2 e detalhada no PRD.

### 5.10. Controle financeiro operacional

O MVP incluirá controle financeiro operacional para registrar despesas, contas a pagar, vencimentos e pagamentos. Trata-se de uma ampliação do escopo inicial, expressamente aprovada pelo proprietário. Não equivale a uma solução contábil completa.

O sistema deverá permitir, no escopo básico:

- Registrar despesas operacionais e sua classificação.
- Registrar contas a pagar e respectivos vencimentos.
- Consultar obrigações pendentes, vencidas e pagas, segundo regras a detalhar.
- Registrar pagamentos realizados e preservar seus históricos.
- Consultar despesas, contas e pagamentos por período e situação.
- Preservar a relação entre compras e obrigações financeiras quando houver vínculo, prevenindo lançamentos duplicados.

A aprovação de uma compra, o recebimento físico de mercadorias, o registro de uma obrigação financeira e sua quitação são eventos distintos. O sistema deverá preservar a consistência desses registros sem produzir baixas de estoque ou despesas em duplicidade.

As regras de parcelamento, pagamentos parciais, recorrência, abatimentos, cancelamentos, estornos e tratamento de diferenças entre compra e recebimento serão investigadas na Fase 2. Esta versão não considera tais comportamentos especializados automaticamente aprovados. (DEC-F1-003)

### 5.11. Relatórios e indicadores

O MVP deverá oferecer relatórios operacionais que permitam acompanhar:

- Compras por fornecedor e período.
- Evolução dos preços de ingredientes.
- Estoque atual e movimentações.
- Itens próximos do vencimento e vencidos.
- Produção prevista versus realizada.
- Consumo de ingredientes e perdas.
- Custo previsto versus custo real.
- Vendas por produto e período.
- Vendas unitárias e no atacado.
- Encomendas pendentes e concluídas.
- Custos estimados e margens estimadas por produto.
- Despesas e pagamentos por período.
- Contas a pagar por vencimento e situação.

Os relatórios deverão permitir filtros por datas e produtos, conforme pertinente.

O objetivo é apoiar decisões de compra, produção, preço e comercialização, sem pretender substituir um sistema contábil completo.

### 5.12. Configurações e administração

O sistema deverá oferecer configurações para os principais elementos operacionais, incluindo:

- Unidades de medida e conversões suportadas.
- Categorias de custos e métodos de apropriação.
- Classificações utilizadas no controle financeiro operacional.
- Categorias de produtos.
- Modelos de etiquetas.
- Critérios de validade validados para cada produto.
- Parâmetros de alertas de estoque.
- Integração com Telegram.
- Dados básicos da operação.

O MVP terá um único usuário operacional, mas deverá registrar as operações relevantes e preservar a possibilidade de incorporar perfis de acesso posteriormente.

## 6. Princípios de produto

### Simplicidade operacional

As tarefas recorrentes devem exigir poucos passos. A automação deve reduzir trabalho manual, e não criar telas complexas para administrar a própria automação.

### Extensibilidade

Cadastros, categorias de custos, modelos de etiquetas e integrações deverão permitir expansão sem alterações desnecessárias no núcleo do sistema.

### Consistência dos dados

Compras, estoques, produções, vendas e custos deverão ser conciliáveis. O sistema não poderá manter registros contraditórios sem indicar a divergência.

### Histórico preservado

Alterações de preços, receitas, fichas técnicas e cadastros não deverão reescrever os resultados históricos de produções ou vendas concluídas.

### Rastreabilidade

O sistema deverá permitir identificar a origem e o destino das principais movimentações e consultar documentos que sustentem os registros.

### Automação supervisionada

A extração automatizada poderá preparar lançamentos, mas decisões com impacto financeiro e de estoque deverão respeitar os pontos de aprovação definidos.

### Configurabilidade

Parâmetros operacionais deverão ser configuráveis sempre que isso fizer sentido, sem permitir combinações que comprometam a consistência dos dados.

## 7. Requisitos não funcionais e diretrizes técnicas iniciais

### Plataforma e acesso

- Aplicação web responsiva.
- Interface em português brasileiro.
- Acesso por navegador em computadores, tablets e celulares conectados à rede local.
- Serviço central executado em um computador da rede.
- Banco SQLite acessado pelo serviço central, nunca compartilhado para acesso concorrente direto por vários dispositivos.
- Operação local dependente de o computador central e o serviço estarem disponíveis.

### Integração com Telegram

- Bot privado, com autorização explícita dos remetentes.
- Recepção de documentos e confirmação de processamento.
- Comunicação desacoplada do módulo de compras.
- Armazenamento do arquivo original e tratamento de falhas.
- Possibilidade de substituir ou adicionar outro canal no futuro.
- Preferência inicial por integração oficial com a Bot API do Telegram.
- Comunicação de saída para o Telegram, evitando a necessidade de expor diretamente a aplicação local à internet.

A integração não deverá impedir o lançamento manual de compras se o Telegram estiver indisponível.

### Segurança e integridade

- Autenticação para acesso à aplicação.
- Proteção de arquivos e documentos fiscais.
- Validação dos dados recebidos de integrações externas.
- Prevenção de lançamentos e aprovações duplicados.
- Registro de operações relevantes.
- Controle de concorrência e transações para evitar inconsistências.
- Tratamento de erros sem perda silenciosa de documentos ou movimentações.

### Backup e recuperação

O sistema deverá oferecer backup e restauração do banco de dados e dos documentos associados.

O procedimento de backup deverá considerar a consistência do banco e dos arquivos. A restauração deverá ser verificável, e o plano de operação deverá definir uma frequência de backup adequada ao volume de dados.

### Desempenho e manutenção

A aplicação deverá ser adequada ao volume inicial de uma pequena operação e permitir evolução modular.

O projeto deverá separar interface, regras de negócio, persistência e integrações externas para reduzir acoplamento e facilitar manutenção.

## 8. Fora do escopo do MVP

Não fazem parte do escopo inicial:

- Aplicativo nativo para Android ou iOS.
- Acesso público à aplicação pela internet.
- Integração com WhatsApp.
- Plataforma multiempresa completa.
- Gestão avançada de revendedores e clientes corporativos.
- Portais de clientes ou fornecedores.
- Integrações com marketplaces.
- Integração bancária avançada.
- Emissão fiscal integrada e gestão tributária completa.
- Contabilidade completa.
- Sistema completo de recursos humanos e folha de pagamento.
- Automação sem aprovação para lançamentos financeiros e de estoque.
- Rótulos comerciais completos destinados ao consumidor ou à revenda.
- Recursos de inteligência artificial que não sejam necessários aos fluxos definidos para o MVP.

Esses itens poderão ser avaliados futuramente conforme necessidade real, retorno esperado e complexidade.

## 9. Critérios de sucesso do MVP

O MVP será considerado operacionalmente satisfatório quando:

1. O operador conseguir cadastrar ingredientes, produtos e fichas técnicas.
2. Uma ficha técnica puder reutilizar sub-receitas com cálculo proporcional de custos.
3. O operador conseguir importar uma nota ou cupom pelo Telegram e também pela interface web.
4. O sistema conseguir preparar uma compra para revisão, indicar dados incertos e impedir sua efetivação duplicada.
5. A aprovação de uma compra preservar os dados documentais; a confirmação de recebimento registrar somente as quantidades fisicamente entregues no estoque, com saldo pendente identificável e sem duplicidade.
6. A produção registrar consumo, rendimento, perdas e lotes sem duplicidade.
7. Produtos acabados puderem ser identificados, controlados por estado de conservação e etiquetados internamente.
8. Vendas unitárias, atacadistas e encomendas movimentarem corretamente os estoques.
9. O sistema apresentar custos estimados e reais com critérios compreensíveis.
10. Alterações posteriores em preços e fichas não modificarem indevidamente os históricos concluídos.
11. Os principais relatórios operacionais puderem ser consultados.
12. Um backup puder ser restaurado e a integridade dos registros verificada.
13. Despesas, contas a pagar, vencimentos e pagamentos puderem ser registrados e consultados com histórico rastreável.
14. A produção preservar os vínculos com lotes de ingredientes conhecidos e sinalizar explicitamente a ausência de lote de origem.

## 10. Decisões já tomadas

- O produto será desenvolvido especificamente para a operação inicial.
- O MVP terá um único usuário operacional.
- A interface será web e responsiva.
- O uso inicial será em rede local.
- SQLite será utilizado por meio de um serviço central.
- O sistema controlará ingredientes, preparações intermediárias, produtos frescos, resfriados e congelados.
- As fichas técnicas compostas e sub-receitas farão parte do MVP.
- O sistema terá compras, produção em lotes, vendas diretas, atacado e encomendas.
- A etiquetagem térmica do MVP será exclusivamente para controle interno de produção e armazenamento (DEC-F1-002).
- As categorias de custos deverão ser extensíveis.
- A entrada automatizada de documentos com aprovação humana fará parte do MVP.
- O Telegram será o primeiro canal de entrada de documentos.
- O WhatsApp poderá ser avaliado posteriormente.
- Backup, rastreabilidade, integridade e histórico serão requisitos iniciais.
- O recebimento parcial preservará a compra documental, atualizará o estoque apenas com a quantidade recebida e manterá a diferença pendente (DEC-F1-001).
- O MVP contemplará despesas, contas a pagar, vencimentos e pagamentos (DEC-F1-003).
- Os lotes de origem dos ingredientes serão registrados sempre que disponíveis, com ausência de lote explicitamente sinalizada, e cada produção terá lote próprio (DEC-F1-004).

## 11. Pendências para o Product Discovery e as etapas seguintes

Antes do desenvolvimento, deverão ser detalhados:

1. Regras exatas de estoque, reserva, recebimentos complementares, perdas e ajustes, respeitando a DEC-F1-001.
2. Regras de versionamento e utilização de fichas técnicas nas ordens de produção.
3. Metodologia de cálculo de custos e rateio de despesas.
4. Tratamento de descontos, frete, tributos e divergências nos documentos de compra.
5. Regras de aprovação, rejeição e correção de importações.
6. Formatos de documentos aceitos e estratégia de extração de dados.
7. Impressora térmica, dimensões e campos das etiquetas internas, respeitando a DEC-F1-002.
8. Critérios de validade, conservação e requisitos sanitários aplicáveis.
9. Regras de cancelamento de vendas, devoluções e encomendas.
10. Política de backup, restauração e retenção de documentos.
11. Tecnologias e estrutura de implantação do serviço central.
12. Estratégia de autenticação e proteção da integração com Telegram.
13. Indicadores prioritários do dashboard e relatórios.
14. Testes de consistência dos cálculos, estoque e histórico.
15. Tratamento financeiro de parcelamentos, pagamentos parciais, despesas recorrentes, estornos e cancelamentos.
16. Vínculo entre compras, contas a pagar, pagamentos e divergências de recebimento, preservando a distinção entre fatos físicos e financeiros.
17. Tratamento operacional de itens sem lote informado e das condições que exigirem identificação obrigatória por normas sanitárias.

## 12. Próxima etapa e condição de aprovação

Esta versão 1.1 foi consolidada para revisão. **A Fase 1 permanece aberta e o PVD ainda aguarda aprovação final expressa do proprietário.** A autorização para consolidar o documento não equivale à aprovação final de seu conteúdo.

Após a aprovação do PVD, a próxima fase será a **Fase 2 — Product Discovery e levantamento de regras de negócio**, organizada por domínios, começando pelas decisões que mais afetam a integridade de compras, estoque, produção e financeiro.

Somente após o levantamento e a validação das regras críticas será iniciada a **Fase 3 — PRD (Documento de Requisitos do Produto)**, para transformar a visão em requisitos verificáveis, fluxos, cenários de erro, critérios de aceitação e prioridades do MVP.

As fases seguintes serão UX/UI, arquitetura técnica, backlog e planejamento de desenvolvimento, e acompanhamento da implementação, de acordo com os critérios de conclusão de cada etapa. O desenvolvimento não deverá começar antes de as regras críticas e decisões técnicas pertinentes estarem suficientemente especificadas e validadas.

## 13. Registro de decisões aprovadas na Fase 1

| Identificador | Decisão aprovada | Data | Situação |
| --- | --- | --- | --- |
| DEC-F1-001 | Compra documentada preservada; estoque recebe apenas a quantidade física confirmada; diferença permanece pendente. | 18/10/2026 | Aprovada |
| DEC-F1-002 | Etiquetas térmicas exclusivamente para identificação e controle interno no MVP. | 18/10/2026 | Aprovada |
| DEC-F1-003 | MVP inclui despesas, contas a pagar, vencimentos e pagamentos. | 18/10/2026 | Aprovada (regras detalhadas pendentes) |
| DEC-F1-004 | Registrar lotes de ingredientes quando informados e indicar ausências; cada produção terá lote próprio. | 18/10/2026 | Aprovada |

As decisões da tabela foram confirmadas pelo proprietário. As soluções e exceções expressamente indicadas como pendentes não são consideradas decisões aprovadas.

## 14. Histórico de versões e validação

| Versão | Data | Descrição | Situação |
| --- | --- | --- | --- |
| 1.0 | Anterior | PVD consolidado que serviu de referência à revisão da Fase 1. | Documento-base |
| 1.1 | 18/10/2026 | Incorporação das DEC-F1-001 a DEC-F1-004, atualização cruzada dos módulos e correção da sequência das fases. | Aguardando aprovação final |

**Aprovação final do PVD v1.1:** pendente de manifestação expressa do proprietário.  
**Situação da Fase 1:** em validação.  
**Fase 2 — Product Discovery:** não iniciada.
