# Plano 2 — Produção guiada — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O dono escolhe "Coxinha de frango 150 g × 50, fritas", começa o preparo e é conduzido etapa por etapa (mise en place com pesagem ou "usei o previsto", etapas com cronômetros), conclui com um único lote do produto final com custo real e validade, congela parte dele e imprime as etiquetas internas.

**Architecture:** Um app novo, `producao`, guarda a produção em andamento como estado do servidor (`Producao`, linhas do mise en place, cronômetros). Toda escrita (iniciar, pesar, mudar de etapa, cronômetros, concluir, cancelar, transferir estado, registrar etiqueta, criar tamanho, salvar ficha/item no admin) passa por `nucleo.operacoes.executar()`. Os números vêm de `fichas.escala.escalar()` e de funções puras de estoque (FEFO, saldo por lote e estado, validade). As telas são templates Django com um único arquivo JS para cronômetros, alarme e tela acesa.

**Tech Stack:** Python 3.12, uv, Django 5.2, SQLite, pytest + pytest-django. JS sem biblioteca (Web Audio, Screen Wake Lock).

**Spec:** `docs/superpowers/specs/2026-10-19-agente-cozinha-design.md` (§6.2, §6.3 itens 5–9, §6.4, §10). Regras em `docs/prd/02-prd.md`: RF-OP-02/04/05/06/08/09, RF-EST-03/05/10/12, RF-ETQ-01/02/03/05/06/07, RF-CUS-01, RN-08, RN-14/15/16/17/18/19, RN-27/28, RN-39; decisões DEC-F2-004, 014, 015, 017, 023, 032, 047. Pendências do Plano 1: `docs/superpowers/plans/2026-10-19-plano-1-pendencias.md`.

## Decisões deste plano (revisáveis pelo dono)

| Decisão | Por quê / custo se estiver errada |
|---|---|
| **Produto por tamanho = `Item` do tipo `produto`** (unidade `un`), apontando para a ficha de produto e com `peso_g`. "Coxinha de frango 150 g" e "Coxinha de frango 25 g" são dois itens com a mesma ficha. | Lote e Movimento continuam iguais; estoque, preço e encomenda (Plano 6) já têm onde se pendurar. |
| Produção tem três estados: **andamento → concluída / cancelada**. Não há "planejada" neste plano. | O plano de produção vem com encomendas (Planos 4 e 6). Iniciar já fixa a versão (RN-15), então DEC-F2-015 vale trivialmente. |
| **Versão da ficha = foto (JSON) da ficha a cada salvamento que muda algo**. A produção guarda a versão e copia as linhas e etapas no início. | Imutável por construção, sem tabelas duplicadas. Editar a ficha no meio do preparo não muda nada da produção. |
| **Estado de conservação** (`fresco`, `resfriado`, `congelado`) fica no `Movimento`; a **forma** (`cru`, `frito`) fica no `Lote`. Ingredientes usam estado vazio. | Saldo por lote × estado (RF-EST-03) sem tabela nova. Pré-frito congelado = lote frito no estado congelado. |
| Validade pelo **critério cadastrado** (produto, forma, estado, dias), contando **da data da operação** (conclusão ou transferência). Sem critério: validade manual com justificativa, marcada "informada manualmente". | Data-base definitiva depende de REG-02; trocar depois é mudar uma função. |
| **Óleo por referência em R$ por unidade, no próprio tamanho** (`Item.oleo_ref_un`). Unidades fritas = boas + perdas. Nenhum movimento de óleo aqui (a troca de óleo é do Plano 6). | Um salgado de 25 g gasta menos óleo que um de 150 g; sem tabela de parâmetros. |
| **Sem consumo pendente neste plano.** Iniciar recusa se falta estoque; concluir recusa se o pesado passa do saldo, e a produção continua em andamento até o dono dar entrada. | A conciliação depende do recebimento (Plano 3). Nada se perde: o estado está no servidor. |
| Troca de lote só pelo núcleo (`registrar_peso(..., lote_id=...)`), sem escolha na tela. | Design §6.4: sem escolha de lote na tela; o agente (Plano 4) usa o parâmetro pela conversa. |
| Um único modelo de etiqueta, impresso pelo navegador (arquivo imprimível). A impressão só é registrada quando o dono confirma que saiu. | PR-03 (impressora) aberta; RF-ETQ-04 (modelos configuráveis) fica para quando houver impressora. |
| **Cadastros pelo admin passam a gravar dentro de `executar()`** (Item, Ficha, Critério de validade), cumprindo a pendência do Plano 1 antes do Plano 4. | O admin continua sendo o plano B dos cadastros, agora auditado. |

## Global Constraints

- Tudo do Plano 1 continua valendo: Decimal sempre; quantidade com 3 casas e custo unitário com 4 casas; arredondamento `ROUND_HALF_UP`; unidade base `g`, `mL` ou `un`; telas com login; pt-BR com vírgula decimal (`DecimalBR` recusa ponto).
- **Toda gravação de domínio passa por `executar()`** (inclusive o admin, a partir da Task 3). Saldo nunca é editado (RN-01). Movimentos e versões nunca são apagados nem editados (RN-34).
- Conclusão atômica e única: consumos, lote e custo numa só operação; repetir não gera movimento (RN-08, RF-OP-04).
- Uma produção gera no máximo um lote (zero só na perda total confirmada) (RN-16, DEC-F2-017).
- FEFO: menor validade primeiro; sem validade ou empate, entrada mais antiga; vencido nunca é consumido (RN-18, RN-19, DEC-F2-032).
- Custo total da produção com 2 casas; custo unitário = custo total ÷ quantidade boa, 4 casas.
- Nenhum prazo de validade padrão: sem critério, validade manual com justificativa (RN-27).
- Etiquetas são internas e trazem "USO INTERNO" (RF-ETQ-06).
- Tela de cozinha: botões de no mínimo 44 px, uma tarefa por tela, tela acesa durante o preparo, sem rolagem horizontal a 360 px.
- Nenhuma conta de quantidade, custo ou validade por IA (design A3).

