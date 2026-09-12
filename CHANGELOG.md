# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento em [SemVer](https://semver.org/lang/pt-BR/). Nenhuma versão
com tag foi publicada ainda — este arquivo documenta o trabalho por
estágio de desenvolvimento até aqui.

## [Não lançado] — Pós-Estágio 4: correções de uma auditoria independente

Uma análise independente do repositório (`docs/RELATORIO_ANALISE_PROJETO.md`)
encontrou defeitos reais que a suíte de testes do Estágio 4 não cobria.
Verificados e corrigidos nesta passagem:

### Corrigido

- **Segurança (alta prioridade):** a saída de chamadas de ferramenta
  (`ReadFile`/`SearchFiles`/...) era enviada ao provider de IA como
  mensagem `TOOL` sem passar pelo `SecretScanner` -- diferente do que
  `docs/SECURITY.md` já afirmava valer para todo conteúdo de projeto. Um
  arquivo lido por um agente podia carregar uma credencial até a API
  externa. Corrigido em `core/orchestrator/executor.py`
  (`StepExecutor._secret_scanner`); regressão coberta por
  `test_executor_redacts_secrets_in_tool_output_before_sending_to_the_provider`.
- **`SearchTool` (`core/tools/search_tool.py`):** o caminho via `ripgrep`
  não aplicava os mesmos `DEFAULT_IGNORE_PATTERNS` do fallback Python (uma
  `node_modules/` sem `.gitignore` explícito vazava para os resultados),
  não normalizava o prefixo `./` que `rg` inclui, e usava correspondência
  sensível a maiúsculas enquanto o fallback é insensível -- o mesmo termo
  de busca podia se comportar de forma diferente dependendo apenas de
  `rg` estar instalado na máquina. Corrigido com `--glob`/`--ignore-case`
  explícitos e normalização do caminho; regressão coberta por dois novos
  testes em `tests/python/test_search_tool.py`.
- **Smoke test (`tests/smoke/test_end_to_end_sidecar.py`):** o cliente de
  teste lia a saída do sidecar com `Popen.stdout.readline()` bloqueante
  dentro de um laço com prazo -- o prazo só era checado entre chamadas,
  nunca durante uma, então um sidecar silencioso travava o teste
  indefinidamente em vez de falhar após o timeout configurado. Corrigido
  com uma thread leitora alimentando uma `Queue` (`Queue.get(timeout=...)`
  é um timeout real); regressão coberta por
  `test_read_message_enforces_a_real_timeout_when_the_sidecar_writes_nothing`.
- **Rust/Tauri estava incorretamente marcado como não verificável:** o
  toolchain `cargo`/`rustc` está de fato instalado nesta máquina (só não
  estava no `PATH` das sessões de shell usadas durante o Estágio 4) --
  `cargo check`/`test`/`clippy`/`fmt` rodam e passam, e `npm run tauri dev`
  abre a janela nativa real com o sidecar Python conectado. Também achou
  uma violação de formatação genuína (`cargo fmt --check`) em
  `desktop/src-tauri/src/bridge/manager.rs`, existente desde o Estágio 1 e
  nunca antes detectada porque `cargo fmt` nunca tinha rodado de verdade
  neste projeto -- corrigida (mudança só de formatação). `README.md` e
  `docs/BUILD.md` foram corrigidos para não afirmarem mais que o
  toolchain Rust está ausente.
- **`README.md`:** removida a alegação de versão "v1.0", que não batia com
  a versão real dos pacotes (`0.1.0` em `package.json`/`Cargo.toml`/
  `pyproject.toml`).

### Conhecido, ainda não corrigido

A mesma análise levantou outros pontos reais que não foram corrigidos
nesta passagem (escopo/tempo) -- ver `docs/RELATORIO_ANALISE_PROJETO.md`
seção 8 para o texto completo com evidências: `budget.py` não reserva
custo de chamadas em voo (só confere gasto já registrado); Planner/Judge/
Reflection chamam `provider.execute` diretamente, fora do `StepExecutor`,
então não têm orçamento/métricas/cancelamento uniformes; o adapter OpenAI
não reconstrói `tool_calls` na mensagem `ASSISTANT` antes de um resultado
de ferramenta; `tauri.conf.json` tem `externalBin: []` (sem empacotamento
real do sidecar ainda) e `app.security.csp` nulo; `_steps_from_plan_data()`
descarta dependências desconhecidas antes de validar o grafo; a revisão
adicional de alto risco não é imposta uniformemente a planos vindos de
IA/regras/playbook; o Verifier omite silenciosamente verificações sem
comando reconhecido; cancelamento não se propaga ao `ShellRunner`/
`CommandPlanner`; `pip-audit`/`npm audit` continuam `|| true` no CI; e
`quick_integrity_check()` existe mas não está de fato no caminho de
startup (`build_context()`), apesar da documentação sugerir que sim.

