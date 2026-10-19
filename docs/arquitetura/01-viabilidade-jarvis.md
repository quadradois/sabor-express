# Análise de viabilidade — Jarvis como sistema × Jarvis como usuário do sistema

**Data:** 19/10/2026 · **Status:** recomendação para decisão do proprietário
**Base:** PVD v1.1, PRD v1.0 (RF-EXT-01 a 04, DEC-F2-002) e leitura do código de `omnigentx/jarvis` (commit `bba84b2`, de 17/10/2026)

## 1. A pergunta

- **Opção A — o Jarvis é o sistema:** partir do repositório do Jarvis e construir dentro dele o sistema de gestão de salgados (cadastros, estoque, produção, custos e financeiro).
- **Opção B — o Jarvis é usuário do sistema:** construir o sistema de salgados como um núcleo independente, que expõe as suas operações por MCP. O Jarvis, ou outro agente, se conecta a ele e opera como um usuário.

## 2. O que o código do Jarvis mostra (fatos)

| Aspecto | Achado |
|---|---|
| Tamanho | Cerca de 110 mil linhas de código (Python + Vue), sem contar os testes |
| Autoria | Praticamente um autor (cerca de 267 de 274 commits recentes) e desenvolvimento ativo (último commit em 17/10/2026) |
| Stack | Backend FastAPI + fast-agent, frontend Vue 3, SQLite e 7 serviços no Docker Compose |
| Escopo | Equipes de agentes, spawn de subagentes, e-mail entre agentes, memória e recuperação de contexto, integrações com Gmail, Calendar, Figma, Atlassian, IoT e outras |
| Ferramentas | Cada ferramenta é um servidor MCP (`FastMCP`). Conectar um servidor externo exige **uma entrada de poucas linhas** em `fastagent.config.yaml` (comando e argumentos) |
| Aprovação humana | Já existe um padrão de "pedir aprovação" (`approval_server.py`), útil para confirmar ações por voz |
| Idioma | Reconhecimento de fala com idioma "auto". Os padrões são vietnamitas (fuso Asia/Ho_Chi_Minh, motor de voz vi). Português não é mencionado e precisa de teste |

## 3. Comparação

| Critério | A — Jarvis é o sistema | B — Jarvis é usuário |
|---|---|---|
| **Tempo até o MVP de gestão** | Pior. É preciso entender e adaptar 110 mil linhas antes da primeira tela de estoque | Melhor. O núcleo pequeno começa vazio e cresce só com o que o PRD pede |
| **Simplicidade** | Pior. Herda equipes de agentes, e-mail entre agentes e 7 serviços que o projeto não usa | Melhor. Só o necessário |
| **Integridade de estoque e dinheiro** | Risco. O agente e as regras de negócio dividem o mesmo processo e o mesmo banco, o que facilita gravar "por fora" das regras. O PRD exige o contrário (RF-EXT-01, DEC-F2-002) | Forte. Toda gravação passa pelas operações do núcleo, venha da tela ou da voz |
| **Atualizações do Jarvis** | Ruim. Um fork de projeto ativo diverge rápido: ou você para de receber melhorias, ou resolve conflitos a cada atualização | Bom. O Jarvis fica intocado e é atualizado normalmente |
| **Dependência de um projeto de um autor só** | Alta. Se o projeto parar, o seu sistema fica preso a ele | Baixa. Trocar de agente não mexe no sistema |
| **Experiência de voz** | Ligeiramente melhor no início, porque o agente "enxerga tudo" | Igual na prática. O agente faz o que as ferramentas MCP oferecem, e elas são desenhadas para as tarefas da cozinha |
| **Funciona sem o agente** | Não. Desligar o Jarvis derruba o sistema | Sim. O MVP inteiro funciona sem voz, como o PRD exige |
| **Infraestrutura para rodar** | Um conjunto só, mas pesado (7 serviços Docker) | Dois conjuntos: o núcleo leve e o Jarvis, ligado só quando for usado |
| **Trabalho extra** | Remover ou ignorar o que não serve; adaptar o banco | Escrever o servidor MCP do núcleo, uma camada fina sobre as operações que já existem (RF-EXT) |
| **Aderência ao PVD e ao PRD** | Conflita com a ordem das fases (voz depois do MVP), com a simplicidade e com RF-EXT | Total |

## 4. Recomendação

**Opção B: o Jarvis é usuário do sistema.**

A vantagem real da opção A, aproveitar infraestrutura pronta, cobre a parte que menos importa: login, tela e Docker são simples de ter. O preço é alto justamente no que mais importa: a integridade dos dados, a simplicidade e a independência de um projeto de terceiros.

O encaixe pela opção B é barato e o código confirmou isso: o Jarvis já trata toda ferramenta como servidor MCP, e conectar uma nova é uma entrada de configuração.

**Quando a opção A faria sentido:** se a voz fosse a interface principal desde o primeiro dia e o sistema tivesse pouca regra de negócio. Não é o caso aqui.

## 5. Consequências para o MVP

1. O núcleo implementa as operações de domínio (já previstas em RF-EXT-01 a 03).
2. Depois do MVP, um **servidor MCP do Sabor Express** expõe ferramentas pensadas para a cozinha (gerar receita escalada, próxima etapa, cronômetro, registrar peso, concluir produção, consultar estoque e validade), com níveis de confirmação.
3. O Jarvis recebe uma "persona de cozinha" em português, configurada por skills ou prompts, **sem fork do código**.
4. Antes de adotar o Jarvis, testar português (reconhecimento e voz), latência e ruído de cozinha. Se não atender, trocar de agente sem mexer no núcleo.