## Review Focus

- O dono pesou mais do que o estoque registrado tem → a conclusão é recusada com o nome do item e quanto falta; a produção continua em andamento com tudo o que foi pesado (teste na Task 7).
- O lote de validade mais próxima está vencido → ele é pulado e o próximo é consumido; nunca se consome lote vencido (teste na Task 1).
- Toque duplo em "Concluir" ou reenvio do formulário → um único lote; uma segunda conclusão com outra chave é recusada (teste na Task 7).
- A ficha é editada no admin com uma produção em andamento → as linhas, as etapas e a versão da produção não mudam (teste na Task 5).
- A página do preparo é recarregada ou aberta em outro aparelho → mesma etapa, mesmos pesos e cronômetros com o mesmo horário de término (teste na Task 10).

---

### Task 1: Estoque por lote e estado, FEFO

**Files:**
- Modify: `estoque/models.py`, `estoque/servicos.py`
- Create: migração `estoque/migrations/0003_...` (via `makemigrations`)
- Test: `tests/test_fefo.py`

**Interfaces:**
- Consumes: `Lote`, `Movimento`, `saldo(item)` (Plano 1).
- Produces:
  - Constantes em `estoque/models.py`: `ESTADOS = [("fresco", "Fresco"), ("resfriado", "Resfriado"), ("congelado", "Congelado")]`, `FORMAS = [("cru", "Cru"), ("frito", "Frito")]`.
  - Campos novos: `Lote.forma = CharField(max_length=10, choices=FORMAS, blank=True, default="")`; `Movimento.estado = CharField(max_length=20, choices=ESTADOS, blank=True, default="")`; `Movimento.validade = DateField(null=True, blank=True)`; `Movimento.validade_manual = BooleanField(default=False)`.
  - `saldo_lote(lote, estado: str = "") -> Decimal` — soma dos movimentos do lote naquele estado.
  - `validade_porcao(lote, estado: str = "") -> date | None` — menor `Movimento.validade` entre as entradas (quantidade > 0) do lote naquele estado; se nenhuma entrada tiver validade, `lote.validade`.
  - `alocar_fefo(item, quantidade: Decimal, *, hoje: date) -> list[tuple[Lote, Decimal]]` — distribui `quantidade` (unidade base) pelos lotes do item com saldo > 0 no estado `""`, pulando os de validade < `hoje`, na ordem `validade` (nulos por último), `criado_em`, `id`. Levanta `RegraViolada(f"Falta {q} de '{item.nome}' no estoque.")` (q formatado com `web.templatetags.formato.quantidade`, ex.: "500 g", "1 kg"; as outras mensagens com quantidade usam a mesma função) se o saldo utilizável não cobre.

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_fefo.py — datas relativas a hoje = timezone.localdate()
def test_fefo_menor_validade_primeiro():        # A vence hoje+5, B hoje+2 → B antes de A
    assert alocar_fefo(frango, D("700"), hoje=hoje) == [(lote_b, D("500")), (lote_a, D("200"))]
def test_fefo_sem_validade_entrada_mais_antiga(): # dois lotes de sal sem validade → o criado primeiro
def test_fefo_pula_lote_vencido():              # C vence hoje-1 com 1000 g; A tem 500 g
    assert alocar_fefo(frango, D("300"), hoje=hoje) == [(lote_a, D("300"))]
def test_fefo_falta_conta_so_lotes_validos():   # C vencido não cobre: RegraViolada "Falta 500 g de 'Frango' no estoque."
def test_saldo_lote_por_estado():               # +10 resfriado, -4 resfriado, +4 congelado → 6 e 4
```
Os lotes são criados com `entrada_manual` (Plano 1); os movimentos de estado são criados direto no teste.

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/test_fefo.py -v` → FAIL (ImportError `alocar_fefo`).
- [ ] **Step 3: Campos, migração e funções** — `uv run python manage.py makemigrations estoque`; implementar as três funções em `estoque/servicos.py`. `entrada_manual` grava `Movimento.validade = validade`.
- [ ] **Step 4: Rodar tudo** — `uv run pytest -v` → PASS (os 72 do Plano 1 + os novos).
- [ ] **Step 5: Commit** — `git add estoque tests/test_fefo.py && git commit -m "feat: saldo por lote e estado e alocação FEFO"`

---

### Task 2: Produto por tamanho

**Files:**
- Modify: `cadastros/models.py`, `cadastros/admin.py`, `web/forms.py` (`EntradaForm` sem produtos), `conftest.py`
- Create: `cadastros/servicos.py`, migração `cadastros/migrations/0003_...`
- Test: `tests/test_tamanhos.py`

