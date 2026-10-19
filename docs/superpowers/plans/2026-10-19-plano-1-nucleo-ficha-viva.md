# Plano 1 — Núcleo de regras e ficha viva — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ter o núcleo de regras funcionando de ponta a ponta para a ficha viva: o dono cadastra ingredientes e fichas, dá entrada de estoque e pede "50 coxinhas de 150 g", e recebe a receita escalada, um bloco por preparação, com o indicador do que falta no estoque.

**Architecture:** Projeto Django com SQLite. Toda gravação de domínio passa por `nucleo.operacoes.executar()`, que é atômica, idempotente e auditada. Esse é o futuro "caminho único de gravação" que o agente vai usar por MCP. Os cálculos (conversão e escala) são funções puras e determinísticas. As telas são templates Django simples. O admin do Django serve como formulário de plano B para os cadastros.

**Tech Stack:** Python 3.12, uv, Django 5.2 (LTS), SQLite, pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-10-19-agente-cozinha-design.md` (§6.1, §6.3, §7). Regras de domínio em `docs/prd/02-prd.md` (RN-01, RN-06, RN-13, RN-39, RN-40, RF-CAD, RF-EST-01/08, RF-FIC).

## Sequência de planos (contexto)

O design aprovado cobre vários subsistemas. Por isso, cada plano entrega software testável por conta própria:

1. **Este plano:** núcleo, cadastros, estoque básico, fichas e escala da receita.
2. Produção guiada: preparo etapa por etapa, cronômetros, pesagem, conclusão com lote e custo real, produto por tamanho, conservação e etiquetas.
3. Compras manuais, recebimento, pendências e contas a pagar.
4. Agente: ferramentas MCP sobre `executar()`, alçada, caixa de decisões, conversa web, fila de tarefas, resumo da manhã e backup.
5. Telegram e leitura de cupom.
6. Vendas, encomendas, contas a receber, fritura e óleo.
7. Custos do período e relatórios.

## Global Constraints

- Python 3.12; Django `>=5.2,<5.3`; banco SQLite em `db.sqlite3` na raiz do projeto, ignorado pelo git; arquivos enviados em `media/`.
- Interface em pt-BR: `LANGUAGE_CODE = "pt-br"`, `TIME_ZONE = "America/Sao_Paulo"`, `USE_TZ = True`.
- Quantidades sempre em `Decimal`, nunca `float`. Cada item guarda as quantidades na sua **unidade base**, que é uma de `g`, `mL` ou `un`. Precisão: quantidade com 3 casas e custo unitário com 4 casas. Arredondamento só na exibição (PRD RNF-12).
- Conversões padrão fixas: `kg` = 1000 `g` e `L` = 1000 `mL`. Qualquer outra unidade exige uma `Conversao` cadastrada no item. Sem ela, a operação é recusada (PRD RN-40, DEC-F2-029).
- **Toda gravação de domínio passa por `executar()`.** Saldo de estoque nunca é editado: é sempre a soma dos movimentos (PRD RN-01).
- Um único usuário (o dono). Todas as telas exigem login (PRD RF-ADM-01).
- Nenhuma conta de quantidade ou custo é feita por IA (design, anti-objetivo A3).

## Review Focus

- Ficha de produto cujas proporções não somam 100% → recusada ao salvar, com mensagem (teste na Task 5).
- Preparação com rendimento zero ou vazio → recusada ao salvar, nunca divisão por zero na escala (teste na Task 5).
- Mesmo ingrediente em dois blocos (ex.: farinha na massa e no empanamento) com estoque insuficiente no total → a falta é calculada sobre a soma das necessidades, não bloco a bloco (teste na Task 6).
- Pedido com unidades ou peso zero ou negativo → erro no formulário, nada é calculado (teste na Task 7).
- Duplo envio do formulário de entrada de estoque → um único movimento, pela chave de idempotência (teste na Task 7).

---

### Task 1: Projeto Django, login e configuração de testes

**Files:**
- Create: `pyproject.toml` (via uv), `manage.py`, `sabor/__init__.py`, `sabor/settings.py`, `sabor/urls.py`, `sabor/wsgi.py`
- Create: `web/__init__.py`, `web/apps.py`, `web/views.py`, `web/urls.py`, `web/templates/web/base.html`, `web/templates/web/inicio.html`, `web/templates/registration/login.html`, `web/static/web/app.css`
- Create: `conftest.py`, `pytest.ini`
- Modify: `.gitignore` (acrescentar `db.sqlite3` e `/media/`)
- Test: `tests/test_web_acesso.py`

**Interfaces:**
- Produces: URL nomeada `inicio` (`/`), `login` (`/entrar/`), `logout` (`/sair/`); template base `web/base.html` com bloco `conteudo`; fixture pytest `dono` (usuário logado via `client.force_login`) em `conftest.py`.

- [ ] **Step 1: Criar o projeto**

Run:
```bash
uv init --app --name sabor-express --python 3.12 --no-readme && rm -f main.py hello.py
uv add "django>=5.2,<5.3"
uv add --dev pytest pytest-django
uv run django-admin startproject sabor .
uv run python manage.py startapp web
```
Expected: `manage.py` e `sabor/settings.py` existem; `uv run python -c "import django"` sem erro.

- [ ] **Step 2: Configurar settings**

Em `sabor/settings.py`: `LANGUAGE_CODE="pt-br"`, `TIME_ZONE="America/Sao_Paulo"`, `USE_TZ=True`, `LOGIN_URL="login"`, `LOGIN_REDIRECT_URL="inicio"`, `LOGOUT_REDIRECT_URL="login"`, `MEDIA_ROOT=BASE_DIR / "media"`, `MEDIA_URL="/media/"`, `SECRET_KEY` e `DEBUG` lidos de variáveis de ambiente `SABOR_SECRET_KEY` (obrigatória quando `SABOR_DEBUG != "1"`) e `SABOR_DEBUG` (padrão `"1"` em desenvolvimento), `ALLOWED_HOSTS` de `SABOR_ALLOWED_HOSTS` separado por vírgula (padrão `"localhost,127.0.0.1"`). Registrar `web` em `INSTALLED_APPS`. `pytest.ini`: `DJANGO_SETTINGS_MODULE = sabor.settings`, `testpaths = tests`.

- [ ] **Step 3: Escrever o teste que falha**

```python
# tests/test_web_acesso.py
def test_anonimo_vai_para_login(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.url.startswith("/entrar/")

def test_dono_ve_inicio(client, dono):
    r = client.get("/")
    assert r.status_code == 200
    assert "Sabor Express" in r.content.decode()
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `uv run pytest tests/test_web_acesso.py -v`
Expected: FAIL (a URL `/` não existe ou a fixture `dono` não foi definida).

- [ ] **Step 5: Implementar**

View `inicio` com `@login_required`, que renderiza `web/inicio.html` (título "Sabor Express" e links para as telas das Tasks 7). `LoginView`/`LogoutView` do Django em `/entrar/` e `/sair/`. `base.html`: `<meta name="viewport" content="width=device-width, initial-scale=1">`, `lang="pt-BR"` e link para `web/app.css`. CSS mínimo: fonte do sistema, botões com altura mínima de 44 px, largura máxima de 960 px e nada que cause rolagem horizontal a 360 px. Fixture `dono` em `conftest.py`: cria um `User` e chama `client.force_login`.

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest -v`
Expected: PASS (2 testes).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock manage.py sabor web conftest.py pytest.ini tests .gitignore .python-version
git commit -m "feat: projeto Django com login único e testes"
```

---

### Task 2: Operações de domínio (caminho único de gravação)

**Files:**
- Create: `nucleo/__init__.py`, `nucleo/apps.py`, `nucleo/models.py`, `nucleo/operacoes.py`, `nucleo/admin.py`, `nucleo/migrations/`
- Modify: `sabor/settings.py` (registrar `nucleo`)
- Test: `tests/test_operacoes.py`

**Interfaces:**
- Produces:
  - `class RegraViolada(Exception)`: erro de regra de negócio, com mensagem em pt-BR para o usuário.
  - `RegistroOperacao` (model): `nome: CharField`, `chave: CharField(unique, null=True)`, `canal: CharField` (`"web" | "telegram" | "agente" | "sistema"`), `autor: CharField`, `status: CharField` (`"sucesso" | "erro"`), `resultado: JSONField(null)`, `erro: TextField(blank)`, `criado_em: DateTimeField(auto_now_add)`.
  - `executar(nome: str, func: Callable[[RegistroOperacao], dict], *, autor: str, canal: str = "web", chave: str | None = None) -> dict`. A `func` recebe o registro da própria operação, para ligar a ele o que grava (ex.: `Movimento.operacao`).

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_operacoes.py
import pytest
from nucleo.operacoes import executar, RegraViolada
from nucleo.models import RegistroOperacao

pytestmark = pytest.mark.django_db

def test_sucesso_registra_auditoria():
    r = executar("teste", lambda op: {"ok": 1}, autor="dono", canal="web")
    assert r == {"ok": 1}
    reg = RegistroOperacao.objects.get()
    assert (reg.nome, reg.status, reg.canal, reg.autor, reg.resultado) == ("teste", "sucesso", "web", "dono", {"ok": 1})

def test_repeticao_com_mesma_chave_nao_reexecuta():
    chamadas = []
    f = lambda op: chamadas.append(1) or {"n": len(chamadas)}
    a = executar("teste", f, autor="dono", chave="k1")
    b = executar("teste", f, autor="dono", chave="k1")
    assert a == b == {"n": 1}
    assert len(chamadas) == 1
    assert RegistroOperacao.objects.count() == 1

def test_erro_desfaz_gravacao_parcial_e_registra_erro():
    def f(op):
        RegistroOperacao.objects.create(nome="lixo", canal="web", autor="x", status="sucesso")
        raise RegraViolada("saldo insuficiente")
    with pytest.raises(RegraViolada, match="saldo insuficiente"):
        executar("teste", f, autor="dono", chave="k2")
    assert not RegistroOperacao.objects.filter(nome="lixo").exists()
    reg = RegistroOperacao.objects.get(nome="teste")
    assert reg.status == "erro" and "saldo insuficiente" in reg.erro

def test_chave_que_falhou_pode_ser_tentada_de_novo():
    def falha(op): raise RegraViolada("x")
    with pytest.raises(RegraViolada):
        executar("teste", falha, autor="dono", chave="k3")
    assert executar("teste", lambda op: {"ok": 1}, autor="dono", chave="k3") == {"ok": 1}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_operacoes.py -v`
Expected: FAIL (`ModuleNotFoundError: nucleo`).

- [ ] **Step 3: Implementar `executar` em `nucleo/operacoes.py`**

Fluxo:
1. Se `chave` já tem registro com `status="sucesso"`, devolver `resultado` sem chamar `func`. Se tem registro com `status="erro"`, apagá-lo, para liberar a chave.
2. Dentro de `transaction.atomic()`: criar o `RegistroOperacao` (`status="sucesso"`, `resultado=None`), chamar `func(registro)`, gravar `resultado` no registro.
3. Se houver exceção, a transação desfaz tudo, inclusive o registro. Fora dela, criar um registro com `status="erro"` e a mensagem, e relançar a exceção.

O resultado precisa ser serializável em JSON (`Decimal` vira `str` antes de retornar). Registrar `RegistroOperacao` no admin como somente leitura (`has_add/change/delete_permission` retornam `False`).

- [ ] **Step 4: Migrar e rodar**

Run: `uv run python manage.py makemigrations nucleo && uv run pytest tests/test_operacoes.py -v`
Expected: PASS (4 testes).

- [ ] **Step 5: Commit**

```bash
git add nucleo sabor/settings.py tests/test_operacoes.py
git commit -m "feat: operações de domínio atômicas, idempotentes e auditadas"
```

---

### Task 3: Itens e conversões de unidade

**Files:**
- Create: `cadastros/__init__.py`, `cadastros/apps.py`, `cadastros/models.py`, `cadastros/unidades.py`, `cadastros/admin.py`, `cadastros/migrations/`
- Modify: `sabor/settings.py` (registrar `cadastros`)
- Test: `tests/test_unidades.py`

**Interfaces:**
- Consumes: `RegraViolada` (Task 2).
- Produces:
  - `Item` (model): `nome: CharField(unique)`, `tipo: CharField` (`"ingrediente" | "insumo" | "embalagem"`), `unidade_base: CharField` (`"g" | "mL" | "un"`), `controla_validade: BooleanField(default=True)`, `estoque_minimo: DecimalField(max_digits=14, decimal_places=3, default=0)`, `ativo: BooleanField(default=True)`. `__str__` devolve `nome`.
  - `Conversao` (model): `item: FK Item (related_name="conversoes")`, `unidade: CharField` (ex.: `"dz"`, `"pct"`, `"kg"` para item em `mL`), `fator: DecimalField(max_digits=14, decimal_places=6)` = quantas unidades base há em 1 `unidade`. Unicidade `(item, unidade)`.
  - `para_base(item: Item, quantidade: Decimal, unidade: str) -> Decimal` em `cadastros/unidades.py`.

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_unidades.py
from decimal import Decimal as D
import pytest
from cadastros.models import Item, Conversao
from cadastros.unidades import para_base
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db

@pytest.fixture
def farinha(): return Item.objects.create(nome="Farinha de trigo", tipo="ingrediente", unidade_base="g")
@pytest.fixture
def oleo(): return Item.objects.create(nome="Óleo", tipo="insumo", unidade_base="mL")
@pytest.fixture
def ovo(): return Item.objects.create(nome="Ovo", tipo="ingrediente", unidade_base="un")

def test_padroes_fixos(farinha, oleo):
    assert para_base(farinha, D("1.8"), "kg") == D("1800")
    assert para_base(farinha, D("250"), "g") == D("250")
    assert para_base(oleo, D("2.7"), "L") == D("2700")

def test_conversao_cadastrada(ovo, oleo):
    Conversao.objects.create(item=ovo, unidade="dz", fator=D("12"))
    Conversao.objects.create(item=oleo, unidade="kg", fator=D("1087"))
    assert para_base(ovo, D("2.5"), "dz") == D("30")
    assert para_base(oleo, D("15"), "kg") == D("16305")

def test_sem_fator_recusa_com_mensagem(oleo, ovo):
    with pytest.raises(RegraViolada, match="Cadastre o fator de 'kg' para 'Ovo'"):
        para_base(ovo, D("1"), "kg")
    with pytest.raises(RegraViolada, match="Cadastre o fator de 'g' para 'Óleo'"):
        para_base(oleo, D("1"), "g")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_unidades.py -v`
Expected: FAIL (`ModuleNotFoundError: cadastros`).

- [ ] **Step 3: Implementar models e `para_base`**

Ordem de resolução: se `unidade == item.unidade_base`, fator 1. Senão, usar o padrão fixo (`kg`→`g` 1000; `L`→`mL` 1000) quando a base corresponder. Senão, usar a `Conversao` do item. Senão, levantar `RegraViolada(f"Cadastre o fator de '{unidade}' para '{item.nome}'.")`. Admin: `Item` com `Conversao` inline.

- [ ] **Step 4: Migrar e rodar**

Run: `uv run python manage.py makemigrations cadastros && uv run pytest tests/test_unidades.py -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add cadastros sabor/settings.py tests/test_unidades.py
git commit -m "feat: itens com unidade base e conversões obrigatórias"
```

---

### Task 4: Estoque por lote e movimento, com entrada manual

**Files:**
- Create: `estoque/__init__.py`, `estoque/apps.py`, `estoque/models.py`, `estoque/servicos.py`, `estoque/admin.py`, `estoque/migrations/`
- Modify: `sabor/settings.py` (registrar `estoque`)
- Test: `tests/test_estoque.py`

**Interfaces:**
- Consumes: `executar`, `RegraViolada` (Task 2); `Item`, `para_base` (Task 3).
- Produces:
  - `Lote` (model): `item: FK Item`, `codigo: CharField(blank)`, `sem_lote: BooleanField`, `validade: DateField(null)`, `custo_unitario: DecimalField(max_digits=14, decimal_places=4)` por unidade base, `criado_em: DateTimeField(auto_now_add)`.
  - `Movimento` (model): `tipo: CharField` (neste plano só `"entrada_manual"`), `item: FK Item`, `lote: FK Lote`, `quantidade: DecimalField(max_digits=14, decimal_places=3)` (positiva = entrada), `motivo: CharField`, `operacao: FK nucleo.RegistroOperacao(null)`, `criado_em: DateTimeField(auto_now_add)`.
  - `saldo(item: Item) -> Decimal` em `estoque/servicos.py`: soma das quantidades dos movimentos do item, `Decimal("0")` se não houver nenhum.
  - `entrada_manual(*, item_id: int, quantidade: Decimal, unidade: str, custo_total: Decimal, motivo: str, lote_codigo: str = "", validade: date | None = None, autor: str, canal: str = "web", chave: str | None = None) -> dict` em `estoque/servicos.py`. Devolve `{"lote_id": int, "quantidade_base": str}`.

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_estoque.py
from decimal import Decimal as D
import datetime as dt
import pytest
from cadastros.models import Item
from estoque.models import Lote, Movimento
from estoque.servicos import entrada_manual, saldo
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db

@pytest.fixture
def requeijao(): return Item.objects.create(nome="Requeijão", tipo="ingrediente", unidade_base="g")

def test_entrada_cria_lote_e_movimento_em_unidade_base(requeijao):
    r = entrada_manual(item_id=requeijao.id, quantidade=D("1.5"), unidade="kg", custo_total=D("45.00"),
                       motivo="estoque inicial", lote_codigo="REQ-1012", validade=dt.date(2026, 10, 24), autor="dono")
    lote = Lote.objects.get(id=r["lote_id"])
    assert lote.custo_unitario == D("0.0300")
    assert saldo(requeijao) == D("1500")
    assert Movimento.objects.get().operacao.nome == "entrada_manual"

def test_sem_codigo_marca_sem_lote(requeijao):
    r = entrada_manual(item_id=requeijao.id, quantidade=D("200"), unidade="g", custo_total=D("6"),
                       motivo="estoque inicial", validade=dt.date(2026, 10, 30), autor="dono")
    assert Lote.objects.get(id=r["lote_id"]).sem_lote is True

def test_motivo_obrigatorio(requeijao):
    with pytest.raises(RegraViolada, match="Informe o motivo"):
        entrada_manual(item_id=requeijao.id, quantidade=D("1"), unidade="g", custo_total=D("1"), motivo=" ", autor="dono")

def test_quantidade_deve_ser_positiva(requeijao):
    with pytest.raises(RegraViolada, match="maior que zero"):
        entrada_manual(item_id=requeijao.id, quantidade=D("0"), unidade="g", custo_total=D("1"), motivo="x", autor="dono")

def test_validade_obrigatoria_quando_item_controla(requeijao):
    with pytest.raises(RegraViolada, match="Informe a validade"):
        entrada_manual(item_id=requeijao.id, quantidade=D("1"), unidade="g", custo_total=D("1"), motivo="x", autor="dono")

def test_saldo_sem_movimentos_e_zero(requeijao):
    assert saldo(requeijao) == D("0")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_estoque.py -v`
Expected: FAIL (`ModuleNotFoundError: estoque`).

- [ ] **Step 3: Implementar**

`entrada_manual` valida as entradas e chama `executar("entrada_manual", func, ...)`. A `func` cria o `Lote` e o `Movimento`, com `custo_unitario = custo_total / quantidade_base`, quantizado em 4 casas, e liga o movimento ao registro que a `func` recebe (`Movimento.operacao = op`). Admin de `Lote` e `Movimento` somente leitura (sem adicionar, alterar ou apagar).

- [ ] **Step 4: Migrar e rodar**

Run: `uv run python manage.py makemigrations estoque && uv run pytest -v`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add estoque nucleo sabor/settings.py tests/test_estoque.py
git commit -m "feat: estoque por lote e movimento com entrada manual"
```

---

### Task 5: Fichas técnicas com proporções, rendimento e etapas

**Files:**
- Create: `fichas/__init__.py`, `fichas/apps.py`, `fichas/models.py`, `fichas/validacao.py`, `fichas/admin.py`, `fichas/migrations/`
- Modify: `sabor/settings.py` (registrar `fichas`)
- Test: `tests/test_fichas.py`

**Interfaces:**
- Consumes: `Item` (Task 3), `RegraViolada` (Task 2).
- Produces:
  - `Ficha` (model): `nome: CharField(unique)`, `tipo: CharField` (`"preparacao" | "produto"`), `rendimento_g: DecimalField(max_digits=14, decimal_places=3, null)` (obrigatório e > 0 para preparação; vazio para produto), `ativa: BooleanField(default=True)`.
  - `ComponenteItem` (model): `ficha: FK Ficha (related_name="itens")`, `item: FK Item`, `quantidade: DecimalField(max_digits=14, decimal_places=3)` na unidade base do item, `ordem: PositiveIntegerField`. Só em fichas de preparação.
  - `ComponentePreparacao` (model): `ficha: FK Ficha (related_name="subpreparacoes")`, `preparacao: FK Ficha (related_name="+")`, `quantidade_g: DecimalField(max_digits=14, decimal_places=3)`, `ordem`. Só em fichas de preparação.
  - `Proporcao` (model): `ficha: FK Ficha (related_name="proporcoes")` do tipo produto, `preparacao: FK Ficha (related_name="+")`, `percentual: DecimalField(max_digits=6, decimal_places=3)`, `ordem`. Só em fichas de produto.
  - `Etapa` (model): `ficha: FK Ficha (related_name="etapas")`, `ordem`, `instrucao: CharField(max_length=300)`, `tempo_seg: PositiveIntegerField(null)`, `ponto: CharField(blank)`, `midia: FileField(upload_to="etapas/", blank)`.
  - `validar_ficha(ficha: Ficha) -> None` em `fichas/validacao.py`. Levanta `RegraViolada` com mensagem em pt-BR.

> Versionamento (PRD RN-14) fica para o Plano 2, quando existirem produções que usam a ficha. Neste plano a ficha é editada no lugar.

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_fichas.py
from decimal import Decimal as D
import pytest
from cadastros.models import Item
from fichas.models import Ficha, ComponenteItem, ComponentePreparacao, Proporcao
from fichas.validacao import validar_ficha
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db

def prep(nome, rend="1000"):
    return Ficha.objects.create(nome=nome, tipo="preparacao", rendimento_g=D(rend))

def test_proporcoes_devem_somar_100():
    p = Ficha.objects.create(nome="Coxinha", tipo="produto")
    Proporcao.objects.create(ficha=p, preparacao=prep("Massa"), percentual=D("60"), ordem=1)
    Proporcao.objects.create(ficha=p, preparacao=prep("Recheio"), percentual=D("30"), ordem=2)
    with pytest.raises(RegraViolada, match="somam 90"):
        validar_ficha(p)

def test_preparacao_exige_rendimento_positivo():
    with pytest.raises(RegraViolada, match="rendimento"):
        validar_ficha(Ficha.objects.create(nome="Massa", tipo="preparacao", rendimento_g=D("0")))

def test_ciclo_entre_preparacoes_e_recusado():
    a, b = prep("Caldo"), prep("Massa")
    ComponentePreparacao.objects.create(ficha=b, preparacao=a, quantidade_g=D("600"), ordem=1)
    ComponentePreparacao.objects.create(ficha=a, preparacao=b, quantidade_g=D("10"), ordem=1)
    with pytest.raises(RegraViolada, match="circular"):
        validar_ficha(a)

def test_ficha_valida_passa():
    sal = Item.objects.create(nome="Sal", tipo="ingrediente", unidade_base="g", controla_validade=False)
    m = prep("Massa")
    ComponenteItem.objects.create(ficha=m, item=sal, quantidade=D("8"), ordem=1)
    validar_ficha(m)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_fichas.py -v`
Expected: FAIL (`ModuleNotFoundError: fichas`).

- [ ] **Step 3: Implementar models e `validar_ficha`**

Regras:
- Produto: precisa ter pelo menos uma `Proporcao`, e a soma dos percentuais deve ser exatamente 100. Mensagem: `"As proporções somam {soma}%, precisam somar 100%."`
- Preparação: `rendimento_g > 0`.
- Ciclo: busca em profundidade pelas `subpreparacoes`. Se a ficha aparecer de novo, levantar `"Referência circular: ..."`, com os nomes do caminho.

Admin: `Ficha` com inlines de `ComponenteItem`, `ComponentePreparacao`, `Proporcao` e `Etapa`. Em `save_related`, chamar `validar_ficha` e, se der `RegraViolada`, mostrar a mensagem com `messages.error` e reverter (transação). A ficha não fica salva inválida.

- [ ] **Step 4: Migrar e rodar**

Run: `uv run python manage.py makemigrations fichas && uv run pytest tests/test_fichas.py -v`
Expected: PASS (4 testes).

- [ ] **Step 5: Commit**

```bash
git add fichas sabor/settings.py tests/test_fichas.py
git commit -m "feat: fichas com proporções, rendimento, etapas e validação"
```

---

### Task 6: Escala da receita em cascata com indicador de estoque

**Files:**
- Create: `fichas/escala.py`
- Test: `tests/test_escala.py`

**Interfaces:**
- Consumes: modelos da Task 5; `saldo` (Task 4); `RegraViolada` (Task 2).
- Produces (em `fichas/escala.py`):

```python
@dataclass(frozen=True)
class Linha:
    item_id: int
    nome: str
    unidade_base: str        # "g" | "mL" | "un"
    quantidade: Decimal      # na unidade base, sem arredondar
    falta: Decimal           # 0 se o estoque cobre a necessidade TOTAL do item no pedido

@dataclass(frozen=True)
class Bloco:
    nome: str                # nome da preparação, ou "Montagem" para as etapas da ficha de produto
    total_g: Decimal
    linhas: list[Linha]
    etapas: list[Etapa]

@dataclass(frozen=True)
class ReceitaEscalada:
    produto: str
    unidades: int
    peso_unitario_g: Decimal
    total_g: Decimal
    blocos: list[Bloco]

def escalar(ficha_produto: Ficha, unidades: int, peso_unitario_g: Decimal) -> ReceitaEscalada
```

- [ ] **Step 1: Escrever os testes que falham**

Dados do exemplo do design (§6.3): coxinha de 150 g, proporções 60 / 33 / 7.

```python
# tests/test_escala.py
from decimal import Decimal as D
import datetime as dt
import pytest
from cadastros.models import Item
from estoque.servicos import entrada_manual
from fichas.models import Ficha, ComponenteItem, ComponentePreparacao, Proporcao, Etapa
from fichas.escala import escalar
from nucleo.operacoes import RegraViolada

pytestmark = pytest.mark.django_db

def item(nome, base="g"): return Item.objects.create(nome=nome, tipo="ingrediente", unidade_base=base, controla_validade=False)
def prep(nome, rend="1000"): return Ficha.objects.create(nome=nome, tipo="preparacao", rendimento_g=D(rend))

@pytest.fixture
def coxinha():
    farinha, caldo_frango, frango, requeijao, rosca = item("Farinha de trigo"), item("Caldo", "mL"), item("Frango"), item("Requeijão"), item("Farinha de rosca")
    massa, recheio, emp = prep("Massa"), prep("Recheio"), prep("Empanamento")
    ComponenteItem.objects.create(ficha=massa, item=caldo_frango, quantidade=D("600"), ordem=1)
    ComponenteItem.objects.create(ficha=massa, item=farinha, quantidade=D("400"), ordem=2)
    ComponenteItem.objects.create(ficha=recheio, item=frango, quantidade=D("800"), ordem=1)
    ComponenteItem.objects.create(ficha=recheio, item=requeijao, quantidade=D("120"), ordem=2)
    ComponenteItem.objects.create(ficha=emp, item=rosca, quantidade=D("700"), ordem=1)
    ComponenteItem.objects.create(ficha=emp, item=farinha, quantidade=D("300"), ordem=2)
    p = Ficha.objects.create(nome="Coxinha de frango", tipo="produto")
    Proporcao.objects.create(ficha=p, preparacao=recheio, percentual=D("33"), ordem=1)
    Proporcao.objects.create(ficha=p, preparacao=massa, percentual=D("60"), ordem=2)
    Proporcao.objects.create(ficha=p, preparacao=emp, percentual=D("7"), ordem=3)
    Etapa.objects.create(ficha=p, ordem=1, instrucao="Modele as coxinhas")
    return p

def test_totais_e_ordem_dos_blocos(coxinha):
    r = escalar(coxinha, 50, D("150"))
    assert r.total_g == D("7500")
    assert [(b.nome, b.total_g) for b in r.blocos] == [
        ("Recheio", D("2475")), ("Massa", D("4500")), ("Empanamento", D("525")), ("Montagem", D("7500"))]
    assert r.blocos[-1].linhas == [] and r.blocos[-1].etapas[0].instrucao == "Modele as coxinhas"

def test_ingredientes_escalados(coxinha):
    massa = escalar(coxinha, 50, D("150")).blocos[1]
    assert {l.nome: l.quantidade for l in massa.linhas} == {"Caldo": D("2700"), "Farinha de trigo": D("1800")}

def test_falta_considera_necessidade_total_do_item(coxinha):
    farinha = Item.objects.get(nome="Farinha de trigo")
    entrada_manual(item_id=farinha.id, quantidade=D("1.9"), unidade="kg", custo_total=D("10"), motivo="inicial", autor="dono")
    r = escalar(coxinha, 50, D("150"))
    # massa 1800 g + empanamento 157,5 g = 1957,5 g; saldo 1900 g
    linhas_farinha = [l for b in r.blocos for l in b.linhas if l.nome == "Farinha de trigo"]
    assert [l.falta for l in linhas_farinha] == [D("57.5"), D("57.5")]
    assert next(l for l in r.blocos[0].linhas if l.nome == "Frango").falta == D("1980")

def test_subpreparacao_vem_antes_da_preparacao_que_a_usa(coxinha):
    caldo_caseiro = prep("Caldo caseiro", "2000")
    agua = item("Água", "mL")
    ComponenteItem.objects.create(ficha=caldo_caseiro, item=agua, quantidade=D("2000"), ordem=1)
    ComponentePreparacao.objects.create(ficha=Ficha.objects.get(nome="Massa"), preparacao=caldo_caseiro, quantidade_g=D("100"), ordem=3)
    nomes = [b.nome for b in escalar(coxinha, 50, D("150")).blocos]
    assert nomes.index("Caldo caseiro") == nomes.index("Massa") - 1
    caldo = next(b for b in escalar(coxinha, 50, D("150")).blocos if b.nome == "Caldo caseiro")
    assert caldo.total_g == D("450") and caldo.linhas[0].quantidade == D("450")

@pytest.mark.parametrize("unidades,peso", [(0, D("150")), (50, D("0")), (-1, D("150"))])
def test_pedido_invalido(coxinha, unidades, peso):
    with pytest.raises(RegraViolada):
        escalar(coxinha, unidades, peso)

def test_so_ficha_de_produto(coxinha):
    with pytest.raises(RegraViolada, match="produto"):
        escalar(Ficha.objects.get(nome="Massa"), 10, D("100"))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_escala.py -v`
Expected: FAIL (`ModuleNotFoundError: fichas.escala`).

- [ ] **Step 3: Implementar `escalar`**

Algoritmo:
1. Validar o pedido (`unidades > 0`, `peso > 0`, ficha do tipo produto) e chamar `validar_ficha`.
2. `total_g = unidades × peso_unitario_g`.
3. Para cada `Proporcao`, em `ordem`, expandir a preparação com `alvo_g = total_g × percentual / 100`. A expansão usa `fator = alvo_g / rendimento_g`: os `ComponenteItem` viram `Linha` com `quantidade × fator`; cada `ComponentePreparacao` é expandida **recursivamente antes**, com `alvo = quantidade_g × fator`, e o bloco dela entra na lista antes do bloco da preparação que a usa (pós-ordem).
4. Por último, o bloco `"Montagem"` com as etapas da ficha de produto, se houver alguma.
5. Calcular a necessidade total por item em todos os blocos e definir `falta = max(0, total_item − saldo(item))` em **cada** linha desse item.

Nenhum arredondamento aqui.

- [ ] **Step 4: Rodar**

Run: `uv run pytest tests/test_escala.py -v`
Expected: PASS (8 casos).

- [ ] **Step 5: Commit**

```bash
git add fichas/escala.py tests/test_escala.py
git commit -m "feat: escala da receita em cascata com indicador de falta"
```

---

### Task 7: Telas de entrada de estoque e de receita escalada

**Files:**
- Create: `web/forms.py`, `web/templatetags/__init__.py`, `web/templatetags/formato.py`, `web/templates/web/entrada.html`, `web/templates/web/receita_form.html`, `web/templates/web/receita.html`
- Modify: `web/views.py`, `web/urls.py`, `web/templates/web/inicio.html`
- Test: `tests/test_web_receita.py`, `tests/test_formato.py`

**Interfaces:**
- Consumes: `entrada_manual` (Task 4), `escalar`, `ReceitaEscalada` (Task 6), `Ficha` (Task 5), `RegraViolada` (Task 2).
- Produces: URLs `entrada` (`/estoque/entrada/`) e `receita` (`/receita/`); filtro de template `quantidade` (`{{ linha.quantidade|quantidade:linha.unidade_base }}`).

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_formato.py
from decimal import Decimal as D
import pytest
from web.templatetags.formato import quantidade

@pytest.mark.parametrize("q,u,esperado", [
    (D("1800"), "g", "1,8 kg"), (D("4500"), "g", "4,5 kg"), (D("360"), "g", "360 g"),
    (D("157.5"), "g", "157,5 g"), (D("2700"), "mL", "2,7 L"), (D("90"), "mL", "90 mL"),
    (D("30"), "un", "30 un"), (D("1957.5"), "g", "1,958 kg"),
])
def test_quantidade(q, u, esperado):
    assert quantidade(q, u) == esperado
```

```python
# tests/test_web_receita.py
from decimal import Decimal as D
import pytest
from cadastros.models import Item
from estoque.models import Movimento
# reutiliza a fixture coxinha de tests/test_escala.py movida para conftest.py

pytestmark = pytest.mark.django_db

def test_gera_receita(client, dono, coxinha):
    r = client.get("/receita/", {"ficha": coxinha.id, "unidades": 50, "peso": "150"})
    html = r.content.decode()
    assert r.status_code == 200
    assert "7,5 kg" in html and "Recheio" in html and "Massa" in html
    assert html.index("Recheio") < html.index("Massa") < html.index("Empanamento")
    assert "falta 1,98 kg" in html   # frango sem estoque

@pytest.mark.parametrize("unidades,peso", [("0", "150"), ("50", "0"), ("-3", "150")])
def test_pedido_invalido_mostra_erro(client, dono, coxinha, unidades, peso):
    r = client.get("/receita/", {"ficha": coxinha.id, "unidades": unidades, "peso": peso})
    assert r.status_code == 200 and "maior que zero" in r.content.decode()

def test_entrada_duplo_envio_gera_um_movimento(client, dono):
    sal = Item.objects.create(nome="Sal", tipo="ingrediente", unidade_base="g", controla_validade=False)
    dados = {"item": sal.id, "quantidade": "1", "unidade": "kg", "custo_total": "3,50",
             "motivo": "estoque inicial", "chave": "form-abc"}
    client.post("/estoque/entrada/", dados)
    client.post("/estoque/entrada/", dados)
    assert Movimento.objects.count() == 1

def test_entrada_sem_fator_mostra_mensagem(client, dono):
    ovo = Item.objects.create(nome="Ovo", tipo="ingrediente", unidade_base="un", controla_validade=False)
    r = client.post("/estoque/entrada/", {"item": ovo.id, "quantidade": "1", "unidade": "dz",
                                          "custo_total": "10", "motivo": "x", "chave": "form-def"})
    assert "Cadastre o fator de 'dz' para 'Ovo'" in r.content.decode()
```

Antes, mover a fixture `coxinha` e os helpers `item`/`prep` de `tests/test_escala.py` para `conftest.py`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_formato.py tests/test_web_receita.py -v`
Expected: FAIL (filtro e URLs inexistentes).

- [ ] **Step 3: Implementar o filtro `quantidade(q: Decimal, unidade_base: str) -> str`**

Regras:
- `g` ≥ 1000 vira `kg`; `mL` ≥ 1000 vira `L`.
- No máximo 3 casas decimais, com arredondamento `ROUND_HALF_UP`, sem zeros à direita.
- Vírgula como separador decimal.
- `un` nunca muda de unidade.

- [ ] **Step 4: Implementar as views e os formulários**

- **`receita`** (GET, `@login_required`): `ReceitaForm` com `ficha` (só fichas `tipo="produto"` e `ativa`), `unidades` (inteiro) e `peso` (decimal com `localize=True`, aceita vírgula). Mensagem de erro de valor ≤ 0: `"Informe um valor maior que zero."`. Sem parâmetros, mostra só o formulário. Com dados válidos, chama `escalar` e renderiza `receita.html`.
- **`receita.html`:** no topo, o total do pedido formatado (ex.: "Total: 7,5 kg"). Abaixo, um bloco por preparação, na ordem, com o total do bloco. Cada linha tem `<input type="checkbox">` "separado" (só no navegador, sem gravar), o nome, a quantidade formatada e, se `falta > 0`, o texto `falta {{ falta|quantidade:unidade }}` em destaque. As etapas aparecem em lista ordenada com o tempo em minutos, quando houver.
- **`entrada`** (GET/POST, `@login_required`): `EntradaForm` (campos decimais com `localize=True`, para aceitar vírgula) com `item`, `quantidade`, `unidade` (texto livre com sugestões `g, kg, mL, L, un`), `custo_total`, `lote_codigo`, `validade`, `motivo` e `chave` oculta (`uuid4().hex` gerado no GET). O POST chama `entrada_manual(..., autor=request.user.username, canal="web", chave=form.cleaned_data["chave"])`. Uma `RegraViolada` vira erro do formulário com a mensagem. No sucesso, redireciona para `entrada` com mensagem `"Entrada registrada."`.
- **`inicio.html`:** links "Gerar receita", "Entrada de estoque" e "Cadastros" (admin).

- [ ] **Step 5: Rodar tudo**

Run: `uv run pytest -v`
Expected: PASS (todos os testes do projeto).

- [ ] **Step 6: Verificação manual no navegador**

Run: `uv run python manage.py migrate && uv run python manage.py createsuperuser && uv run python manage.py runserver 0.0.0.0:8000`

No admin, cadastre a ficha da coxinha do exemplo. Em `/receita/`, peça 50 × 150 g e confira:
- blocos na ordem Recheio → Massa → Empanamento → Montagem;
- os valores do esboço aprovado;
- o "falta" aparecendo;
- nenhuma rolagem horizontal com a janela em 360 px de largura.

- [ ] **Step 7: Commit**

```bash
git add web conftest.py tests
git commit -m "feat: telas de entrada de estoque e receita escalada"
```
