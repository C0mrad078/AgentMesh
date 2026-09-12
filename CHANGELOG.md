# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento em [SemVer](https://semver.org/lang/pt-BR/). Nenhuma versão
com tag foi publicada ainda — este arquivo documenta o trabalho por
estágio de desenvolvimento até aqui.

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
