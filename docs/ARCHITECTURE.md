# Arquitetura

## Visão geral

```
┌───────────────────────────────────────────┐
│           ORQUESTRADOR DESKTOP             │
│           Tauri 2 + React/TypeScript       │
└───────────────────┬───────────────────────┘
                     │ invoke("bridge_invoke"/"bridge_status"/"bridge_reconnect")
                     ▼
┌───────────────────────────────────────────┐
│              SECURITY BRIDGE               │
│   allowlist de comandos (Rust + Python)    │
└───────────────────┬───────────────────────┘
                     │ stdio + JSON Lines, token de sessão
                     ▼
┌───────────────────────────────────────────┐
│             PYTHON ORCHESTRATOR            │
│                                             │
│  Intent Analyzer → Planner → Router        │
│  → Executor (DAG paralelo) → Verifier      │
│  → Aggregator → Reflection → Learning      │
│                                             │
│  Agents · Tools · Memory · Permission      │
│  Engine · Budget · Secret Store            │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┼────────┐
       ▼       ▼        ▼
    Claude   Gemini   OpenAI/Codex
               │
               ▼
         SQLite (WAL, migrations versionadas, backups)
```

Nenhuma camada pula a que está abaixo dela: o React nunca toca o sistema de
arquivos, git ou processos diretamente; o Rust nunca interpreta o conteúdo
de uma requisição além de rotear bytes; o Python nunca expõe uma operação
que não esteja na allowlist tipada (`core/security/allowlist.py
::BridgeCommand`).

## Camadas

### 1. Frontend (`desktop/src`)

React + TypeScript + Zustand + Tailwind/shadcn. Fala com o backend
exclusivamente através de `src/services/bridge.ts` (que chama os três
comandos Tauri) e dos módulos `src/services/api.ts` (chamadas tipadas em
cima disso). Cada página (`src/pages`) é isolada por um `ErrorBoundary`
(`src/components/ErrorBoundary.tsx`) para que uma falha de renderização não
derrube o app inteiro.

### 2. Bridge (Rust: `desktop/src-tauri/src/bridge`; Python: `core/bridge`)

- `manager.rs` possui o ciclo de vida do sidecar Python: inicia, faz stream
  do protocolo, detecta desconexão e reconecta com backoff exponencial
  limitado (`MAX_BACKOFF`). Se o sidecar cair repetidamente (mais de
  `MAX_RESTARTS_PER_WINDOW` vezes em `RESTART_WINDOW`), o supervisor para de
  tentar sozinho e reporta `BridgeStatus::Unavailable` até uma ação explícita
  do usuário (`reconnect_now`) — nunca fica preso em loop infinito de
  restart.
- `core/bridge/server.py` lê uma linha JSON por vez, valida contra
  `ALL_COMMANDS` e despacha para `core/bridge/handlers.py`.
- `core/bridge/context.py::build_context()` é o único lugar que constrói
  todo o grafo de dependências (repositories, providers, motor de
  orquestração, motor de aprendizado) — é também o seam de teste: qualquer
  teste que precise de um `BridgeContext` real usa esta função com
  `provider_overrides`/`secret_store` injetados.

### 3. Core de orquestração (`core/orchestrator`)

- **Intent Analyzer** classifica a tarefa em categorias, complexidade e
  risco (heurística determinística, nunca uma chamada de IA).
- **Planner** (`planner.py`) tenta, nesta ordem, para tarefas automáticas:
  (a) um **Playbook** correspondente (`core/learning/playbooks.py`), (b) um
  plano gerado por IA com *structured output* validado por schema
  (`AIPlanner`), (c) um plano baseado em regras determinísticas
  (`RuleBasedPlanner`) — sempre disponível, mesmo offline.
- **Router** (`router.py`) pontua candidatos por capacidade, disponibilidade,
  custo, histórico de sucesso verificado (`core/learning/model_performance
  .py`, amortecido para amostras pequenas) e regras aprendidas
  (`core/learning/rule_resolver.py`) — nunca uma tabela fixa.
- **Executor** (`executor.py`) roda o DAG do plano em camadas paralelas
  (`dag.py`), com retry/backoff só para erros transitórios, circuit breaker
  por provider e cancelamento cooperativo real.
- **Verifier** (`verifier.py`) roda checagens determinísticas (testes/lint/
  build reais via `CommandPlanner`) sempre antes de qualquer aspecto
  subjetivo — que é, por design, o próprio step de revisão gerado pelo
  Planner quando o risco é alto, não uma chamada oculta.
- **Aggregator** consolida custo, tokens e resultado final.
- **Reflection Engine / Learning Engine** (`core/learning`) analisam a
  execução (evidência determinística primeiro, IA só quando o custo da
  execução justificar) e transformam achados em candidatos de aprendizado
  com ciclo de vida completo (`candidate → observing → active →
  deprecated/rejected`).

### 4. Agentes e ferramentas (`core/agents`, `core/tools`)

Seis agentes padrão com permissões de mínimo privilégio
(`AgentPermissions`) e prompts versionados (`core/agents/prompt_registry
.py`). Toda ferramenta (arquivo, git, comando) passa pelo `Permission
Engine` (`core/security/permissions.py`) antes de executar — ver
`docs/SECURITY.md`.

### 5. Persistência (`core/database`)

SQLite em WAL mode, `busy_timeout`, `foreign_keys` ligado, migrations
versionadas e idempotentes (`core/database/migrations`), backup/restauração
online (`core/database/backup.py`) e checagens de integridade
(`quick_check` no startup, `integrity_check` completo sob demanda).

## Fluxo de uma tarefa automática

```
Task criada
  → Intent Analyzer (categoria, complexidade, risco)
  → Planner (playbook | IA | regras)
  → Router (uma decisão por step, com justificativa curta persistida)
  → Executor (DAG paralelo, ferramentas com Permission Engine, budget)
  → Verifier (determinístico; revisão por IA é um step comum quando o risco exige)
  → loop de correção limitado (nunca > max_review_iterations)
  → Aggregator (custo/tokens/resultado)
  → status final: completed | partial | failed (nunca "sucesso" sem verificação)
  → (em segundo plano, sem bloquear a resposta ao usuário)
    Reflection → Learning Candidates → Model Performance → Playbook feedback
```

## Por que a arquitetura não precisou ser recriada em nenhum estágio

Cada estágio adicionou uma camada sobre uma interface já estreita da
anterior, sem o consumidor de cima precisar saber da mudança:

- Trocar `MockProvider` por Claude/Gemini/OpenAI reais não mudou uma linha
  do `Executor`/`Router`/`ExecutionEngine` — só `ProviderAdapter`
  implementações novas registradas no `ProviderPool`.
- Adicionar Reflection/Learning não mudou o `Executor`; o
  `ExecutionEngine` apenas agenda `PostExecutionPipeline.process()` como uma
  tarefa em segundo plano depois que o resultado já foi entregue.
- Adicionar o Permission Engine não mudou a *forma* de `ToolExecutor
  .execute()` de fora — só a fonte da decisão de autorização passou de um
  `frozenset` plano para uma avaliação de risco.
