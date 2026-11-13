# Plano 4, fase 2a — pendências das telas

Telas entregues: Hoje (`/`), Caixa de decisões (`/decisoes/`), Histórico de operações (`/historico/`). Sem mudança em modelo, serviço ou regra do núcleo.

## Para a coordenação / núcleo
- **Estoque baixo sem link próprio.** Não há tela de estoque por item; o bloco "O que falta" do Hoje só leva à entrada de estoque. Se virar tela (Plano futuro), ligar `item_id`.
- **Contas na caixa sem link por conta.** Não existe tela de uma conta/parcela; o link vai para "Contas a pagar". O mesmo vale para `conta_id` nos avisos de ajuste.
- **Resumo do dia não traz o nome do fornecedor/valor das compras a chegar.** `compras_em_aberto` é listada só por `compra_id` no Hoje; mostrar fornecedor exigiria o dict completo da consulta (conferir os campos) ou nova consulta.
- **Histórico sem filtro de texto livre nem de operação por voz/telefone.** Autor e canal são listas dos valores existentes na trilha; o limite do núcleo (`limite=None`) carrega tudo na memória antes de paginar. Se a trilha crescer muito, paginar na consulta.
- **Aprovar uma decisão cuja operação o núcleo recusa** mostra o erro e mantém pendente (por desenho); a tela não oferece "desistir" além de recusar com motivo.

## Das telas
- Sem atualização automática: o Hoje reflete o momento do carregamento; a rotina diária (`rotina_diaria`) precisa estar agendada para a caixa estar em dia.
- Situação do backup usa `settings.BACKUP_DIR` do processo web; se o serviço rodar com outro usuário/pasta, o alerta "não há backup" pode ser falso.
- Teste: `conftest.py` ganhou um fixture autouse que aponta `BACKUP_DIR` para uma pasta temporária (os testes não leem a pasta real de backups).
- Não há link "Caixa" no cabeçalho de todas as páginas; só no Hoje e nas telas novas.