**Interfaces:**
- Consumes: `Ficha` (Plano 1), `executar`, `RegraViolada`.
- Produces:
  - `Item.TIPOS` ganha `("produto", "Produto")`. Campos: `ficha = ForeignKey("fichas.Ficha", null=True, blank=True, on_delete=PROTECT, limit_choices_to={"tipo": "produto"})`, `peso_g = DecimalField(14, 3, null=True, blank=True)`, `oleo_ref_un = DecimalField(14, 4, null=True, blank=True)` (R$ por unidade frita).
  - `Item.clean()`: tipo `produto` exige `ficha` de tipo produto, `peso_g > 0` e `unidade_base == "un"` (mensagens: "Produto precisa de uma ficha de produto.", "Informe o peso de cada unidade (g).", "Produto é controlado em unidades (un)."); outro tipo exige `ficha` vazia e `peso_g` vazio.
  - `criar_tamanho(*, ficha_id: int, peso_g: Decimal, oleo_ref_un: Decimal | None = None, autor: str, canal: str = "web", chave: str | None = None) -> dict` em `cadastros/servicos.py`, via `executar("criar_tamanho", ...)`. Cria `Item(nome=f"{ficha.nome} {peso} g", tipo="produto", unidade_base="un", controla_validade=True, ficha, peso_g)`, com o peso formatado por `quantidade(peso_g, "un")` sem o " un" (ex.: "12,5"). Recusa `peso_g <= 0` ("O peso de cada unidade deve ser maior que zero."), ficha que não é produto e tamanho repetido para a mesma ficha (`f"Esse tamanho já existe: {nome}."`). Retorna `{"item_id": id, "nome": nome}`.
  - Fixture `bolinha` em `conftest.py`: item "Farinha de trigo" (g), preparação "Massa simples" (rendimento 1000 g, 1000 g de farinha, etapa "Sove a massa" com `tempo_seg=300`), ficha produto "Bolinha" (100% massa, etapa "Modele as bolinhas"), e o tamanho "Bolinha 100 g" (`peso_g=100`, `oleo_ref_un=0,05`). Retorna o `Item` do tamanho.

- [ ] **Step 1: Testes que falham**

```python
def test_criar_tamanho_cria_item_produto(coxinha):
    r = criar_tamanho(ficha_id=coxinha.id, peso_g=D("25"), autor="dono")
    i = Item.objects.get(id=r["item_id"])
    assert (i.nome, i.tipo, i.unidade_base, i.ficha, i.peso_g) == ("Coxinha de frango 25 g", "produto", "un", coxinha, D("25"))
def test_tamanho_repetido_recusado(coxinha):    # segundo criar_tamanho 25 g → "Esse tamanho já existe: Coxinha de frango 25 g."
def test_peso_decimal_no_nome(coxinha):         # 12.5 → "Coxinha de frango 12,5 g"
def test_tamanho_peso_zero_recusado(coxinha):
def test_produto_sem_ficha_invalido():          # Item(tipo="produto", unidade_base="un").full_clean() → ValidationError
def test_entrada_manual_nao_lista_produto(client, dono, bolinha):  # o <select> de /estoque/entrada/ não contém "Bolinha 100 g"
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/test_tamanhos.py -v` → FAIL.
- [ ] **Step 3: Implementar** campos, `clean`, migração, `criar_tamanho`, fixture; `EntradaForm.item` filtra `ativo=True` e exclui `tipo="produto"`; `ItemAdmin.list_display` ganha `ficha` e `peso_g`.
- [ ] **Step 4: Rodar tudo** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: produto por tamanho compartilhando a ficha"`

---

### Task 3: Versões de ficha (RN-14) e admin pelo núcleo

**Files:**
- Modify: `fichas/models.py`, `fichas/admin.py`, `cadastros/admin.py`
- Create: `fichas/versoes.py`, `nucleo/admin_executar.py`, migração `fichas/migrations/0003_...`
- Test: `tests/test_versoes.py`

**Interfaces:**
- Consumes: `executar`, `validar_ficha`, `SomenteLeitura` (`estoque/admin.py`).
- Produces:
  - `FichaVersao(ficha FK PROTECT related_name="versoes", numero PositiveIntegerField, conteudo JSONField, operacao FK RegistroOperacao null PROTECT, criado_em auto_now_add)`, `UniqueConstraint(ficha, numero)`, `ordering=["numero"]`. Registrada no admin com `SomenteLeitura`.
  - `foto(ficha) -> dict` — `{"tipo", "rendimento_g", "itens": [[item_id, nome, qtd]], "subpreparacoes": [[ficha_id, nome, qtd_g]], "proporcoes": [[ficha_id, nome, pct]], "etapas": [[instrucao, tempo_seg, ponto]]}` na ordem (`ordem`, `id`); Decimals como str.
  - `salvar_versao(ficha, op=None) -> FichaVersao` — cria `numero = última + 1` só se `foto(ficha)` difere da última; senão devolve a última.
  - `versao_vigente(ficha) -> FichaVersao` — a última; se não houver, cria a 1 (fichas anteriores a este plano).
  - `class AdminViaExecutar` (mixin de `ModelAdmin`) em `nucleo/admin_executar.py`: `save_model` não grava; `save_related` chama `executar(f"salvar_{opts.model_name}", func, autor=request.user.username, canal="web", parametros={"id": obj.pk})`, onde `func` faz `obj.save()`, `super().save_related(...)` e `self.depois_de_salvar(obj, op)` (gancho, padrão nada) e devolve `{"id": obj.pk}`. `delete_model` faz `obj.delete()` dentro de `executar(f"excluir_{model_name}", ...)`.
  - `FichaAdmin(AdminViaExecutar, ...)`: `depois_de_salvar` = `validar_ficha(obj)` + `salvar_versao(obj, op)`; mantém o tratamento `_FichaInvalida` existente. Inline somente leitura das versões (número e data). `ItemAdmin` também herda o mixin.

- [ ] **Step 1: Testes que falham**

