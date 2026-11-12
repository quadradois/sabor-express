# Plano 2 — pendências e decisões da execução

Branch `feat/plano-2-producao-guiada`. Suíte: 139 testes verdes; `makemigrations --check` sem mudanças.

## Decisões tomadas na execução

- Os cadastros do admin (Item, Ficha, Critério de validade) agora gravam dentro de `executar()` (`nucleo/admin_executar.py`), cumprindo a pendência do Plano 1.
- A tela de produção concluída linka para o lote e para as etiquetas do estado inicial (estado do movimento `entrada_producao`).
- "Saiu certo" registra a impressão por POST; abrir ou imprimir a tela de etiquetas (GET) nunca grava nada.
- Número de cópias padrão = saldo do estado; valor inválido vira 1 cópia.

## Fica para depois

| Item | Quando |
|---|---|
| Consumo pendente e conciliação | Plano 3 |
| Plano de produção e status "planejada" | Planos 4/6 |
| Troca de lote pela conversa | Plano 4 |
| Proposta de ajuste de ficha pelo rendimento (os dados previsto × usado já ficam gravados) | Plano 4 |
| Embalagens de produção no custo (quando a ficha tiver embalagens) | Quando a ficha tiver embalagens |
| Modelos de etiqueta e impressora térmica | PR-03 |
| Data-base da validade | REG-02 |
| Fritura de lotes crus já guardados e troca de óleo | Plano 6 |
