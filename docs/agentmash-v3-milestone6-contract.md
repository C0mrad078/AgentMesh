# AgentMash V3 — Milestone 6 Shared Contract: Production Readiness & Release Candidate

This document establishes the binding architectural contract, domain models, packaging matrices, backup/restore invariants, diagnostics bundle specifications, file ownership boundaries, security rules, and acceptance criteria for **Milestone 6 (Production Readiness & Release Candidate)**.

---

## 1. Architectural Mission & Objectives

The purpose of Milestone 6 is to transform AgentMash from an integrated engine into a distributed, hardened, observable, recoverable, and user-friendly **Release Candidate (RC)** for Windows and macOS desktop platforms.

Milestone 6 does **not** introduce new major agent orchestration concepts. Its focus is strict production readiness:
1. **Self-Contained Desktop Application**: Packaged Tauri application that operates independently of development servers (`npm run dev`, `vite`, manual Python processes, or developer machine paths).
2. **Robust SQLite Backup & Restore**: Transactionally safe online SQLite backups with checksums, manifests, atomic swap, and fail-safe recovery that protects existing data.
3. **Diagnostics & Troubleshooting Bundle**: Comprehensive diagnostic export with complete, strict redaction of secrets, tokens, prompts, and user code.
4. **Resilient Initial Experience & State Management**: Graceful first-time onboarding, provider detection, clean empty/degraded states, and absence of optimistic success.
5. **Multi-Platform CI Packaging**: Reproducible CI build matrix for macOS (Apple Silicon and Intel) and Windows x64 producing verifiable native installers (`.dmg`, `.app`, `.exe`/NSIS).
6. **Integrity & Code Signing Transparency**: Honest, documented handling of code signing and notarization without fabricated certificates or keys in the repository.

---

## 2. Versioning Audit & Proposed Release Candidate Version

An audit of the codebase manifests reveals the current version baseline:
* `desktop/package.json`: `0.1.0` (name: `orquestrador`)
* `desktop/src-tauri/Cargo.toml`: `0.1.0` (name: `orquestrador`)
* `desktop/src-tauri/tauri.conf.json`: `0.1.0` (productName: `Orquestrador`)
* `pyproject.toml`: `0.1.0` (name: `orchestrator-core`)
* `core/__init__.py`: `__version__ = "0.1.0"`

### Target Release Candidate Version:
Following standard SemVer 2.0 conventions aligned with the existing codebase:
$$\mathbf{0.1.0\text{-}rc.1}$$

All manifests, DTOs, bridge version queries, and UI version badges must reference `0.1.0-rc.1`.

---

## 3. Supported Platforms & Build Matrix

| Platform | Architecture | Target Triple | Packaging Format | Target Artifact |
| :--- | :--- | :--- | :--- | :--- |
| **macOS** | Apple Silicon (M-series) | `aarch64-apple-darwin` | `.app`, `.dmg` | `Orquestrador_0.1.0-rc.1_aarch64.dmg` |
| **macOS** | Intel x64 | `x86_64-apple-darwin` | `.app`, `.dmg` | `Orquestrador_0.1.0-rc.1_x64.dmg` |
| **Windows** | x86_64 (64-bit) | `x86_64-pc-windows-msvc` | NSIS `.exe` / MSI | `Orquestrador_0.1.0-rc.1_x64-setup.exe` |
| **Linux** | x86_64 | `x86_64-unknown-linux-gnu` | AppImage / deb | CI testing & development runtime |

### Packaging Rules:
1. Native desktop installers must bundle the compiled frontend assets (`desktop/dist`).
2. Bundled binaries must locate system CLIs (`gh`, `git`, `python3`) via standard platform lookups or fallback gracefully with explicit user instructions.
3. Installers must never touch or delete user database directories during uninstallation or upgrade unless explicitly requested by the user.

---

## 4. SQLite Backup & Restore Architecture

### 4.1 Invariants
* **Online Backup API**: Backups must utilize `sqlite3.Connection.backup()` (or equivalent online WAL checkpointing). Raw file copies during active database operations are strictly forbidden.
* **Backup Manifest**: Every backup must be accompanied by an immutable JSON manifest:
  ```json
  {
    "backup_id": "bkp-20260921-123456-abc12345",
    "schema_version": 21,
    "app_version": "0.1.0-rc.1",
    "created_at": "2026-09-21T20:45:00Z",
    "db_size_bytes": 1048576,
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "source_path": ".../agentmash.db",
    "tables_count": 19,
    "records_summary": {
      "missions": 5,
      "delivery_candidates": 2,
      "release_candidates": 2,
      "deployment_runs": 8
    }
  }
  ```
* **Retention Policy**:
  * Default: Retain the last 5 successful backups.
  * Explicit manual backups can be flagged as `protected` to prevent automated pruning.
* **Safe Restore Invariants**:
  1. Validate SHA-256 checksum against manifest before touching anything.
  2. Verify schema compatibility (`backup.schema_version <= current_supported_schema`).
  3. Load backup into an isolated temporary connection and execute:
     - `PRAGMA integrity_check` (must return `ok`)
     - `PRAGMA foreign_key_check` (must return 0 violations)
  4. Automatically create a safety snapshot of the active database (`pre_restore_backup.db`).
  5. Perform an atomic file swap (`os.replace`).
  6. If post-restore database connection verification fails, immediately restore the safety snapshot (`rollback_to_safety_snapshot`).

---

## 5. Diagnostics Bundle & Data Sanitization Specification