```python
def test_salvar_versao_so_quando_muda(coxinha):
    v1 = salvar_versao(coxinha); assert salvar_versao(coxinha) == v1
    Etapa.objects.create(ficha=coxinha, ordem=2, instrucao="Empane")
    assert salvar_versao(coxinha).numero == 2
def test_versao_antiga_nao_muda(coxinha):     # v1.conteudo igual antes e depois da edição
def test_admin_salva_ficha_pelo_nucleo(client, admin_user, coxinha):
    # POST no change form do admin (client.force_login(admin_user)) mudando o nome
    # → RegistroOperacao nome="salvar_ficha" status="sucesso" e FichaVersao nova
def test_admin_ficha_invalida_nao_cria_versao(client, admin_user, coxinha):  # proporções somando 90 → nenhuma FichaVersao, ficha intacta
def test_admin_salva_item_pelo_nucleo(client, admin_user):  # add de Item → RegistroOperacao "salvar_item"
```
Para os POSTs do admin, montar os dados do formulário com os prefixos de inline (`itens-TOTAL_FORMS` etc.) a partir de um GET do change form; um helper `dados_admin(client, url)` no próprio arquivo de teste lê o formulário do GET com `html.parser` e devolve o dict.

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/test_versoes.py -v` → FAIL.
- [ ] **Step 3: Implementar** modelo, migração, `fichas/versoes.py`, mixin e admins.
- [ ] **Step 4: Rodar tudo** — `uv run pytest -v` → PASS (inclusive `tests/test_fichas_admin.py` do Plano 1).
- [ ] **Step 5: Commit** — `git commit -m "feat: versões de ficha e cadastros do admin pelo núcleo"`

---

### Task 4: Validade e transferência de estado

**Files:**
- Modify: `estoque/models.py`, `estoque/servicos.py`, `estoque/admin.py`
- Create: migração `estoque/migrations/0004_...`
- Test: `tests/test_conservacao.py`

**Interfaces:**
- Consumes: `ESTADOS`, `FORMAS`, `saldo_lote`, `validade_porcao` (Task 1); `AdminViaExecutar` (Task 3).
- Produces:
  - `CriterioValidade(produto FK Item limit tipo=produto, forma choices FORMAS, estado choices ESTADOS, dias PositiveIntegerField, fonte CharField(200, blank))`, único por (produto, forma, estado). Admin com `AdminViaExecutar`.
  - `calcular_validade(produto, forma: str, estado: str, *, hoje: date, manual: date | None, justificativa: str) -> tuple[date, bool]` — com critério: `(hoje + dias, False)`, ignorando `manual`; sem critério: exige `manual` (`f"Sem critério de validade para '{produto.nome}' {forma} {estado}: informe a validade."`) e `justificativa` não vazia ("Justifique a validade informada.") → `(manual, True)`.
  - `transferir_estado(*, lote_id: int, quantidade: Decimal, de: str, para: str, validade_manual: date | None = None, justificativa: str = "", autor: str, canal: str = "web", chave: str | None = None) -> dict` via `executar("transferir_estado", ...)`. Recusa: `quantidade <= 0`; `de == para`; estado inválido; porção vencida (`validade_porcao(lote, de) < hoje`: "Lote vencido só aceita descarte."); `quantidade > saldo_lote(lote, de)` (`f"Só há {q} em {de}."`). Grava dois movimentos `tipo="transferencia_estado"`: `-quantidade` em `de` e `+quantidade` em `para` com a validade calculada; fator 1, unidade `un`, motivo `f"{de} → {para}"`. Retorna `{"lote_id", "validade": iso, "validade_manual": bool}`.

- [ ] **Step 1: Testes que falham**

```python
def test_transferir_parcial_mantem_lote():      # lote com 250 resfriado; 200 → congelado
    assert (saldo_lote(l, "resfriado"), saldo_lote(l, "congelado")) == (D("50"), D("200"))
    assert validade_porcao(l, "congelado") == hoje + timedelta(days=60)   # critério congelado = 60 dias
def test_transferir_mais_que_a_porcao_recusa():  # 300 de 250 → "Só há 250 un em resfriado."
def test_sem_criterio_exige_validade_e_justificativa():
def test_validade_manual_fica_marcada():         # Movimento de entrada com validade_manual=True
def test_porcao_vencida_nao_transfere():
```
O lote de produto do teste é criado direto (Lote + Movimento `entrada_producao` estado resfriado), sem depender da Task 7.

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/test_conservacao.py -v` → FAIL.
- [ ] **Step 3: Implementar** modelo, migração, `calcular_validade`, `transferir_estado`.
- [ ] **Step 4: Rodar tudo** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: critério de validade e transferência de estado"`

---

### Task 5: Iniciar produção (estado do servidor)

**Files:**
- Create: app `producao` (`producao/__init__.py`, `apps.py`, `models.py`, `servicos.py`, `admin.py`, `migrations/`)
- Modify: `sabor/settings.py` (registrar `producao`)
- Test: `tests/test_producao_inicio.py`

**Interfaces:**
- Consumes: `escalar()` (Plano 1), `versao_vigente` (Task 3), `Item` produto (Task 2), `FORMAS`.
- Produces:
  - `Producao`: `produto FK Item PROTECT`, `versao FK FichaVersao PROTECT`, `unidades PositiveIntegerField`, `peso_g Decimal(14,3)`, `forma choices FORMAS`, `status` (`"andamento" | "concluida" | "cancelada"`, padrão andamento), `etapa_atual PositiveIntegerField default 0`, `etapas JSONField` (lista de `{"bloco", "instrucao", "tempo_seg", "ponto", "midia"}`), `quantidade_boa`, `perdas` (PositiveInteger null), `perda_motivo`, `anotacao` (texto livre: "como foi?" e sobras), `motivo_cancelamento`, `lote OneToOne Lote null PROTECT`, `custo_total Decimal(14,2) null`, `custo_unitario Decimal(14,4) null`, `iniciada_em auto_now_add`, `encerrada_em null`. Propriedade `fechamento = len(etapas) + 1` (índice da tela de fechamento; 0 é o mise en place).
  - `LinhaPreparo`: `producao FK related_name="linhas"`, `bloco CharField`, `item FK Item PROTECT`, `previsto Decimal(14,3)`, `usado Decimal(14,3) null`, `lote FK Lote null` (troca de lote), `ordem`.
  - `iniciar_producao(*, produto_id: int, unidades: int, forma: str, autor: str, canal: str = "web", chave: str | None = None) -> dict` via `executar("iniciar_producao", ...)`: `escalar(produto.ficha, unidades, produto.peso_g)`; recusa se alguma linha tem `falta > 0` (`f"Falta {q} de '{nome}'. Dê entrada no estoque antes de começar."`, a primeira encontrada), produto inativo ou forma inválida; `forma == "frito"` exige `produto.oleo_ref_un` (`f"Cadastre a referência de óleo de '{nome}'."`). Cria uma `LinhaPreparo` por linha de cada bloco (na ordem dos blocos) e copia as etapas dos blocos; se frito, acrescenta a etapa `{"bloco": "Fritura", "instrucao": f"Frite as {unidades} unidades.", "tempo_seg": None, "ponto": "", "midia": ""}`. Retorna `{"producao_id": id}`.

