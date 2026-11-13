# Plano 9, fase 2a (telas) — o que foi feito, decisões e o que ficou de fora

Branch `claude/plano9-telas`. Só `web/` (views, templates, CSS, URLs), testes e este documento. Nenhuma mudança em `estoque/`, `vendas/`, `producao/`, `decisoes/`, `agente/` nem migração (`makemigrations --check` limpo).

## Telas novas ou alteradas

| Tela / URL | O que mudou |
|---|---|
| `/vender/` | Fluxo em dois passos por formulário (sem JavaScript): "Ver de onde pegar" mostra a separação (`separacao_venda`) por item (de qual lote, quantas un, vence, quanto sobra, avisos); "Confirmar e registrar venda" grava. Campo "Dia da venda" (padrão hoje). "Peguei de outro lote" por item (lotes disponíveis com nome falável, validade e saldo livre) reapresenta a separação com o aviso de lote deixado e grava com `itens[].lotes`. Depois de gravar, mostra os `avisos` do retorno. Aceita `?lote=&estado=&data_venda=` (vinda da conferência do vencido). |
| `/vendas/` | Cada linha mostra de qual lote saiu (nome falável + código) e o motivo do vencido, quando houve. Cancelamento reabre com o campo do motivo quando a devolução de lote vencido é recusada. |
| `/vendas/<id>/cancelar/` | Passa `motivo_vencido`; recusa por vencido volta para `/vendas/?cancelar=<id>` com o cancelamento aberto. |
| `/encomendas/<id>/` | Encomenda pronta mostra a separação da entrega (`separacao_encomenda`), "Peguei de outro lote" por item, "Dia da entrega" e motivo do vencido (reserva vencida). Grava com `entregar_encomenda(lotes=, data_entrega=, motivo_vencido=)` e mostra os avisos. |
| `/fritura/` | Lista também os lotes crus vencidos (marcados, "só com motivo") e tem o campo do motivo; o campo abre sozinho quando o núcleo pede. |
| `/lotes/<id>/` | Nome falável no título e na origem; link "Contar" por conservação; mudança de conservação ganha o motivo do vencido (aparece só quando o núcleo pede). |
| `/lotes/<id>/contar/` (nova, `contar_lote`) | "O sistema diz N, contei M": conservação, quanto há de fato, motivo. Grava com `ajustar_contagem` e mostra antes, depois e diferença (e aviso de reserva liberada). Aceita `?estado=&next=`. |
| `/decisoes/` | Decisão `lotes_vencidos`: "Já foram vendidas" (abre `/vender/` com lote e data preenchidos; para ingrediente, "Já foram usadas" leva à contagem), "Estão aqui: dar destino" (destino + quantidade + motivo, via `registrar_perda`) e "Não sei: contar". Rótulo próprio "Lote deixado para trás" para `lotes_deixados`. |
| `/` (Hoje) | Bloco "Venda primeiro" (`validade.deixados`); nome falável nos lotes vencidos e vencendo; destino (perda, descarte, consumo da equipe, doação) e "Contar" nos vencidos. |
| `/sobras/` e `/lotes/<id>/descartar/` | Campo "Destino" (perda, descarte, consumo da equipe, doação). |
| `/lotes/<id>/etiquetas/` | Dia da produção em número grande (`dia_producao`) e `nome_lote`; validade, produto, conservação, forma e quantidade mantidos. |
| `/historico/` | Mostra o `motivo_vencido` quando houver. |
| `/producao/<id>/` (fechamento) | Campo "Motivo do vencido" só aparece quando a conclusão foi recusada pedindo o motivo (`?motivo=1`). |
| `/consumos/` | Botão mostra o nome falável junto do código. |

## Decisões desta fase

- **Dois passos, e Enter nunca fecha a venda.** O primeiro botão do formulário é sempre "Ver de onde pegar" / "Atualizar a separação"; a venda só fecha com o botão "Confirmar e registrar venda".
- **Impressão digital da separação (`visto`).** Se o atendente mexe nos itens, lotes ou data depois de ver a separação e confirma direto, a tela mostra a separação de novo ("confira de novo e confirme") e não grava. O `POST` sem `acao`/`visto` (como os testes antigos e qualquer chamada direta) continua gravando como antes.
- **Venda atrasada vinda da conferência:** a data vem preenchida com o último dia de validade e o lote vem marcado como "tudo que for digitado saiu deste lote" (`todo_<apresentação>`); quem diz quanto foi vendido é o atendente. Nunca se preenche quantidade nem motivo sozinho.
- **Motivo do vencido** é um campo recolhido que abre sozinho quando a separação marca `precisa_motivo` ou o núcleo recusou pedindo o motivo; nunca vem preenchido. É um motivo por venda/entrega.
- **Botão de confirmar some quando falta estoque** (`completo` falso): o núcleo recusaria de qualquer forma; a tela diz o que fazer.
- **"Estão aqui"** reaproveita a URL `descartar` (que já chamava `registrar_perda`) com o campo `destino`. A mensagem de sucesso do descarte com destino "perda" continua "Descartado: ...".
- **Nome falável junto do código** onde a tela mostrava só o código: lote, fritura, sobras, produção concluída, Hoje, consumos, vendas. Um teste antigo (`test_fritura_registra_pelo_servico_e_mostra_o_custo`) trocou `"lote K1"` por `"código K1"` e `"lote do dia"`.
- Não foi preciso mexer no núcleo.

## O que ficou de fora ou limitado

- **Conciliação de consumo pendente (`/consumos/`) com lote vencido:** a consulta do núcleo (`consumos_pendentes().lotes_possiveis`) só oferece lotes válidos, então a tela não tem como escolher um vencido e não ganhou campo de motivo. O serviço aceita `motivo_vencido`; falta o núcleo oferecer o lote vencido como opção, se o dono quiser.
- **Ingrediente vencido na pesagem da produção:** a tela de pesagem não permite fixar lote (`registrar_peso(lote_id=)`), então o caso só existe por voz/API. A tela já mostra o campo do motivo no fechamento quando a recusa chega (`?motivo=1`).
- **"Venda primeiro" não tem botão que abra a venda já com o lote:** só lista e leva a `/vender/`.
- **Lotes disponíveis em "Peguei de outro lote"** mostram os da forma e conservação da apresentação, com saldo livre (mais o reservado da própria encomenda); não mostram lote feito depois do dia da venda.
- **Cancelamento de venda:** o campo do motivo fica recolhido dentro de "Cancelar venda" e abre sozinho depois da recusa.
- **Não conferido em navegador real:** só testes de tela (cliente de teste do Django); layout no celular não foi visto.
- Em `/historico/` o `motivo_vencido` aparece em destaque; perdas do relatório com `destino` (Task 14) não foram tocadas (é `custos/`, fora desta fase).

## Defeitos do núcleo anotados (não corrigidos)

- **Concordância:** "Faltam 1 un" (singular) no texto da separação e no aviso `falta` (`vendas/lotes.py`: `Faltam {n} un`).
- O resumo falado do agente ainda diz "Vencido não pode ser usado." (já anotado na fase 1; é da fase 2b).
- `consumos_pendentes().lotes_possiveis` exclui vencido (ver acima).
- `vendas.consultas.vendas()` não devolve os lotes de cada linha (a tela os lê de `LinhaVenda.baixas`); seria melhor a consulta trazer `lotes`.
