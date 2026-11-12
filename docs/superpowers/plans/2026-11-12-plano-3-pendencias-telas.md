# Plano 3 — pendências das telas (fase 2a)

Telas entregues: fornecedores, nova compra, compra (detalhe/receber/encerrar/estornar/devolver/cancelar), compras em aberto, falta receber, bonificação, contas a pagar, avisos de ajuste, consumos pendentes; ajuste em Produção nova e resumo em Hoje.

## Pendências

1. **Nova compra: número fixo de linhas (8).** Sem JavaScript para adicionar linhas; compra com mais de 8 itens precisa ser lançada em duas notas ou pelo agente.
2. **Sem prévia do custo na tela.** `custos_das_linhas` existe no núcleo, mas a tela não mostra o custo unitário antes de lançar (precisaria de JS ou de um passo de conferência).
3. **Parcelas só por divisão igual** (`dividir_parcelas`): n parcelas, primeiro vencimento e intervalo. Não há edição parcela a parcela (valores/datas diferentes).
4. **"Recebi tudo agora" usa uma única validade** para todos os itens e lote em branco; itens com validades diferentes devem ser recebidos pela tela da compra.
5. **Receber: sem atalho "receber tudo que falta"** por linha; a quantidade é digitada na unidade da compra (o campo mostra a quantidade documentada como dica). Converter o pendente (unidade base) para a unidade da compra exigiria conta na view; o núcleo não expõe isso.
6. **Devolução ao fornecedor** pede a quantidade na unidade base do item.
7. **Hoje**: a tela inicial não tinha resumo; foi acrescentado um aviso simples com contagens (vencidas, a vencer em 7 dias, falta receber, avisos, consumos pendentes).
8. **Produção: começar com falta** só aparece depois de "Ver receita" (quando algum ingrediente falta). O erro de falta no POST direto continua igual ao anterior.
9. **Estorno de recebimento/pagamento e cancelamento** pedem motivo, sem confirmação extra além do `<details>`.
10. Sem paginação em listas (pagamentos limitados aos últimos 30 dias).