- [ ] **Step 1: Testes que falham**

```python
def test_iniciar_copia_linhas_e_etapas(bolinha, farinha_em_estoque):
    p = Producao.objects.get(id=iniciar_producao(produto_id=bolinha.id, unidades=10, forma="cru", autor="dono")["producao_id"])
    assert [(l.bloco, l.item.nome, l.previsto, l.usado) for l in p.linhas.all()] == [("Massa simples", "Farinha de trigo", D("1000"), None)]
    assert [e["instrucao"] for e in p.etapas] == ["Sove a massa", "Modele as bolinhas"]
    assert (p.status, p.etapa_atual, p.versao.numero) == ("andamento", 0, 1)
def test_frito_acrescenta_fritura_por_ultimo(bolinha, farinha_em_estoque):  # última etapa "Frite as 10 unidades."
def test_iniciar_com_falta_recusa(bolinha):    # sem estoque → "Falta 1 kg de 'Farinha de trigo'. Dê entrada no estoque antes de começar."
def test_frito_sem_referencia_de_oleo_recusa(bolinha, farinha_em_estoque):
def test_editar_ficha_nao_muda_producao_em_andamento(bolinha, farinha_em_estoque):
    # depois de iniciar: muda a quantidade da farinha na massa, cria etapa nova e salvar_versao()
    # → linhas, etapas e versao.numero da produção iguais aos de antes
```
`farinha_em_estoque` (fixture local): `entrada_manual` de 2 kg de farinha, custo R$ 10,00.

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/test_producao_inicio.py -v` → FAIL.
- [ ] **Step 3: Implementar** app, modelos, migração, `iniciar_producao`; admin de `Producao` com `SomenteLeitura`.
- [ ] **Step 4: Rodar tudo** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: iniciar produção com linhas e etapas fixadas"`

---

### Task 6: Mise en place, etapas, cronômetros e cancelamento

**Files:**
- Modify: `producao/models.py`, `producao/servicos.py`
- Test: `tests/test_producao_preparo.py`

**Interfaces:**
- Consumes: `Producao`, `LinhaPreparo` (Task 5).
- Produces (todas via `executar`, todas recusam produção que não está em andamento com "Esta produção já foi encerrada."; todas levam `autor`, `canal="web"`, `chave=None`):
  - `registrar_peso(*, linha_id: int, usado: Decimal | None, lote_id: int | None = None, ...) -> dict` — `usado=None` = "usei o previsto" (`usado = previsto`); `usado < 0` recusado ("O peso não pode ser negativo."); zero é aceito. `lote_id` fixa um lote do mesmo item (outro item: "Esse lote não é de '{nome}'.").
  - `usar_previsto_restantes(*, producao_id: int, ...) -> dict` — `usado = previsto` nas linhas com `usado` nulo; retorna `{"linhas": n}`.
  - `ir_para_etapa(*, producao_id: int, indice: int, ...) -> dict` — `0 <= indice <= fechamento` (senão "Etapa inexistente."); sair do mise en place (indice > 0) exige todas as linhas com `usado` (`f"Pese ou marque 'usei o previsto' em: {nomes}."`, nomes separados por ", ").
  - `Cronometro(producao FK related_name="cronometros", nome CharField(120), fim DateTimeField, parado_em DateTimeField null)`.
  - `iniciar_cronometro(*, producao_id: int, nome: str, segundos: int, ...) -> dict` — `segundos > 0`; `fim = timezone.now() + segundos`; retorna `{"cronometro_id", "fim": iso}`.
  - `parar_cronometro(*, cronometro_id: int, ...) -> dict` — grava `parado_em`; parar de novo é inofensivo.
  - `cancelar_producao(*, producao_id: int, motivo: str, ...) -> dict` — motivo obrigatório ("Informe o motivo do cancelamento."); `status="cancelada"`, `encerrada_em`; nenhum movimento de estoque (RF-OP-08).

- [ ] **Step 1: Testes que falham**

```python
def test_usei_o_previsto(producao):            # registrar_peso(usado=None) → usado == previsto
def test_peso_negativo_recusado(producao):
def test_nao_sai_do_mise_en_place_sem_pesar(producao):  # "Pese ou marque 'usei o previsto' em: Farinha de trigo."
def test_avanca_e_volta(producao):             # previsto restantes; ir_para_etapa 1, 2, 1; 99 → "Etapa inexistente."
def test_cronometros_simultaneos_sobrevivem_a_troca_de_etapa(producao):
    # dois cronômetros, ir_para_etapa → ambos continuam sem parado_em e com o mesmo fim
def test_cancelar_nao_mexe_no_estoque(producao):  # saldo da farinha igual; depois registrar_peso → "Esta produção já foi encerrada."
```
Fixture `producao` local: `bolinha` + farinha em estoque + `iniciar_producao(10, "cru")`.

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/test_producao_preparo.py -v` → FAIL.
- [ ] **Step 3: Implementar** modelo `Cronometro`, migração e as seis operações.
- [ ] **Step 4: Rodar tudo** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: mise en place, etapas, cronômetros e cancelamento"`

---

### Task 7: Concluir produção: um lote, custo real, rastreio

**Files:**
- Modify: `producao/servicos.py`
- Test: `tests/test_producao_conclusao.py`

