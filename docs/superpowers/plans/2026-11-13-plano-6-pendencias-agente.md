# Plano 6, fase 2b — pendências das ferramentas do agente

O que ficou de fora ou depende de outra fase, achado ao ligar vendas,
encomendas, fritura, perda e contas a receber ao servidor MCP
(`agente/vendas.py`, Tasks 15–18 de `2026-11-13-plano-6-vendas.md`). Nenhum
modelo, serviço, consulta ou regra do núcleo mudou; tudo usa o "Contrato para
a fase 2" do plano. Branch `claude/onda4-ferramentas`; 70 ferramentas.

## Decisões tomadas na execução (revisáveis pelo dono)

- **Fritura por voz é nível 2**, não nível 1 como sugeria a tabela do
  contrato: o pedido desta fase pôs venda, perda, fritura, entrega e
  cancelamentos como "repete e espera o sim". Voltar a nível 1 é trocar o
  `@escrita(2)` de `registrar_fritura` em `agente/ferramentas.py` (e a função
  passa a gravar direto, como `completar_reserva`).
- **Nomes das ferramentas:** `registrar_venda` e `criar_encomenda` (o contrato
  sugeria `vender` e `nova_encomenda`), no padrão de `registrar_compra`.
  `estornar_recebimento_cliente` porque `estornar_recebimento` já é o da
  mercadoria de compra; a docstring de `registrar_recebimento` diz que não é
  `receber_compra`.
- **Preço sempre o da tabela:** sem `preco` nos itens (desconto manual por
  linha, RF-VEN-01, só pela tela), por Q10. Se o dono quiser desconto por
  voz, é um campo `preco` no item com a confirmação dizendo "em vez de 45".
- **Achar a apresentação pelo que foi dito:** as palavras faladas (produto,
  apresentação, forma, conservação) precisam todas casar com
  "produto + nome da apresentação + forma + conservação", sem acento, sem
  caixa, sem plural ("caixas", "congeladas", "pastéis") e com sinônimos
  ("crua", "frita", "geladeira", "freezer", "gramas"). Com mais de uma, ganha
  a que tem o nome da apresentação todo dito; se ainda sobrar mais de uma,
  pergunta. Nunca escolhe sozinho entre "unidade" e "caixa".
- **Fritura escolhe a porção crua que vence primeiro** (`lotes_para_fritar`,
  a sugestão do contrato) e a diz na confirmação; cru em duas conservações →
  pergunta. Uma fala frita de **um** lote: se pedirem mais que o livre da
  primeira porção, o núcleo recusa ("Só há N...").
- **Perda sem quantidade = a porção toda** ("descarta o vencido"). Mais de um
  lote com saldo → pergunta (lote, conservação, cru/frito ou `vencido`).
- **Cancelar venda sem número:** pelo cliente (todas as dele) ou, sem
  cliente, entre as de hoje; mais de uma → pergunta com as opções.
- **Dia falado da encomenda:** "sábado" é o próximo sábado, **hoje incluído**
  se hoje for sábado. A confirmação repete o dia ("para hoje", "para 22 de
  novembro"), então o engano aparece antes do "sim".
- **`ver_vendas` não devolve margem** (instrução: não opinar sobre margem);
  `margem_estimada` continua só na consulta do núcleo, para as telas.
- **Texto das decisões falado** (`agente.decisoes.falavel`): o agente troca
  "15/11" por "hoje"/"amanhã"/"em 15 de novembro", "R$ 100,00" por "100
  reais", "30 un" por "30 unidades" e omite "(lote sem lote)". Vale para
  todas as origens da caixa (resolve, na voz, a pendência do Plano 4); o
  texto original continua em `texto_decisao` de `ver_decisao` e na tela.
- **Resumo do dia:** assuntos novos na ordem encomendas atrasadas, encomendas
  de hoje, (contas vencidas), contas a receber vencidas, (validade), falta
  produzir, (estoque baixo, contas a vencer), sobra de frito, ... , encomendas
  dos próximos dias, vendas de hoje. Os três primeiros continuam sendo os
  falados.

## Núcleo (pedir à coordenação)

- **Geradores com datas, "R$" e "un"** (`decisoes/geradores.py`): o agente
  agora converte na fala, mas a tela continua mostrando "15/11" e "R$". Se os
  geradores passarem a escrever datas faladas, `falavel` vira no-op.
- **Lote frito "vence em 2 dias" na caixa:** um frito de ontem gera dois
  avisos (`lotes_vencendo` e `sobras_fritas`). Sugestão: `lotes_vencendo`
  ignorar lotes `forma="frito"` que já estão em `sobras_fritas`.
- `agente.consultas.estoque` (`consultar_estoque`) continua comparando o
  saldo bruto (pendência dos Planos 4 e 6). Para salgado, a voz tem agora
  `ver_estoque_para_venda` com o livre, o reservado e o vencido; mudar
  `consultar_estoque` fica para uma rodada com teste por voz.

## Para depois

- Desconto manual e preço por voz (Q10) — ver acima.
- Fritar de mais de um lote numa fala; entrega parcial e devolução parcial
  (Q3, "Fora deste plano").
- Escolher o lote na venda (Q12): hoje sempre FEFO, sem perguntar.
- Descarte de vencido aprovável pela caixa (o gerador `lotes_vencidos` propor
  `registrar_perda`): por voz, hoje, é `registrar_perda(vencido=True)`.
- Validar no Gemini Live que "duas", "doze" e "vinte e cinco" chegam como
  inteiros em `quantidade`, e que "às três da tarde" chega como "15:00" ou
  "15h" em `hora` (a ferramenta recusa outros formatos com mensagem).
- `ver_vendas` devolve no máximo as 20 últimas vendas do período (os totais
  são de todas); rever se o dono pedir a lista do mês.
