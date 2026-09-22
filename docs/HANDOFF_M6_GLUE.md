# Handoff — Marco 6 / Onda 3: Glue Code

**Responsável:** Antigravity Lead  
**Branch:** `feat/v3-production-readiness`  
**Data:** 2026-09-21  

---

## 1. Escopo da Onda 3

A Onda 3 integra ponta a ponta as fundações de confiabilidade do Backend (Onda 1), os manifestos nativos e pipelines de empacotamento (Onda 2A) e a experiência de Onboarding e Diagnósticos do Frontend (Onda 2B), fornecendo a cola arquitetural do Marco 6:

1. **Allowlist de Comandos do Bridge (`core/security/allowlist.py`)**:
   - Registro explícito e tipado dos 6 novos comandos `system.*`:
     - `system.diagnostics.collect`
     - `system.diagnostics.export`
     - `system.backup.create`
     - `system.backup.list`
     - `system.backup.restore`
     - `system.onboarding.status`
   - Rejeição estrita de qualquer comando fora da allowlist antes do dispatch.

2. **Injeção de Serviços no Contexto (`core/bridge/context.py`)**:
   - Instanciação de `BackupManager`, `RestoreManager` e `DiagnosticsCollector` na função `build_context`.
   - Suporte a fallback defensivo sob demanda (`_backup_manager`, `_restore_manager`, `_diagnostics_collector`) para isolamento de testes e harnesses temporários.

3. **Handlers do Bridge (`core/bridge/handlers.py`)**:
   - `_system_diagnostics_collect`: agrega metadados de sistema, saúde do SQLite, pragmas, inventário de providers/bindings e logs sanitizados.
   - `_system_diagnostics_export`: empacota o bundle .zip sanitizado, grava trilha de auditoria e retorna metadados completos de arquivo.
   - `_system_backup_create`: cria snapshot online consistente SQLite com manifesto SHA-256 e gravação de log de auditoria.
   - `_system_backup_list`: lista metadados de backups existentes ordenados cronologicamente.
   - `_system_backup_restore`: executa swap atômico de banco com snapshot pré-restore e revalidação de integridade.
   - `_system_onboarding_status`: diagnostica prontidão de primeiro uso (projetos, agentes, provedores e runtimes configurados).

4. **Pareamento Rigoroso de Timeouts (Rust + Python)**:
   - Contrato do Marco 6 rigorosamente espelhado em `core/bridge/server.py` e `desktop/src-tauri/src/bridge/manager.rs`:
     - Comandos padrão (30s Tauri / 30s Python): `system.diagnostics.collect`, `system.backup.list`, `system.onboarding.status`.
     - Comandos médios (60s Tauri / 60s Python): `system.diagnostics.export`, `system.backup.create`.
     - Comando longo de restauração (120s Tauri / 120s Python): `system.backup.restore`.

5. **Navegação e Roteamento Desktop (`desktop/src/stores/uiStore.ts`, `desktop/src/App.tsx`, `desktop/src/layouts/BottomNav.tsx`)**:
   - Inclusão dos destinos `diagnostics` e `onboarding` em `AppPage`.
   - Lazy loading e error boundaries de `DiagnosticsCenterPage` e `OnboardingPage` em `App.tsx`.
   - Atalhos na barra de navegação inferior `BottomNav.tsx`.

6. **Testes de Integração do Bridge (`tests/python/test_reliability_bridge.py`)**:
   - 6 testes cobrindo todo o ciclo de diagnóstico, exportação de zip, auditoria, criação/listagem/restauração de backup, rejeição de id inválido, status de onboarding e timeouts contratuais.

---

## 2. Evidências de Validação

- **Python Tests**:
  - `tests/python/test_reliability_bridge.py`: 6 passed em 1.09s.
  - `tests/python/test_reliability_core.py`: 9 passed.
  - Testes globais do projeto: 743 passed, 11 skipped em 50.55s (100% pass rate).
- **Python Quality**:
  - `ruff check`: All checks passed.
  - `mypy`: Success: no issues found in 9 source files.
- **Rust Desktop Shell**:
  - `cargo test --manifest-path desktop/src-tauri/Cargo.toml`: 14 passed (incluindo `test_reliability_paired_timeouts`).
  - `cargo clippy --manifest-path desktop/src-tauri/Cargo.toml --all-targets -- -D warnings`: Aprovado (zero warnings).
  - `cargo fmt --manifest-path desktop/src-tauri/Cargo.toml -- --check`: Aprovado.
- **Frontend Product**:
  - `npm --prefix desktop test -- --run`: 41 arquivos de teste, 220 testes aprovados.
  - `npm --prefix desktop run lint`: Aprovado (0 erros, 0 avisos).
  - `npm --prefix desktop run build`: Aprovado (dist estático gerado em 709ms).