**Interfaces:**
- Consumes: `alocar_fefo`, `calcular_validade` (Tasks 1 e 4), `Producao`, `LinhaPreparo`.
- Produces:
  - `concluir_producao(*, producao_id: int, quantidade_boa: int, perdas: int = 0, perda_motivo: str = "", estado: str, validade_manual: date | None = None, justificativa: str = "", anotacao: str = "", confirmar_perda_total: bool = False, autor: str, canal: str = "web", chave: str | None = None) -> dict` via `executar("concluir_producao", ...)`. Regras, nesta ordem:
    1. Produção em andamento ("Esta produção já foi encerrada."); todas as linhas pesadas (mesma mensagem da Task 6).
    2. `quantidade_boa >= 0`, `perdas >= 0`; `perdas > 0` exige motivo ("Informe o motivo das perdas."); `estado` precisa estar em `ESTADOS` ("Escolha a conservação."); `quantidade_boa == 0` exige `confirmar_perda_total` ("Nenhuma unidade boa: confirme a perda total.").
    3. Consumo por item = soma de `usado` das linhas do item (linhas com `lote` fixado consomem desse lote e precisam de saldo nele; o restante vai por `alocar_fefo`). Um movimento `tipo="consumo_producao"` por (lote, quantidade), negativo, motivo `f"Produção {id}"`.
    4. `custo_total = Σ(q × lote.custo_unitario)` + (se frito) `produto.oleo_ref_un × (quantidade_boa + perdas)`, quantizado a 0,01.
    5. Se `quantidade_boa > 0`: validade por `calcular_validade(produto, forma, estado, hoje=localdate(), ...)`; cria `Lote(item=produto, codigo=f"{hoje:%y%m%d}-{id}", forma, validade, custo_unitario = custo_total / quantidade_boa a 4 casas)` e um movimento `tipo="entrada_producao"`, `+quantidade_boa`, estado, validade, `validade_manual`.
    6. Grava na produção `status="concluida"`, números, `lote`, custos, `encerrada_em`.
    Retorna `{"lote_id": id | None, "custo_total", "custo_unitario"}`.
  - `origem(lote) -> list[tuple[Lote, Decimal]]` em `producao/servicos.py` — lotes consumidos pela operação que criou o lote (movimentos negativos com a mesma `operacao` da entrada do lote), com a quantidade (RF-EST-12, RN-17).

- [ ] **Step 1: Testes que falham**

```python
# Farinha: lote A 600 g por R$ 3,00 (vence hoje+1) e lote B 1000 g por R$ 8,00 (vence hoje+6).
# Bolinha 100 g × 10, critério resfriado cru = 3 dias. Todas as linhas "usei o previsto" (1000 g).
def test_conclui_cru_custo_fefo(producao_pesada):
    r = concluir_producao(producao_id=p.id, quantidade_boa=9, perdas=1, perda_motivo="rasgou", estado="resfriado", autor="dono")
    assert (D(r["custo_total"]), D(r["custo_unitario"])) == (D("6.20"), D("0.6889"))   # 600×0,005 + 400×0,008
    assert (saldo_lote(lote_a), saldo_lote(lote_b)) == (D("0"), D("600"))
    lote = Lote.objects.get(id=r["lote_id"])
    assert (saldo_lote(lote, "resfriado"), lote.validade, lote.forma) == (D("9"), hoje + timedelta(days=3), "cru")
    assert origem(lote) == [(lote_a, D("600")), (lote_b, D("400"))]
def test_conclui_frito_soma_oleo_de_referencia(producao_frita_pesada):  # 6,20 + 0,05 × 10 = 6,70; unitário 0,7444; lote.forma "frito"
def test_pesou_mais_que_o_estoque_recusa_e_continua(producao_pesada):
    # registrar_peso 1700 g → "Falta 100 g de 'Farinha de trigo' no estoque."; status "andamento"; nenhum movimento novo; usado continua 1700
def test_dupla_conclusao_um_lote(producao_pesada):
    # mesma chave duas vezes → mesmo resultado, 1 lote; outra chave → "Esta produção já foi encerrada."
def test_perda_total_exige_confirmacao_e_nao_cria_lote(producao_pesada):
def test_perdas_sem_motivo_recusa(producao_pesada):
def test_lote_fixado_no_peso_e_respeitado(producao):  # registrar_peso(lote_id=lote_b) → consome só de B
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/test_producao_conclusao.py -v` → FAIL.
- [ ] **Step 3: Implementar** `concluir_producao` e `origem`.
- [ ] **Step 4: Rodar tudo** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: concluir produção com lote único, custo real e rastreio"`

---

### Task 8: Etiquetas internas

**Files:**
- Create: `estoque/etiquetas.py`
- Modify: `estoque/models.py`, `estoque/admin.py`
- Create: migração `estoque/migrations/0005_...`
- Test: `tests/test_etiquetas.py`

**Interfaces:**
- Consumes: `saldo_lote`, `validade_porcao`, `ESTADOS`.
- Produces:
  - `EtiquetaImpressa(lote FK PROTECT, estado CharField, copias PositiveIntegerField, reimpressao BooleanField, operacao FK, criado_em)`, admin `SomenteLeitura`.
  - `dados_etiqueta(lote, estado: str) -> dict` — `{"produto", "lote", "fabricacao": date, "validade": date, "validade_manual": bool, "conservacao": rótulo do estado, "forma": rótulo, "quantidade": saldo_lote}`; `fabricacao = lote.criado_em` em data local; `validade_manual` vem do movimento de entrada mais recente da porção.
  - `registrar_impressao(*, lote_id: int, estado: str, copias: int, autor: str, canal: str = "web", chave: str | None = None) -> dict` via `executar("registrar_impressao", ...)` — `copias >= 1`; `reimpressao = já existe EtiquetaImpressa do lote e estado`; não altera o lote. Retorna `{"etiqueta_id", "reimpressao"}`.

- [ ] **Step 1: Testes que falham**

