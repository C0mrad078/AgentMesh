# Orquestrador

**Orquestrador** é uma aplicação desktop multiplataforma (macOS e Windows, com
Linux preparado para o futuro) que atuará como um agente autônomo de
coordenação de múltiplas inteligências artificiais (Claude, Gemini,
Codex/OpenAI e outras).

Este repositório contém o **Estágio 1** do projeto: a fundação completa da
arquitetura — shell desktop, bridge, core de orquestração, banco de dados,
resiliência e interface — funcionando de ponta a ponta com **provedores de
IA mockados**. Nenhuma API de IA real está conectada ainda; o objetivo deste
estágio é ter uma base sólida, testada e segura antes de integrar provedores
reais no Estágio 2.

## Arquitetura

```
React (UI)
   │  invoke("bridge_invoke" | "bridge_status" | "bridge_reconnect")
   ▼
Tauri (Rust) — desktop/src-tauri
   │  spawn + stdin/stdout JSON-lines (ver "Decisão: protocolo do bridge")
   ▼
Bridge (Python) — core/bridge
   │  allowlist de comandos → handlers → serviços
   ▼
Python Core — core/{orchestrator,agents,providers,tasks,projects,memory,tools,security}
   │
   ▼
SQLite — core/database (migrations versionadas, repositories tipados)
```

- **React** (`desktop/src`) é a única camada que o usuário vê. Ela nunca fala
  diretamente com o sistema de arquivos, git ou processos — apenas chama os
  três comandos Tauri expostos (`bridge_invoke`, `bridge_status`,
  `bridge_reconnect`) e escuta dois eventos (`orchestrator://status`,
  `orchestrator://event`).
- **Tauri/Rust** (`desktop/src-tauri`) é dono do ciclo de vida do sidecar
  Python: inicia, reinicia com backoff quando cai, e é a única camada que
  sabe como o processo Python é resolvido em cada plataforma
  (`bridge/process.rs`).
- **Bridge** (`core/bridge`) é o protocolo e a allowlist: todo comando que
  atravessa a fronteira Tauri↔Python precisa existir em
  `core/security/allowlist.py::BridgeCommand`. Não existe um comando
  genérico de "execute isso".
- **Core Python** (`core/orchestrator`, `core/agents`, `core/providers`,
  `core/tasks`, `core/projects`, `core/memory`, `core/tools`,
  `core/security`) implementa o pipeline de execução:
  `Intent Analyzer → Planner → Router → Executor → Verifier → Result Aggregator`.
- **SQLite** (`core/database`) é a única fonte de persistência, acessada
  exclusivamente através de repositories tipados — não há SQL espalhado
  pela aplicação.

### Decisão: protocolo do bridge (Tauri ↔ Python)

O sidecar Python é controlado pelo processo Tauri e conversa com ele por
**stdin/stdout, com mensagens JSON delimitadas por linha** (JSON Lines),
nunca por texto de shell arbitrário. As alternativas consideradas foram:

- **IPC nativo (named pipes / Unix sockets)**: exigiria duas implementações
  completamente diferentes (POSIX vs. Windows) para o mesmo resultado que
  stdio já dá de graça em ambas as plataformas.
- **HTTP/TCP em localhost**: exige gerenciar uma porta (conflitos, escolha
  dinâmica) e abre um listener local que, sem trabalho extra, qualquer
  processo da máquina poderia tentar acessar.

`stdio` é inerentemente 1:1 entre pai e filho (nenhum outro processo lê/escreve
nesses descritores sem privilégios de depuração), não exige porta, e é o
padrão em torno do qual as próprias APIs de sidecar do Tauri são desenhadas.
Um **token de sessão** trocado no handshake inicial (mensagem `hello`) adiciona
uma camada extra de verificação de identidade, e mantém o protocolo pronto
para, no futuro, trocar de transporte sem afetar o payload das mensagens.

O protocolo completo está documentado em `core/bridge/protocol.py` (lado
Python) e `desktop/src-tauri/src/bridge/protocol.rs` (lado Rust) — os dois
arquivos existem para manter os tipos explícitos em cada linguagem; o Python
é a fonte de verdade sobre *quais* comandos existem
(`core/security/allowlist.py`).

### Decisão: sem servidor de shell/execução genérico

Não existe, em nenhum lugar do código, uma função que receba uma string e a
execute como comando de shell. `core/tools/git_tool.py` e
`core/tools/terminal_tool.py` só expõem operações fixas e tipadas (ex.:
`GitTool.status()`, `TerminalCommand.PYTHON_VERSION`), sempre executadas via
`asyncio.create_subprocess_exec` (vetor de argumentos, nunca uma string de
shell) através da abstração central `core/utils/shell_runner.py`.

### Decisão: caminhos e plataforma centralizados