## [Não lançado] — Estágio 4: Hardening, produção, sandbox e empacotamento

### Adicionado

- Permission Engine / Risk Engine (`core/security/permissions.py`):
  classificação de risco fixa por operação (low/medium/high/critical/
  forbidden), avaliação default-deny, exigência de confirmação para
  operações de risco alto/crítico.
- Escritas de arquivo atômicas (temp file + `fsync` + `os.replace`) com
  backup automático de arquivo único antes de sobrescrever/excluir
  (`core/tools/filesystem_tool.py`).
- `GitTool` com camadas de operação somente-leitura, mutável e destrutiva,
  defesa contra injeção de flag em nomes de branch/revisão
  (`core/tools/git_tool.py`).
- `ShellRunner` com ambiente mínimo explícito, limite de tamanho de saída,
  término de árvore de processos completa e cancelamento cooperativo
  (`core/utils/shell_runner.py`).
- Backup/restauração online de banco de dados via API nativa do SQLite,
  autoverificado e com retenção (`core/database/backup.py`), exposto na UI
  em Configurações → Dados (`DataManagementSettings.tsx`).
- `busy_timeout` e checagens de integridade rápida/completa no banco
  (`core/database/connection.py`).
- Estado de recuperação de execução (`RecoveryState`) após falha/crash
  (`core/orchestrator/recovery.py`).
- Política de reinício com limite (máx. 3 em 5 minutos, depois
  `BridgeStatus::Unavailable` até ação explícita do usuário) no supervisor
  do sidecar (`desktop/src-tauri/src/bridge/manager.rs`).
- `ErrorBoundary` do React isolando cada página contra falhas de
  renderização (`desktop/src/components/ErrorBoundary.tsx`).
- Pipeline de CI (`.github/workflows/ci.yml`): lint/typecheck/testes
  multiplataforma para Python, frontend e Rust, mais varredura de segredos
  (gitleaks) e auditoria de dependências.
- Documentação: `docs/ARCHITECTURE.md`, `docs/SECURITY.md`,
  `docs/DEVELOPMENT.md`, `docs/BUILD.md`, `docs/RELEASE.md`.
- ~60 novos testes automatizados cobrindo o hardening acima.

### Modificado

- `ToolExecutor.execute()` agora recebe `agent=` e consulta o Permission
  Engine para toda chamada de ferramenta, substituindo a checagem plana por
  `allowed_tools=` do Estágio 1.
- README atualizado para refletir os quatro estágios concluídos e o estado
  real do projeto (beta pronto para uso interno, com limitações honestas
  listadas).

### Corrigido

- `except` genérico silencioso em `FilesystemTool.exists()`.
- Aba "Aprendizado" nas Configurações ainda dizia que o recurso seria
  implementado em um estágio futuro, apesar de já estar funcional desde o
  Estágio 3.

## [Não lançado] — Estágio 3: Reflexão e aprendizado

- Reflection Engine e Learning Engine: ciclo de vida completo de
  candidatos de aprendizado (`candidate → observing → active →
  deprecated/rejected`), com `SafetyValidator` recusando candidatos que
  sugiram pular verificação/segurança.
- Prompt Registry com versionamento imutável do Core Prompt por origem
  (`origin="user"` vs. automação).
- Playbooks (seeds pré-definidos + aprendidos) consultados pelo Planner
  antes de recorrer a um plano gerado por IA.
- Desempenho de modelo por agente/categoria (`model_performance.py`)
  alimentando o Router.
- Página de Aprendizado no frontend (revisão humana de candidatos,
  histórico, rollback).

## [Não lançado] — Estágio 2: Providers reais e orquestração

- Adapters reais para Claude, Gemini e OpenAI sobre `HttpProviderAdapter`,
  com mapeamento de erros normalizado e circuit breaker por provider.
- Pipeline completo de orquestração: Intent Analyzer → Planner → Router →
  Executor (DAG paralelo) → Verifier → Aggregator.
- Orçamento (budget) por execução com corte automático ao exceder limite.
- Armazenamento seguro de credenciais no keychain/credential manager do
  sistema operacional.

## [Não lançado] — Estágio 1: Fundação

- Aplicativo desktop Tauri 2 + React/TypeScript com bridge stdio/JSON
  Lines para um sidecar Python.
- Seis agentes padrão com permissões de mínimo privilégio.
- `resolve_safe_path` (sandbox de sistema de arquivos resistente a
  symlink), `PathTraversalError`.
- Banco de dados SQLite com migrations versionadas.
- `MockProvider` para desenvolvimento e testes sem custo de API real.