```python
def test_impressao_e_reimpressao():   # 10 cópias → reimpressao False; 2 cópias → True; dois registros; lote igual
def test_dados_etiqueta_iguais_ao_lote():
def test_copias_zero_recusa():
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/test_etiquetas.py -v` → FAIL.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar tudo** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: registro de etiquetas internas"`

---

### Task 9: Telas — nova produção e novo tamanho

**Files:**
- Modify: `web/views.py`, `web/forms.py`, `web/urls.py`, `web/templates/web/inicio.html`
- Create: `web/templates/web/producao_nova.html`, `web/templates/web/producoes.html`
- Test: `tests/test_web_producao.py`

**Interfaces:**
- Consumes: `escalar`, `iniciar_producao`, `criar_tamanho`.
- Produces:
  - URLs: `producoes` (`/producao/`, lista as em andamento com link para cada uma, mais "Nova produção"), `producao_nova` (`/producao/nova/`), `tamanho_novo` (`/producao/tamanho/`, só POST).
  - `ProducaoForm`: `produto` (`Item` produto ativo, label "Produto"), `unidades` (Integer, `min_value=1`, mensagem `MAIOR_QUE_ZERO`), `forma` (radio: "Cru (guardar ou congelar)" / "Frito"), `chave` hidden.
  - `TamanhoForm`: `ficha` (ficha produto ativa, label "Receita"), `peso` (`DecimalBR`, "Peso de cada unidade (g)", `min_value=0.001`), `chave` hidden.
  - GET com dados válidos em `/producao/nova/` mostra a receita escalada (reusa o include de blocos de `web/receita.html`, extraído para `web/_blocos.html`) e o botão "Começar preparo"; POST chama `iniciar_producao` e redireciona para `producao` (Task 10). `RegraViolada` vira erro do formulário. Abaixo, o formulário "Outro tamanho" posta em `tamanho_novo`, que cria e volta para `/producao/nova/?produto=<novo id>` com a mensagem `f"Tamanho criado: {nome}."`.
  - `inicio.html` ganha links "Produção" e "Nova produção".

- [ ] **Step 1: Testes que falham**

```python
def test_nova_producao_mostra_receita_e_comeca(client, dono, bolinha, farinha_em_estoque):
    r = client.get("/producao/nova/", {"produto": bolinha.id, "unidades": 10, "forma": "cru"})
    assert "Massa simples" in texto(r) and "Começar preparo" in texto(r)
    r = client.post("/producao/nova/", {"produto": bolinha.id, "unidades": 10, "forma": "cru", "chave": "k1"})
    assert r.status_code == 302 and Producao.objects.count() == 1
def test_comecar_com_falta_mostra_erro(client, dono, bolinha):   # "Dê entrada no estoque antes de começar." e nenhuma Producao
def test_duplo_envio_uma_producao(client, dono, bolinha, farinha_em_estoque):
def test_outro_tamanho(client, dono, bolinha):   # POST ficha + peso "25" → Item "Bolinha 25 g" e redirect com ?produto=
def test_lista_em_andamento(client, dono, producao):
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/test_web_producao.py -v` → FAIL.
- [ ] **Step 3: Implementar** views, forms, templates.
- [ ] **Step 4: Rodar tudo** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: telas de nova produção e novo tamanho"`

---

### Task 10: Tela do preparo guiado

**Files:**
- Modify: `web/views.py`, `web/forms.py`, `web/urls.py`, `web/static/web/app.css`
- Create: `web/templates/web/producao.html`, `web/static/web/preparo.js`
- Test: `tests/test_web_preparo.py`

**Interfaces:**
- Consumes: operações das Tasks 6 e 7.
- Produces:
  - URL `producao` (`/producao/<id>/`): GET mostra **uma tarefa por tela** conforme `etapa_atual`; POST `acao` despacha para a operação e redireciona para a mesma URL (PRG). Cada formulário leva `chave` nova (uuid) gerada no render.
    - `etapa_atual == 0` (**Mise en place**): uma linha por `LinhaPreparo` com bloco, item, previsto (filtro `quantidade`), campo de peso (`DecimalBR`, unidade base ao lado), botões "Pesei" (`acao=peso`) e "Usei o previsto" (`acao=previsto`); linha já registrada mostra o valor usado. Botões "Usei o previsto em todos" (`acao=previsto_todos`) e "Começar etapas" (`acao=etapa`, `indice=1`).
    - `1..len(etapas)` (**Etapa i de n**): bloco, instrução, ponto ("Ponto: ..."), mídia (imagem ou vídeo), "Iniciar cronômetro (X min)" quando há `tempo_seg` (`acao=cronometro`, nome = instrução até 120 caracteres), "Voltar" e "Próxima etapa".
    - `fechamento` (**Fechamento**): quantidade boa (inicial = unidades), perdas, motivo das perdas, estado inicial (radio de `ESTADOS`), validade manual + justificativa (só quando não há critério para produto/forma/estado escolhidos — sempre presentes, opcionais, com a dica "Só se não houver critério de validade"), "Como foi?" (anotacao, inclui sobras), caixa "Confirmo a perda total" e "Concluir produção".
    - Concluída: resumo previsto × realizado (RF-OP-09): por linha previsto e usado; unidades planejadas e boas; perdas; custo total e unitário; link para o lote.
    - Em todas as telas em andamento: painel de cronômetros ativos (`data-fim` em ISO 8601 UTC, botão "Parar" com `acao=parar`) e "Cancelar produção" com motivo, no rodapé.
  - `preparo.js`: a cada segundo escreve `mm:ss` restante em cada `[data-fim]`; ao chegar a zero adiciona a classe `tocando` e toca um bipe (Web Audio, 880 Hz, 0,3 s a cada 1 s) até "Parar"; pede `navigator.wakeLock.request("screen")` ao carregar e de novo em `visibilitychange`. Sem rede: tudo calculado pelo `data-fim`, então trocar de etapa (novo GET) não perde o cronômetro.
  - CSS: `.tocando` com fundo de alerta e texto "Tempo!" visível (não só cor); botões da tela de preparo com pelo menos 56 px de altura.