Toda detecção de sistema operacional passa por `core/utils/platform.py`
(Python) e `desktop/src-tauri/src/bridge/process.rs` (Rust, apenas para
resolver o comando do sidecar). Nenhum outro módulo chama `platform.system()`,
`sys.platform`, `cfg!(target_os = ...)` ou monta caminhos absolutos
manualmente. Diretórios de dados/log usam `platformdirs`, que resolve para o
local correto em cada SO (`~/Library/...` no macOS, `%APPDATA%` no Windows).

### Modelo de dados

Tabelas (todas criadas via migration versionada, `core/database/migrations/versions/0001_initial.sql`):
`settings`, `projects`, `conversations`, `messages`, `agents`, `tasks`,
`executions`, `execution_steps`, `provider_configs`, `prompt_versions`,
`learned_rules`, `project_memories`, `audit_logs`. Os schemas incluem colunas
que o Estágio 1 ainda não usa totalmente (ex.: `provider_configs.secret_ref`)
para que o Estágio 2+ não precise de migrations destrutivas.

### Motor de execução

```
Tarefa criada
     │
     ▼
Intent Analyzer   (core/orchestrator/intent_analyzer.py — baseado em regras/keywords)
     │
     ▼
Planner           (core/orchestrator/planner.py — gera um ExecutionPlan)
     │
     ▼
Router            (core/orchestrator/router.py — escolhe o agente por capability)
     │
     ▼
Executor          (core/orchestrator/executor.py — retry+backoff+timeout+cancelamento reais)
     │
     ▼
Verifier          (core/orchestrator/verifier.py)
     │
     ▼
Result Aggregator (core/orchestrator/aggregator.py)
```

Cada uma dessas 6 fases vira uma linha em `execution_steps` e é transmitida
ao frontend em tempo real via evento `orchestrator://event`
(`execution.progress`), o que alimenta o quadro de progresso da interface.

### MockProvider

`core/providers/mock_provider.py` simula seis cenários reais, selecionáveis
via `task.input.scenario`: `success`, `latency`, `retry_then_success`,
`persistent_error`, `timeout`, `invalid_response`. Isso permite testar todo o
Executor (retry/backoff/timeout/cancelamento) sem depender de uma API real.

## Requisitos de desenvolvimento

### macOS

