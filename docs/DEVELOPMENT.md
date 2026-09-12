# Desenvolvimento

Para requisitos de sistema, setup inicial e como rodar em modo
desenvolvimento, veja as seções "Requisitos de desenvolvimento", "Setup" e
"Executando em desenvolvimento" no `README.md` — este documento cobre o que
falta: como navegar o código, os fluxos comuns de contribuição e como
depurar.

## Onde encontrar as coisas

```
core/orchestrator/   Intent Analyzer, Planner, Router, Executor, Verifier,
                      Aggregator, DAG, orçamento, engine principal
core/agents/         Definição dos 6 agentes padrão e Prompt Registry
core/providers/      Adapters Claude/Gemini/OpenAI + MockProvider + registry
core/tools/          Filesystem/Git/Search/Terminal/CommandPlanner tools
core/security/       Permission Engine, allowlist do bridge, secret store/scanner, audit
core/learning/       Reflection Engine, Learning Engine, playbooks, memory-adjacent
core/database/       Conexão, migrations versionadas, repositories, backup
core/bridge/         Protocolo, contexto (build_context), handlers, allowlist
desktop/src/         React (páginas, componentes, stores Zustand, services)
desktop/src-tauri/   Rust: gerência do sidecar, protocolo, empacotamento
tests/python/        Testes unitários do core
tests/integration/   Pipeline completo contra SQLite real
tests/smoke/         Processo Python real, protocolo real
docs/                Esta pasta
```

## Rodando os testes durante o desenvolvimento

```bash
# um arquivo específico
.venv/bin/python -m pytest tests/python/test_router.py -v

# um teste específico
.venv/bin/python -m pytest tests/python/test_router.py::test_router_prefers_the_agent_with_a_better_verified_track_record -v

# frontend, um arquivo
cd desktop && npx vitest run src/pages/__tests__/LearningPage.test.tsx
```

O quality gate completo (`./scripts/test.sh`) roda tudo na mesma ordem do
CI; rode-o antes de abrir um PR.

## Fluxos comuns

### Adicionar uma nova ferramenta que um agente pode chamar

1. Implemente o método real no tool wrapper apropriado
   (`core/tools/filesystem_tool.py`, `git_tool.py`, ...), sempre passando
   por `resolve_safe_path`/`GitTool._run` — nunca uma chamada de subprocesso
   direta.
2. Classifique o risco em `core/security/permissions.py::OPERATION_RISK` e,
   se necessário, o requisito de capacidade em `_CAPABILITY_FLAG`.
3. Adicione o `ToolSchema` e o `if name == "..."` correspondente em
   `core/tools/tool_schemas.py::ToolExecutor._dispatch`.
4. Adicione o nome da ferramenta ao `tools=[...]` dos agentes que devem
   poder usá-la (`core/agents/registry.py`) — lembre-se que
   `_IMPLIED_BY_CAPABILITY_ALONE` já cobre leituras de baixo risco.
5. Teste: permissão negada sem a flag, permissão negada sem estar em
   `agent.tools`, `require_confirmation` para risco alto sem
   pré-autorização, sucesso com pré-autorização.

### Adicionar um novo provider de IA

1. Implemente `ProviderAdapter` (`core/providers/base.py`) em cima de
   `HttpProviderAdapter` (`core/providers/http_provider.py`), mapeando
   erros HTTP para as exceções normalizadas (`core/utils/errors.py`).
2. Adicione os modelos padrão em `core/providers/registry.py::DEFAULT_MODELS`
   (nunca um nome de modelo hardcoded em outro lugar).
3. Adicione o provider a `SUPPORTED_PROVIDERS`
   (`core/providers/credentials.py`) e a `build_adapter`.
4. Teste com `respx` mockando a API HTTP (veja
   `tests/python/test_anthropic_provider.py` como referência) — sucesso,
   401, 429 com `Retry-After`, 500, timeout, resposta malformada.
5. **Nunca** rode um teste contra a API real por padrão — testes "live"
   ficam atrás de `RUN_LIVE_AI_TESTS=true`.

### Adicionar uma nova regra de aprendizado ou playbook seed

Regras aprendidas nunca são escritas diretamente no banco por um
desenvolvedor — elas nascem de `core/learning/learning_engine.py
::LearningEngine.process_candidate`. Para adicionar um **playbook seed**
(uma estratégia pré-conhecida, não aprendida), edite
`core/learning/playbooks.py::_SEED_PLAYBOOKS`.

## Depuração

- **Logs do core**: `core/utils/logging.py` escreve para `stderr` e um
  arquivo rotacionado (nunca `stdout`, reservado ao protocolo). Em
  desenvolvimento, o Tauri encaminha o `stderr` do sidecar para o log do
  Rust (`log::debug!(target: "orchestrator-core", ...)`).
- **Eventos em tempo real**: o frontend expõe todo evento de orquestração
  (`agent.selected`, `tool.completed`, `reflection.completed`, ...) — veja
  `useBridgeSubscription` e o inspetor de execução em `ExecutionsPage`
  ("Ver detalhes técnicos").
- **Estado do bridge**: `BridgeStatus` (`initializing`/`connected`/
  `reconnecting`/`offline`/`unavailable`/`error`) é visível na UI e nos
  logs do Rust (`bridge status -> ...`).
- **Banco de dados**: abra o arquivo SQLite diretamente com qualquer cliente
  (`sqlite3 ~/Library/Application Support/.../orchestrator.db` no macOS) —
  é texto simples, sem criptografia proprietária.

## Convenções

- Nenhuma string SQL fora de `core/database/repositories/`.
- Nenhuma *definição* de modelo (custo, contexto, capacidades) fora de
  `core/providers/registry.py::DEFAULT_MODELS` — outros lugares (como o
  `model=` preferido de cada agente em `core/agents/registry.py`) podem
  referenciar um `model_id` que já exista lá, nunca inventar um novo.
- Nenhuma chamada de subprocesso fora de `core/utils/shell_runner.py`
  (usada por `GitTool`, `TerminalTool`, `CommandPlanner`).
- Comentários explicam *por quê*, não *o quê* — o nome das funções já diz o
  quê.
- Todo bug corrigido ganha um teste de regressão no mesmo commit.