- [ ] **Step 1: Testes que falham**

```python
def test_fluxo_completo_pela_tela(client, dono, producao):
    post(client, producao, acao="previsto_todos"); post(client, producao, acao="etapa", indice=1)
    assert "Etapa 1 de 2" in texto(client.get(url))
    post(client, producao, acao="etapa", indice=3)
    post(client, producao, acao="concluir", quantidade_boa=10, perdas=0, estado="resfriado", ...)
    assert Producao.objects.get().status == "concluida" and "Previsto" in texto(client.get(url))
def test_peso_com_ponto_recusado(client, dono, producao):   # "Use vírgula para decimais (ex.: 1,5)."
def test_sair_do_mise_en_place_sem_pesar_mostra_erro(client, dono, producao):
def test_outro_aparelho_ve_o_mesmo_estado(client, dono, producao, django_user_model):
    # cronômetro iniciado e etapa 1 pelo primeiro client; um segundo Client logado vê "Etapa 1 de 2" e o mesmo data-fim
def test_cronometro_aparece_em_todas_as_etapas(client, dono, producao):
def test_tela_carrega_preparo_js(client, dono, producao):
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/test_web_preparo.py -v` → FAIL.
- [ ] **Step 3: Implementar** view, template, JS e CSS.
- [ ] **Step 4: Rodar tudo** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Ver no navegador** — subir o servidor pelo `.claude/launch.json` (criar a configuração `sabor` com `uv run python manage.py runserver 8000` se não existir), percorrer um preparo da Bolinha em 360 px: sem rolagem horizontal, cronômetro chega a zero e mostra "Tempo!", tela muda de etapa e o cronômetro continua. Anotar o resultado no commit.
- [ ] **Step 6: Commit** — `git commit -m "feat: tela do preparo guiado com cronômetros"`

---

### Task 11: Tela do lote — conservação e etiquetas

**Files:**
- Modify: `web/views.py`, `web/forms.py`, `web/urls.py`, `web/static/web/app.css`
- Create: `web/templates/web/lote.html`, `web/templates/web/etiquetas.html`
- Test: `tests/test_web_lote.py`

**Interfaces:**
- Consumes: `saldo_lote`, `validade_porcao`, `transferir_estado` (Tasks 1 e 4), `origem` (Task 7), `dados_etiqueta`, `registrar_impressao` (Task 8).
- Produces:
  - URL `lote` (`/lotes/<id>/`): produto, código, forma, fabricação, custo unitário; tabela por estado com saldo e validade (marcada "informada manualmente" quando for o caso); origem (lotes consumidos e quantidades); formulário "Mudar conservação" (quantidade, de, para, validade manual e justificativa opcionais) que chama `transferir_estado`; por estado com saldo, link "Etiquetas" para `etiquetas`.
  - URL `etiquetas` (`/lotes/<id>/etiquetas/?estado=...&copias=N`, padrão `copias` = saldo do estado): N etiquetas com produto, "Lote", "Fabricação", "Validade" (+ " (informada manualmente)"), conservação, forma, quantidade e "USO INTERNO"; botões "Imprimir" (`window.print()`) e "Saiu certo" (POST que chama `registrar_impressao` e volta ao lote com "Impressão registrada." ou "Reimpressão registrada."). CSS `@media print` esconde cabeçalho e botões.
  - A tela de produção concluída (Task 10) linka para o lote e para as etiquetas do estado inicial.

- [ ] **Step 1: Testes que falham**

```python
def test_lote_mostra_saldos_e_origem(client, dono, lote_produzido):   # "9 un", "Resfriado", "Farinha de trigo"
def test_mudar_conservacao_pela_tela(client, dono, lote_produzido):   # 5 → congelado; tela mostra 4 resfriado e 5 congelado
def test_etiquetas_tem_uso_interno_e_nao_registram_no_get(client, dono, lote_produzido):
def test_saiu_certo_registra_e_depois_reimpressao(client, dono, lote_produzido):
```
`lote_produzido` (fixture em `conftest.py`): a produção da Task 7 concluída com 9 boas em resfriado.

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/test_web_lote.py -v` → FAIL.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar tudo** — `uv run pytest -v` → PASS.
- [ ] **Step 5: Ver no navegador** — abrir a tela de etiquetas, conferir a prévia de impressão (cabeçalho e botões somem).
- [ ] **Step 6: Commit** — `git commit -m "feat: tela do lote com conservação e etiquetas"`

---

### Task 12: Fechamento do plano

**Files:**
- Create: `docs/superpowers/plans/2026-10-19-plano-2-pendencias.md`
- Modify: `docs/superpowers/plans/2026-10-19-plano-1-pendencias.md` (marcar como resolvida a pendência do admin fora de `executar()`)

- [ ] **Step 1: Rodar a suíte** — `uv run pytest -v` → PASS, sem avisos de migração (`uv run python manage.py makemigrations --check --dry-run` → "No changes detected").
- [ ] **Step 2: Registrar** decisões tomadas na execução e o que ficou para depois: consumo pendente e conciliação (Plano 3); plano de produção e status "planejada" (Planos 4/6); troca de lote pela conversa (Plano 4); proposta de ajuste de ficha pelo rendimento (Plano 4, os dados de previsto × usado já ficam gravados); embalagens de produção no custo (quando a ficha tiver embalagens); modelos de etiqueta e impressora térmica (PR-03); data-base da validade (REG-02); fritura de lotes crus já guardados e troca de óleo (Plano 6).
- [ ] **Step 3: Commit** — `git commit -m "docs: pendências e decisões da execução do Plano 2"`