### 5.1 Diagnostics Bundle Contents
Exported as a sanitized `.zip` archive containing:
* `metadata.json`: App version, OS platform, architecture, Python version, Node version, applied migrations (0001 through 0021), memory usage, uptime.
* `providers.json`: Availability and versions of external CLIs (`git`, `gh`).
* `runtime_bindings.json`: Configured bindings and target branches (sanitized).
* `database_health.json`: SQLite PRAGMAs, database file size, aggregated counts per entity table.
* `logs_sanitized.log`: Last 500 system logs passing through the redaction filter.

### 5.2 Mandatory Redaction Rules (Zero-Leak Policy)
The diagnostics bundle must NEVER contain:
* Authentication tokens, API keys, personal access tokens (`ghp_*`, `github_pat_*`, `sk-*`, `Bearer *`).
* Headers: `Authorization`, `Cookie`, `X-Api-Key`.
* Full contents of `.env` files.
* SSH keys (`-----BEGIN ... PRIVATE KEY-----`).
* Private code files or user repositories.
* Full raw mission prompts.
* Database connection strings containing passwords (`postgres://user:pass@`).

---

## 6. Bridge Protocol for Milestone 6

Milestone 6 introduces 6 new explicit bridge commands (totaling 22 system-wide commands):

| Command Name | Description | Python Handler | Timeout (Tauri / Python) |
| :--- | :--- | :--- | :--- |
| `system.diagnostics.collect` | Collects local diagnostic report | `handle_diagnostics_collect` | 30s / 30s |
| `system.diagnostics.export` | Generates sanitized diagnostic ZIP | `handle_diagnostics_export` | 60s / 60s |
| `system.backup.create` | Creates consistent SQLite backup | `handle_backup_create` | 60s / 60s |
| `system.backup.list` | Lists existing backup manifests | `handle_backup_list` | 30s / 30s |
| `system.backup.restore` | Restores database from backup ID | `handle_backup_restore` | 120s / 120s |
| `system.onboarding.status` | Checks onboarding readiness & providers | `handle_onboarding_status` | 30s / 30s |

All commands are strictly typed in `desktop/src/types/reliability.ts` and `desktop/src/services/reliabilityApi.ts`.

---

## 7. Performance & Security Criteria

1. **Cold Start**: Native application window ready and interactive in $\le 3.0$ seconds.
2. **Database Initialization**: SQLite connection and migrations verification in $\le 250$ milliseconds.
3. **Backup Execution**: Backup creation for standard databases ($\le 50$ MB) in $\le 2.0$ seconds.
4. **Diagnostics Export**: Complete bundle generation and sanitization in $\le 4.0$ seconds.
5. **Zero Memory Leaks**: Memory footprint idle $\le 150$ MB for desktop UI and background bridge.
6. **No Wildcards**: Bridge dispatcher enforces exact command allowlist.

---

## 8. Code Signing & Notarization Governance

* **Honesty First**: Never fabricate certificates, generate fake self-signed identities claiming official status, or store private signing keys in git.
* **Unsigned Internal Release Candidate**: If Apple Developer ID or Microsoft Authenticode credentials are not configured in CI secrets:
  * CI produces an unsigned build clearly designated as **`Unsigned Internal RC`**.
  * The release documentation explicitly itemizes the credentials required for public distribution:
    - macOS: `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`.
    - Windows: `AZURE_KEY_VAULT` or `CSC_LINK` / `CSC_KEY_PASSWORD`.

---

## 9. File Ownership & Wave Sequencing

All work takes place in `/Users/jhonatan/Downloads/AgentMesh` on branch `feat/v3-production-readiness`.

### Wave 1: Backend Reliability — Codex 1
* **Files owned exclusively**:
  - `core/reliability/__init__.py`
  - `core/reliability/models.py`
  - `core/reliability/backup.py`
  - `core/reliability/restore.py`
  - `core/reliability/diagnostics.py`
  - `tests/python/test_reliability_core.py`
  - `docs/HANDOFF_M6_RELIABILITY.md`
* **Prerequisite**: Reviewed and approved by Antigravity Reviewer before Wave 2 starts.

### Wave 2: Platform & Frontend (Parallel Execution)
* **Codex 2 (Platform & Packaging)**:
  - `desktop/src-tauri/Cargo.toml`
  - `desktop/src-tauri/tauri.conf.json`
  - `.github/workflows/release-candidate.yml`
  - `scripts/verify_artifacts.py`
  - `docs/HANDOFF_M6_PLATFORM.md`
* **Codex 3 (Frontend Product)**:
  - `desktop/src/types/reliability.ts`
  - `desktop/src/services/reliabilityApi.ts`
  - `desktop/src/stores/reliabilityStore.ts`
  - `desktop/src/pages/DiagnosticsCenterPage.tsx`
  - `desktop/src/pages/OnboardingPage.tsx`
  - `desktop/src/pages/__tests__/DiagnosticsCenterPage.test.tsx`
  - `desktop/src/pages/__tests__/OnboardingPage.test.tsx`
  - `docs/HANDOFF_M6_FRONTEND.md`

### Wave 3: Glue Code — Antigravity Lead
* Bridge integration (`core/bridge/commands.py`, `core/bridge/handlers/`), routing, and shell integration.

### Wave 4: Security Audit & Performance Benchmarking
* Full dependency audit, secret scan, and real hardware benchmark.

### Wave 5: CI Build & Native Verification
* Automated build execution, artifact hash verification, clean runtime test, and final Reviewer sign-off.
