# Plano 4 — pendências e decisões da execução (fase 1, núcleo)

Branch `claude/onda3-nucleo-decisoes-8cbc69`. Suíte: 284 testes verdes; `makemigrations --check` sem mudanças.

## Decisões tomadas na execução

- App novo `decisoes` (não em `nucleo`, que não importa os apps de domínio, nem em `agente`, que é uma camada acima). O registro `decisoes.servicos.OPERACOES` é separado de `agente.propostas.OPERACOES` pelo mesmo motivo.
- `aprovar_decisao` chama o serviço da operação **dentro** do próprio `executar()`: a operação aninhada usa a chave da decisão e grava o seu próprio `RegistroOperacao` (autor = quem aprovou, canal = de onde aprovou). Se o serviço recusa, as duas desfazem e a trilha guarda `aprovar_decisao` com status "erro"; o "último erro" da decisão é lido da trilha (`parametros.decisao_id`), sem campo próprio.
- A pendência de aprovação "já aprovada" é verificada **antes** do `executar()`: repetir não cria um `aprovar_decisao` novo na trilha.
- Geradores devolvem `detalhes` com os dicts das consultas de origem (serializados em JSON), para a tela montar links sem consulta extra.
- `estoque.servicos.porcoes` calcula a validade da porção pela entrada mais antiga (mesma regra de `validade_porcao`), enquanto `agente.consultas.validades` usa o menor `validade` de qualquer movimento da porção. Na prática coincidem (saídas não levam validade).

## Fica para depois

| Item | Quando |
|---|---|
| Telas da caixa, "Hoje" com `resumo_do_dia` e histórico de operações | Fase 2a |
| Ferramentas MCP (`ver_resumo_do_dia`, `ver_decisoes`, `ver_historico`, `dar_ciencia`, `recusar_decisao`, `aprovar_decisao` nível 2) e `docs/agente-instrucoes-decisoes.md` | Fase 2b |
| `agente.consultas.estoque` compara o **saldo** com o mínimo (não desconta vencido, RN-03); `agente.consultas.validades` repete a conta de porções. Trocar por `estoque.servicos.disponivel` / `porcoes` | Fase 2b (sem mudar o formato da resposta) |
| Descarte de lote vencido (RF-EST-10, RN-19): sem serviço, o aviso de vencido fica até a ciência | Plano de estoque/inventário |
| Reservas no disponível (RN-03) e encomendas, vendas, sobras do dia (RF-FRI-03), necessidade de produção no resumo e na caixa | Plano 6 |
| Status do backup no resumo do dia (RF-ADM-06) | Depois da sessão de backup |
| Agendar `manage.py rotina_diaria` (cron/systemd) | Coordenação |
| Janelas (3/7 dias), critério da sugestão de ficha e validade das decisões configuráveis pela tela (RF-ADM-03) | Quando o dono pedir (hoje são constantes em `decisoes/consultas.py` e `decisoes/geradores.py`) |
| Operação de "ajustar ficha" aprovável pela caixa (hoje a sugestão só informa; o dono edita no admin, que versiona) | Se o dono quiser aprovar o ajuste com um toque |
| Compra lida de cupom como decisão (acrescentar a operação em `OPERACOES`) | Plano 5 |
| Erro dentro da parte pura de um gerador (antes de gravar) vai só para o relatório do comando, não para a trilha | Se aparecer na prática |
| O texto antigo de uma decisão pendente é substituído quando os números mudam (não houve decisão sobre ele) | — |
| A sugestão de ficha percorre as linhas das últimas 5 produções de cada produto (algumas consultas por produto) | Rever se houver dezenas de produtos |
