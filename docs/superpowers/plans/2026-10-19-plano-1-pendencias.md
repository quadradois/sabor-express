# Plano 1 — pendências e decisões tomadas durante a execução

Registro preservado do ledger de execução (o ledger temporário foi apagado). Commits: `bcd2946..33e4dd4` no branch `feat/plano-1-nucleo-ficha-viva`.

## Decisões tomadas pelo executor (revisáveis pelo dono)

| Decisão | Custo se estiver errada |
|---|---|
| `entrada_manual` valida na ordem: motivo → quantidade > 0 → item existe → validade. Todas as validações rodam dentro de `executar()`, então a recusa também fica auditada. | Só muda a ordem das mensagens. |
| Erros ficam gravados na trilha com `chave=None` e a chave citada no texto, sem nunca apagar nada. | A busca de erros por chave vira busca textual. |
| Campos decimais recusam "." com a mensagem "Use vírgula para decimais (ex.: 1,5).". Assim "1.500" nunca vira 1,5 sem aviso. | O dono precisa digitar "1500" em vez de "1.500". |
| A idempotência compara o nome da operação e os parâmetros. Uma chave repetida com dados diferentes é recusada ("Esta chave já foi usada para outra operação."). | Um reenvio legítimo com campo alterado precisa de uma chave nova, que o formulário já gera a cada abertura. |
| Blocos de preparação mostram as próprias etapas (modo de preparo), não só a "Montagem". | Remover um campo do bloco. |
| O RED da Task 6 não foi rodado separadamente; aceito porque os testes são os do plano e os números foram conferidos à mão. | Um guarda sem prova de falha. |
| O admin como formulário plano B dos cadastros (itens, conversões, fichas) fica **fora** de `executar()` no Plano 1. **Precisa passar por `executar()` antes do Plano 4 (agente)**, junto com o versionamento de fichas (RN-14). | Escritas de cadastro sem auditoria até lá. |

## Antes de entregar o sistema ao dono

- Uma edição inválida de ficha no admin descarta o que foi digitado: o admin volta à lista. Isso dói em fichas com muitas linhas.
- Deploy: definir `SABOR_DEBUG=0` e uma `SABOR_SECRET_KEY` real. O padrão de desenvolvimento é DEBUG ligado.

## Podem esperar (achados menores)

- **Configuração:** `ALLOWED_HOSTS` não remove espaços nem entradas vazias. Os testes dependem do `SABOR_DEBUG` do ambiente. A descrição em `pyproject.toml` é placeholder. O link "/admin/" é fixo.
- **CSS:** `min-height` de 44 px pega checkbox e radio. `table{display:block}` é prematuro. O link da marca não tem alvo de 44 px.
- **Operações:** o erro guarda só `str(e)`, sem o tipo. Uma `func` que retorna algo que não é dict é aceita. A gravação do erro usa `except: pass` sem logging. Chamadas sem `parametros` só comparam o nome.
- **Unidades:** uma `Conversao` igual à unidade base, ou "kg" num item em g, é ignorada (sombreada pelo padrão).
- **Fichas:**
  - Preparações e componentes duplicados são permitidos.
  - `rendimento_g` de produto não é forçado a ficar vazio.
  - A validação não revalida as fichas que referenciam a ficha salva.
  - Item inativo dentro de uma ficha não é checado na escala.
- **Escala:** uma consulta de saldo por item. Sub-preparação usada duas vezes gera dois blocos.
- **Exibição:** valores negativos perto de zero aparecem como "-0".
- **Testes:** `from conftest import` é frágil. Há imports não usados. Faltam testes de borda.
- **Unidade base:** `Item.unidade_base` só é protegida no admin e no `full_clean`. Um `.save()` direto ainda consegue trocá-la.
- **Migrations:** as novas colunas de `Movimento` e `parametros` foram preenchidas com valores padrão. Isso só importa se houver dados anteriores a elas, e hoje não há.
