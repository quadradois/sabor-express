# Plano 3, fase 2b — pendências das ferramentas do agente

O que ficou de fora ou depende de outra fase, achado ao ligar compras,
recebimento e contas a pagar ao servidor MCP. Nenhuma regra do núcleo mudou.

## Núcleo

- **Fornecedor repetido com acento ou outra caixa.** `cadastros.servicos.salvar_fornecedor`
  procura repetido com `nome__iexact`, que no SQLite só ignora a caixa de
  letras ASCII: "ATACADÃO" e "Atacadao" passam como fornecedores novos ao lado
  de "Atacadão". O agente já se protege (`agente.compras.cadastrar_fornecedor`
  compara sem acento e sem caixa antes de gravar); a tela continua exposta.
  Correção sugerida: comparar com o nome normalizado em Python (como
  `agente.consultas._normal`) dentro do serviço.

## Fora do alcance do agente (só pela tela)

- Cadastrar item novo e conversão de unidade de compra (saco, caixa). O agente
  devolve o erro do núcleo ("Cadastre o fator de 'saco' para ...") e orienta a
  usar a tela.
- Trocar parcelas ou vencimento depois de lançada (Q6): só cancelando e
  lançando de novo.
- Pagar acima do saldo da parcela para adiantar a próxima (Q4): recusado pelo
  núcleo; o agente fala a recusa.

## Decisões a confirmar com o dono

- `registrar_pagamento` é nível 2 (Q1). Mudar para nível 1 é trocar
  `@escrita(2)` por `@escrita(1)` e devolver `dito` em vez de proposta.
- "Comprei e já chegou" (`registrar_compra` com `ja_recebido`) é uma proposta
  executada como duas operações do núcleo. Se o recebimento for recusado na
  confirmação (o estado mudou desde a proposta), a compra fica lançada sem
  recebimento e a proposta continua pendente com o erro; confirmar de novo só
  refaz o recebimento. Alternativa: um serviço único no núcleo.
- `registrar_pagamento` com parcelas de compras diferentes do mesmo fornecedor:
  sem `valor` igual a um saldo, devolve `opcoes` em vez de escolher a mais
  antiga (pode haver boletos diferentes no mesmo dia).

## Para depois

- Contas a vencer no resumo da manhã quando a fila de tarefas existir
  (design §6.7; Plano 4).
- Validar no Gemini Live o parâmetro lista de objetos (`itens` de
  `registrar_compra` e `receber_compra`). Os esquemas vão sem `$ref`; se o
  Pipecat ou o Gemini recusarem objetos aninhados, a saída é aceitar um item
  por chamada com parâmetros escalares.
- As consultas de contas calculam saldo parcela a parcela em Python (algumas
  consultas por parcela). Suficiente para o volume de uma cozinha; rever se
  passar de centenas de parcelas em aberto.