- macOS 13+
- [Rust](https://www.rust-lang.org/tools/install) (via `rustup`, profile `default`, que já inclui `cargo`, `clippy`, `rustfmt`)
- Node.js 20+ e npm
- Python 3.12+ (o repositório foi validado com 3.13)
- Xcode Command Line Tools (`xcode-select --install`) — exigido pelo Tauri

### Windows

- Windows 10/11
- [Rust](https://www.rust-lang.org/tools/install) (via `rustup-init.exe`)
- [Microsoft Visual C++ Build Tools](https://tauri.app/start/prerequisites/#windows) (exigido pelo Tauri para compilar o shell nativo)
- [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/) (já vem instalado no Windows 11; no Windows 10 pode exigir instalação manual)
- Node.js 20+ e npm
- Python 3.12+

> O usuário final da versão distribuída **não precisa instalar** Python,
> Node ou Rust — esses requisitos são apenas para desenvolvimento. A
> distribuição em produção empacota o core Python como um binário
> autocontido (ver "Limitações conhecidas").

## Setup

```bash
# macOS / Linux
./scripts/setup.sh

# Windows (PowerShell)
./scripts/setup.ps1
```

Isso cria o virtualenv (`.venv`) na raiz do repositório, instala as
dependências Python (`core/`, modo editável) e as dependências npm de
`desktop/`.

## Executando em desenvolvimento

```bash
# macOS / Linux
./scripts/dev.sh

# Windows (PowerShell)
./scripts/dev.ps1
```

Isso roda `npm run tauri dev` dentro de `desktop/`, que sobe o Vite (frontend)
e compila/roda o binário Tauri, que por sua vez inicia o sidecar Python
automaticamente usando o Python do `.venv` (ver
`desktop/src-tauri/src/bridge/process.rs`).

Variáveis de ambiente úteis para desenvolvimento/CI:

- `ORCH_PYTHON_BIN`: força qual interpretador Python o Tauri deve usar para o
  sidecar (em vez de procurar `.venv`).
- `ORCH_CORE_CWD`: força o diretório de trabalho a partir do qual o sidecar é
  iniciado (em vez de inferir a raiz do repositório).
- `ORCH_DATA_DIR`: força o diretório de dados/banco/log do core (usado pelos
  testes de integração e smoke, para nunca tocar os dados reais do usuário).

## Testes

Rode tudo de uma vez (mesma ordem usada no quality gate deste estágio):

```bash
./scripts/test.sh      # macOS / Linux
./scripts/test.ps1      # Windows
```

Ou individualmente:

```bash
# Python: lint, tipos, testes unitários + integração + smoke
.venv/bin/ruff check core tests
.venv/bin/mypy core
.venv/bin/python -m pytest tests/python tests/integration tests/smoke

# Frontend: tipos, lint, testes, build
cd desktop
npm run typecheck
npm run lint
npm run test
npm run build

# Rust: formatação, lint, testes
cd desktop/src-tauri
cargo fmt -- --check
cargo clippy --all-targets -- -D warnings
cargo test
```

### O que cada suíte cobre

- **`tests/python/`** — banco/migrations, repositories, projetos, lifecycle
  de tasks (todas as transições válidas/inválidas), `MockProvider` (todos os
  6 cenários), `Executor` (retry, timeout real, cancelamento real), path
  traversal, `GitTool`/`TerminalTool`, protocolo do bridge (serialização,
  erro, comando desconhecido, token inválido).
- **`tests/integration/`** — o pipeline completo (Intent → Planner → Router →
  Executor → Verifier → Aggregator) rodando contra um SQLite real, incluindo
  persistência sobrevivendo a fechar/reabrir o banco, e cancelamento real de
  uma execução em andamento.
- **`tests/smoke/`** — sobe o sidecar Python **real** (mesmo processo que o
  Tauri spawna) e conversa com ele pelo protocolo JSON-lines real: cria
  projeto → cria tarefa → inicia execução → aguarda o `MockProvider`
  responder → confirma resultado → fecha o processo → abre um processo novo
  apontando para o mesmo diretório de dados → confirma que o histórico
  continua disponível. Também cobre requisição inválida, comando
  desconhecido e token de sessão incorreto.
- **`desktop/src/**/__tests__`** — Vitest + Testing Library cobrindo o fluxo
  principal do frontend: quadro de progresso (`StepBoard`), status de conexão
  (`useConnectionStatus`), criação de projeto (`NewProjectDialog`, incluindo
  validação), e os estados vazio/preenchido da tela de tarefas
  (`WorkspacePage`).
- **`desktop/src-tauri/src/bridge/{protocol,process}.rs`** — testes `#[test]`
  cobrindo serialização/deserialização de cada tipo de mensagem (`hello`,
  `response` de sucesso e de erro, `event`, tipo desconhecido, JSON malformado)
  e a resolução do comando do sidecar por plataforma.

## Build

```bash
cd desktop
npm run build          # build de produção do frontend (Vite)
npm run tauri build    # build completo do aplicativo desktop (requer Rust)
```

`npm run tauri build` gera o instalador nativo (`.app`/`.dmg` no macOS,
`.exe`/`.msi` no Windows) com o frontend compilado embutido. **O
empacotamento do sidecar Python como binário autocontido (PyInstaller +
`externalBin` no `tauri.conf.json`) ainda não foi implementado neste
estágio** — ver "Limitações conhecidas" abaixo.

## Estrutura do repositório

```
orquestrador/
├── desktop/                 # Shell Tauri 2 + frontend React
│   ├── src/                 # React (components, pages, layouts, hooks, stores, services, types)
│   └── src-tauri/           # Rust: bridge com o sidecar Python, comandos Tauri, config
├── core/                    # Core Python do orquestrador
│   ├── orchestrator/        # Intent Analyzer, Planner, Router, Executor, Verifier, Aggregator
│   ├── agents/               # Modelo de agente + registry (mockado)
│   ├── providers/            # ProviderAdapter (contrato) + MockProvider
│   ├── tasks/                 # Lifecycle de tasks (state machine)
│   ├── projects/              # Projetos locais
│   ├── memory/                 # Contrato de memória + implementação SQLite
│   ├── database/               # Conexão, migrations versionadas, repositories
│   ├── tools/                   # Filesystem/Git/Terminal tools (sandboxed)
│   ├── security/                 # Allowlist do bridge, SecretStore, audit log
│   ├── bridge/                    # Protocolo, servidor, handlers, entrypoint do sidecar
│   └── utils/                      # Plataforma, logging, erros, shell runner
├── tests/
│   ├── python/                # Testes unitários do core
│   ├── integration/           # Pipeline completo contra SQLite real
│   └── smoke/                 # Sidecar real, protocolo real, fim a fim
├── scripts/                   # setup/dev/test para macOS e Windows
├── docs/                      # Decisões arquiteturais detalhadas
└── README.md
```

## Decisões arquiteturais importantes

Ver [`docs/decisions.md`](docs/decisions.md) para o registro completo. Resumo
das que mais afetam os próximos estágios:

1. **Bridge por stdio + JSON Lines**, com token de sessão — não HTTP, não IPC
   nativo (ver acima).
2. **Allowlist única em Python** (`BridgeCommand`) como fonte de verdade de
   quais operações existem; Rust nunca decide isso, só encaminha.
3. **Sem shell genérico**: toda operação de filesystem/git/terminal é um
   método tipado, nunca uma string executada.
4. **Schemas de banco propositalmente mais largos** que o uso atual, para que
   o Estágio 2 (providers reais, aprendizado, multi-agente) só precise de
   migrations aditivas.
5. **Motor de execução com 6 fases fixas** (Intent → Plan → Route → Execute →
   Verify → Aggregate), cada uma como uma linha persistida e um evento —
   pronto para que o Planner e o Router do Estágio 2 sejam trocados por
   versões orientadas a IA sem mudar o restante do pipeline.
6. **Cancelamento real**: `asyncio.Event` propagado até dentro da chamada ao
   provider, que é de fato cancelada (`Task.cancel()` + `provider.cancel()`),
   não apenas ignorada pela UI.
7. **Recuperação de crash no startup**: qualquer task/execution presa em
   estado não-terminal ao iniciar o app é marcada `failed` de forma
   determinística — nunca fica presa nem "continua" silenciosamente.

## Limitações conhecidas

Estas limitações são reais e deliberadas para o escopo do Estágio 1 — não
foram escondidas:

1. **Empacotamento de produção do sidecar Python não implementado.** Em
   desenvolvimento, o Tauri inicia o Python do `.venv` do próprio
   repositório. Para uma build distribuível onde o usuário final não tem
   Python instalado, o plano (documentado em
   `desktop/src-tauri/src/bridge/process.rs`) é congelar `core/` com
   PyInstaller em um binário único e registrá-lo como `externalBin` no
   `tauri.conf.json`. Isso é trabalho de empacotamento do Estágio 2+, não
   afeta a arquitetura, e o `tauri.conf.json` já tem o campo `externalBin`
   reservado para isso.
2. **Fluxo de clique-a-clique na janela nativa não foi automatizado.** Não há
   ferramenta de automação de UI nativa disponível neste ambiente de
   desenvolvimento. Em vez disso, o fluxo completo foi validado de duas
   formas complementares: (a) rodando o app real (`tauri dev`) e confirmando
   nos logs que o handshake Rust↔Python e a conexão acontecem de verdade; e
   (b) o smoke test em `tests/smoke/test_end_to_end_sidecar.py`, que fala o
   protocolo real com o processo Python real (o mesmo que o Tauri spawna) e
   cobre o fluxo completo ponta a ponta, incluindo fechar/reabrir o banco.
   A lógica de frontend (estados, formulários, quadro de progresso) tem
   cobertura unitária própria (Vitest) mockando apenas a fronteira do Tauri.
3. **Modos Manual, Pipeline, Debate e Consenso são placeholders** na
   interface (aparecem desabilitados com indicação de "próximo estágio") —
   apenas o modo Automático está funcional, como pedido para este estágio.
4. **Repositories de `provider_configs`, `prompt_versions` e `learned_rules`**
   ainda não foram implementados (as tabelas existem via migration, prontas
   para uso) porque nada no Estágio 1 os exercita; serão adicionados quando o
   Estágio 2 precisar deles.
5. **Migrations SQL não são 100% atômicas por statement** dentro de um mesmo
   arquivo — `executescript` do SQLite aplica DDL de forma efetivamente
   transacional na prática, mas não há um `BEGIN`/`COMMIT` explícito por
   arquivo de migration. Suficiente para o schema atual (só DDL), mas vale
   revisar se migrations futuras misturarem DDL com DML sensível.

## Preparação para o Estágio 2

A arquitetura já está pronta para receber, sem redesenho:

- **Claude / Gemini / Codex-OpenAI**: basta implementar `ProviderAdapter`
  (`core/providers/base.py`) para cada um e registrá-los — nada no
  `Executor`, `Router` ou `ExecutionEngine` conhece o `MockProvider`
  especificamente.
- **Router e Planner orientados por IA**: `IntentAnalyzer`, `Planner` e
  `Router` já são classes isoladas com uma interface estreita; trocar a
  implementação baseada em regras por uma baseada em LLM não exige mudar o
  `ExecutionEngine`.
- **Agentes especializados**: `core/agents/models.py` já modela
  capabilities, tools, permissions e config por agente; falta apenas
  popular `AgentRegistry` a partir do banco em vez de uma lista fixa.
- **Controle de custo**: `provider_configs` e o próprio `ProviderResult`
  (`tokens_used`) já carregam os campos necessários para agregação de custo.
- **Execução multi-modelo**: o `ExecutionPlan` já suporta múltiplos
  `PlanStep`, cada um roteado independentemente — o Estágio 1 só usa um passo
  por simplicidade, não por limitação da estrutura.
