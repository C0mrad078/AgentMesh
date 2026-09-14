# AgentMash Refactor V2 — Plan (Phase 0 Audit + Phase 1 Domain Model)

This document is the required Phase 0 deliverable for the "Virtual AI Office /
Multi-Agent Development Orchestrator" refactor. It records what exists today,
what the refactor is aiming for, and the concrete, additive plan for Phase 1
(the persistent domain model). It will be extended (not rewritten) as later
phases land — new sections get appended, nothing here gets deleted once a
phase is real.

Ground rule carried through every phase: **migrations are additive only**.
Nothing in `core/database/migrations/versions/0001..0005` is touched. Every
new table/column is a new numbered file.

## 1. Baseline (recorded before any Phase 1 code was written)

Full repo, working tree as of this audit (includes the Stage 3 fallback-tooltip
and Router fallback-preference-bonus work from the prior session — that work
is complete and part of the baseline, not something this refactor redoes):

| Gate | Result |
|---|---|
| `pytest` (Python, excluding the two `RUN_LIVE_AI_TESTS`-gated live-CLI tests) | **527 passed, 6 skipped** |
| `ruff check .` | Clean except 2 pre-existing findings in `scripts/generate_office_map.py` (an untracked, one-off pixel-asset generator script, not part of the runtime — not touched by this refactor) |
| `mypy core` | **0 errors across 143 source files** |
| `npm run typecheck` (desktop) | Clean |
| `npm run lint` (desktop) | Clean |
| `npm run test -- --run` (desktop, Vitest) | **119 passed (23 files)** |
| `npm run build` (desktop, Vite) | Clean (pre-existing chunk-size warning only, unrelated) |
| `cargo test` (src-tauri) | **Not run** — `cargo` is not on PATH in this environment. Phase 1 makes no Rust changes, so this has no bearing on Phase 1's own correctness, but it is an honest gap in this baseline, not a claimed pass. |

Every phase from here on must keep the Python/Frontend rows at "0 failures,
0 new skips of a previously-passing test" before moving to the next phase.

## 2. Current architecture map

The project (internally "Orquestrador") is already a substantial, working
system — this is not a greenfield build. The audit below exists so the
refactor **extends** this rather than rebuilding it blind.

### 2.1 Backend (`core/`)

| Module | What it actually does today | Disposition |
|---|---|---|
| `core/agents/` (`models.py`, `registry.py`, `prompt_registry.py`, `default_prompts.py`) | `Agent` (Pydantic): id, name, description, provider, model, system_prompt, capabilities, tools, permissions, config, active, **`preferred_provider`/`fallback_providers`** (added Stage 3). `AgentRegistry` is the in-memory, capability-indexed lookup the `Router` queries — deliberately has no public "add agent" mutator (registry = routing-time truth, not a CRUD surface). | **REUSE + REFACTOR**: extend `Agent` with the new office/presence fields (role, avatar, status, preferred/fallback *backend*, memory_profile). `AgentRegistry` itself is untouched — it's a routing concern, not a persistence concern. |
| `core/projects/` (`models.py`, `service.py`) | `Project`: id, name, description, workspace_path, status, config (open JSON bag), timestamps. `ProjectService` wraps `ProjectsRepository` + audit logging. No git/README/stack analysis yet. | **REUSE**. `ProjectProfile`/`ProjectAnalyzer` (Phase 4) is new, additive — it reads a project, it doesn't change what a `Project` row is. |
| `core/tasks/` (`models.py`, `service.py`, `state_machine.py`) | `Task`: id, project_id, conversation_id, title, description, mode (automatic/manual/pipeline/debate/consensus), status, input, result, timestamps. No agent/team/session assignment field yet. | **REUSE + REFACTOR**: add `assigned_agent_id`/`assigned_team_id`/`session_id` (Phase 1, additive columns). The DAG-level `PlanStep`/dependency system in `core/orchestrator/` is separate and untouched. |
| `core/orchestrator/` (`engine.py`, `router.py`, `planner.py`, `dag.py`, `verifier.py`, `judge.py`, `meeting_manager.py`, `event_bus.py`, `concurrency.py`, `recovery.py`, `budget.py`, `aggregator.py`, `context_builder.py`, `intent_analyzer.py`, `validation.py`) | The real execution core: DAG planning, capability+health+learning-weighted routing (`Router`, now with the Stage-3 `fallback_preference_bonus`), correction/repair loop, meeting detection, typed `EventBus`. This *is* most of "Supervisor + Planner + Task Graph + Scheduler" already, in a Task/Execution shape rather than an Agent/Session shape. | **REUSE, heavy**. Phase 7 ("Orchestration") is mostly *renaming the lens* (Session-aware) on top of this, not rebuilding it. `AgentSupervisor` (new name in the spec) should wrap/compose this, not replace it. |
| `core/providers/` (`base.py`, `registry.py`, `pool.py`, `health.py`, `circuit_breaker.py`, `provider_manager.py`, `credentials.py`, `cli_provider.py`, `codex_cli_provider.py`, `claude_code_cli_provider.py`, `gemini_cli_provider.py`, `anthropic_provider.py`, `openai_provider.py`, `gemini_provider.py`, `http_provider.py`, `mock_provider.py`) | Already has almost exactly the conceptual split the refactor asks for, just not named/persisted that way: `ProviderAccessMethod` (`HTTP_API` / `CLI` / `MOCK`) is the seed of `ExecutionBackendType`; `ProviderStatus`/`ProviderConnectionState` is the seed of the Providers UI card; `ProviderManager` already does real, uncached CLI discovery (`--version`, login status) for `codex_cli`/`claude_code_cli`/`gemini_cli` — this **is** Subscription Runtime discovery, already built. `ProviderPool` + `ProviderHealthMonitor` is the runtime-availability layer the `Router` already consumes. Nothing here is persisted as a `Provider`/`ProviderAccount` row yet — provider identity today is just a string (`"claude_code_cli"`) resolved against `ModelRegistry`/`ProviderPool` at call time. | **REUSE + CREATE**: keep every adapter/pool/health/manager class as-is. *Add* the persistence layer on top (`providers`, `provider_accounts`, `provider_backends` tables) — Phase 1 — without touching `ProviderAdapter`/`ProviderAccessMethod` (they stay the low-level transport classification; the new tables are the "what's configured/connected" record). |
| `core/memory/` (`models.py`, `store.py`) + `project_memories` table/repo | `MemoryRecord`/`MemoryWrite` already have a real provenance + supersession model (confidence, `valid_from`/`valid_until`/`superseded_by` — a *new* contradicting fact never overwrites in place, it supersedes). Scoped to `project_id` only today (`MemoryKind`: fact/execution_summary/agent_note/preference). This is a strong foundation for "Project Memory" and most of the supersession machinery "Memory Pipeline" needs — it is **not** yet 4-level (global/project/agent/session). | **REUSE + REFACTOR**: Phase 1 adds `scope` + nullable `agent_id`/`session_id` columns and makes `project_id` nullable (global-scope memories have no project). The classification taxonomy (FACT/DECISION/PREFERENCE/RULE/EXPERIENCE/WARNING/TEMPORARY) and the retrieval/validation *pipeline* stay Phase 5 — Phase 1 only lays the schema/model groundwork so Phase 5 doesn't need another migration. |
| `core/learning/` | Reflection/rule-learning/prompt-optimization system (Stage 3). Orthogonal to this refactor. | **REUSE, untouched**. |
| `core/security/` (`secret_store.py`, `allowlist.py`, `permissions.py`, `audit.py`, `secret_scanner.py`) | `SecretStore` already delegates to OS keychain (`keyring`) with a non-durable in-memory fallback when no OS backend exists — never plaintext. This already satisfies the refactor's "Secrets" requirement. | **REUSE, untouched**. `ProviderAccount` secrets (Phase 1) key off `account_id` instead of bare provider name — a key-naming convention, not a new storage mechanism. |
| `core/tools/` (`git_tool.py`, `project_scanner.py`, `project_stack.py`, `filesystem_tool.py`, `terminal_tool.py`, `command_planner.py`, `path_guard.py`) | `project_scanner.py`/`project_stack.py` already do real stack/framework detection — direct reuse target for the Phase 4 `ProjectAnalyzer`. `git_tool.py` wraps git operations already (no arbitrary shell — argv-list `subprocess`, matching the refactor's security rule). No worktree-specific operations yet. | **REUSE**. Phase 4's `WorktreeManager` should extend `git_tool.py`'s existing git-wrapping conventions, not invent a second git-calling path. |
| `core/bridge/` (`context.py`, `handlers.py`, `main.py`, `protocol.py`, `server.py`, `transport.py`) | `BridgeContext` (a plain `@dataclass`) is the single DI graph, built once in `build_context()`; `main.py` is a thin stdio-JSONL entrypoint. This *is* the "don't go HTTP-localhost" bridge the refactor explicitly says to preserve. | **REUSE, untouched shape**. Phase 1 adds new repositories as new `BridgeContext` fields (additive dataclass fields + additive `build_context()` construction lines) — no protocol change. |
| `core/database/` (`connection.py`, `migrations/`, `repositories/*`) | Versioned, glob-discovered, filename-ordered SQL migrations (`NNNN_description.sql`) applied in a transaction each, tracked in `schema_migrations`; one repository class per table, `Database.execute`/`fetch_one`/`fetch_all` + a small JSON codec (`json_codec.dumps`/`loads`) for JSON-shaped columns; ids are app-generated `uuid4().hex`, optionally prefixed (`core.utils.ids.new_id`). | **REUSE, exact pattern to replicate** for every new Phase 1 table/repo — see §4. |

No `Team`, `Session` (as a persisted, agent-centric concept distinct from
`executions`), `Worktree`, `Provider`/`ProviderAccount`/`ExecutionBackend`
table exists yet. `executions`/`execution_steps` are the DAG-run bookkeeping
for a `Task` — real and useful, but not the same thing as the new spec's
`Session` (a continuous CLI/API run tied to one agent, one account, one
optional worktree, that can outlive/wrap multiple executions). Phase 1
creates `Session` alongside `executions` rather than replacing it; how the
engine reconciles the two is a Phase 2/3 wiring question, out of scope here.

### 2.2 Frontend (`desktop/`)

Only inspected for context — **Phase 1 makes zero frontend changes**
("não modificar Office ainda" applies to the whole domain-model phase, not
just the Office screen literally).

- `desktop/src/pages/`: `OfficePage`, `AgentsPage`, `ExecutionsPage`,
  `LearningPage`, `SettingsPage`, `WorkspacePage`. No `ProjectsPage`,
  `TeamsPage`, or `MemoryPage` yet — new nav items for Phase 9/10.
- `desktop/src/stores/`: `connectionStore`, `executionStore`, `projectsStore`,
  `uiStore`. `executionStore` already reacts to pushed `orchestrator://event`
  data (no polling except a narrow, conditional provider-health poll) — the
  right pattern to extend for Presence events later, not replace.
- `desktop/src/game/`: the Stage 1/2/3 pixel office (Phaser-based), already
  event-driven off real backend state via `RealOfficeAdapter` +
  `AgentStateMachine` (see `GAME_ENGINE.md`/`VIRTUAL_OFFICE.md`) — this is
  exactly the "Presence Engine → visual state" pipeline the refactor asks
  for, already built for the current 4-fixed-character office. Phase 9's
  job is generalizing it to N real agents/teams/projects, not building it
  from zero.
- `desktop/src-tauri/`: `bridge/`, `commands.rs`, `lib.rs`, `main.rs` — the
  stdio-JSONL↔Tauri bridge. Untouched by Phase 1.

### 2.3 REUSE / REFACTOR / DEPRECATE / DELETE / CREATE summary

- **REUSE untouched**: `AgentRegistry`, `Router`/`ExecutionEngine`/DAG/
  `EventBus`, every `ProviderAdapter` implementation, `ProviderPool`/
  `ProviderHealthMonitor`/`ProviderManager`, `SecretStore`, `core/tools/*`,
  `core/learning/*`, the bridge's stdio-JSONL protocol, the entire pixel
  office rendering pipeline.
- **REFACTOR (additive)**: `Agent` (+ presence/backend-preference fields),
  `Task` (+ assignment fields), `MemoryRecord`/`project_memories` (+ scope).
- **CREATE**: `Team`, `Session`, `Worktree`, `Provider`, `ProviderAccount`,
  `ProviderBackend` (the persisted `ExecutionBackend` record) — all Phase 1.
  `AgentSupervisor`, `MemoryRetriever`/`Validator`, `WorktreeManager`,
  `PresenceEngine`, the Projects/Teams/Memory UIs — later phases.
- **DEPRECATE**: nothing yet. No module identified in this audit is made
  obsolete by Phase 1.
- **DELETE**: nothing. (Consistent with the project's standing rule: never
  delete code just for being old; nothing here is dead.)

## 3. Target architecture (conceptual, restated from the brief)

```
USER → AgentMash Desktop → Pixel Office → App State
                                             │
                    ┌────────────────────────┼─────────────────────┐
                    ▼                        ▼                     ▼
                Projects                   Teams                Memory
                    │                        │                     │
                    └────────────────────────┼─────────────────────┘
                                              ▼
                                     Agent Supervisor
                                              │
                                              ▼
                                          Planner
                                              │
                                              ▼
                                         Task Graph
                                    ┌─────────┼──────────┐
                                    ▼         ▼          ▼
                                 Agent      Agent      Agent
                                    │         │          │
                                    ▼         ▼          ▼
                                Session    Session    Session
                                    │         │          │
                                    ▼         ▼          ▼
                              Execution Backend Layer (Subscription / Session / API)
                                              │
                                              ▼
                                     Provider Adapter (Claude → Codex → Antigravity)
```

`Provider` ≠ `ExecutionBackend`: a `Provider` row (`claude`, `openai`,
`google`) can have zero or more `ProviderBackend` rows (one per
subscription/session/api combination it supports), and zero or more
`ProviderAccount` rows (for providers that support multiple signed-in
accounts). This is exactly the model in §"PROVIDER NÃO É BACKEND" of the
brief, expressed as tables in §4.

## 4. Phase 1 — Domain Model (this delivery)

Ten entities requested: **Provider, ProviderAccount, ExecutionBackend,
Agent, Team, Project, Session, Memory, Task, Worktree.** Project needs no
schema change (already adequate — see §2.1); the other nine get either a
new table or additive columns. Every migration below is a new file; none
of `0001`-`0005` is edited.

| # | File | Adds |
|---|---|---|
| 1 | `0006_teams.sql` | `teams`, `team_agents` (join table) |
| 2 | `0007_providers.sql` | `providers`, `provider_accounts`, `provider_backends` (+ seeds `claude`/`openai`/`google` provider rows) |
| 3 | `0008_worktrees.sql` | `worktrees` |
| 4 | `0009_sessions.sql` | `sessions` (references agents, projects, providers, provider_accounts, tasks, worktrees — all already exist by this point in the sequence) |
| 5 | `0010_agent_presence_fields.sql` | `agents.role`, `.avatar`, `.status`, `.preferred_backend`, `.fallback_backend`, `.memory_profile` |
| 6 | `0011_task_assignment_fields.sql` | `tasks.assigned_agent_id`, `.assigned_team_id`, `.session_id` |
| 7 | `0012_memory_scopes.sql` | `project_memories.scope`, `.agent_id`, `.session_id`; rebuilds the table (SQLite `ALTER TABLE` cannot drop a `NOT NULL` constraint) so `project_id` becomes nullable for `GLOBAL`-scope rows; existing rows are backfilled `scope='project'` and keep their `project_id` |

Design notes / decisions made so a later phase doesn't have to re-litigate
them:

- **`ExecutionBackendType`** (`subscription` / `session` / `api`) is a new,
  domain-level enum distinct from the existing low-level
  `ProviderAccessMethod` (`http_api`/`cli`/`mock`) in `core/providers/base.py`.
  They are related but not merged: `ProviderAccessMethod` says *how an
  adapter talks to the world*; `ExecutionBackendType` says *which of the
  three user-facing execution modes this is*. `session` has no
  `ProviderAccessMethod` equivalent today (resuming/attaching an existing
  CLI session is new ground, Phase 3).
- **`Agent.status`** is added as a real column now but is *not* wired to
  anything real in Phase 1 — nothing computes or displays it yet (no UI
  changes this phase). It exists so Phase 8's Presence Engine has a place
  to write real state without another migration. Documented in code as a
  placeholder, consistent with the project's "never fabricate progress/
  state" rule — the column exists, nothing reads it as truth yet.
- **`Team.project_id` is nullable, single-valued**, matching the brief's own
  `Team` field list literally (`id, name, project_id, description, ...`).
  Team↔Agent is the actual many-to-many (`team_agents` join table); no
  Team↔Project join table is added since the brief never asked for a team
  spanning multiple projects, and adding one now would be speculative.
- **`Worktree` does not reference `Session`** (only `Session` references
  `Worktree`) — avoids a circular FK between the two new tables. A worktree
  is owned by a project; which session (if any) is currently using it is
  Session's field, not Worktree's.
- **Secrets for `ProviderAccount`** will be looked up from `SecretStore`
  keyed by `account_id` (not bare provider name) once Phase 3 wires real
  credential flows — no `SecretStore` code changes in Phase 1, this is
  just the key-naming convention future phases must follow.
- New repositories are wired into `BridgeContext`/`build_context()` (new
  dataclass fields + construction lines) so they are real, DI-tested
  objects from day one — but **no new bridge JSON-RPC command/handler** is
  added yet. Nothing consumes these tables at runtime until Phase 2/3/6;
  adding commands now would be UI-less dead surface.

## 5. Migration risk register

- **Table rebuild for `project_memories`** (item 7 above) is the only
  non-trivial migration: SQLite requires create-copy-drop-rename to relax a
  `NOT NULL` column. Mitigated by: running inside the existing
  transaction-per-migration runner (all-or-nothing), recreating every index
  the table currently has (`uq_project_memories_active_key`,
  `idx_project_memories_project_id`), and a dedicated test that seeds rows
  through the *old* code path first, applies the migration, and asserts the
  data survived with `scope='project'` before any new code touches it.
- **FK ordering**: `sessions` references four other new/existing tables; it
  is deliberately the *last* new table created so every FK target already
  exists when SQLite parses the `CREATE TABLE` (SQLite does not defer FK
  target existence checks the way some engines do at DDL time for
  `REFERENCES`, though enforcement itself is at DML time under
  `PRAGMA foreign_keys=ON`).
- **No destructive change anywhere in Phase 1** — every migration is
  `CREATE TABLE IF NOT EXISTS` or `ALTER TABLE ... ADD COLUMN`, except the
  one documented rebuild, which preserves all existing data.

## 6. Phased roadmap status

| Phase | Scope | Status |
|---|---|---|
| 0 | Audit, baseline, this document | **Done** |
| 1 | Domain model (Provider/ProviderAccount/ExecutionBackend/Agent/Team/Project/Session/Memory/Task/Worktree) + migrations + repositories + tests | **Done** |
| 2 | Runtime (`ProcessManager`, `SubscriptionRuntime`, `SessionRuntime`, `APIRuntime`, `RuntimeRegistry`) | Not started |
| 3 | Claude (Subscription + Sessions + Anthropic API, fully working) | Not started (foundation already strong — `ClaudeCodeCliProvider`, `AnthropicProvider`, `ProviderManager` discovery all exist and work today) |
| 4 | Projects + Worktrees (`ProjectAnalyzer`, `WorktreeManager`) | Not started (`project_scanner.py`/`project_stack.py` already do real stack detection — reuse target) |
| 5 | Memory (Global/Project/Agent/Session, Retriever, Validator, classification pipeline) | Not started (schema groundwork lands in Phase 1) |
| 6 | Teams (roles, assignments) | Not started (table lands in Phase 1) |
| 7 | Orchestration (Supervisor, Planner, Task Graph, Scheduler, parallel execution) | Not started (DAG/Router/Engine already real — mostly a Session-aware lens on existing code) |
| 8 | Presence (Event Bus, Presence Engine, state normalization) | Not started (`RealOfficeAdapter`/`AgentStateMachine` already do this for the current 4-character office — generalize, don't rebuild) |
| 9 | Pixel Office (full multi-project/multi-team interface) | Not started |
| 10 | Polish | Not started |
| 11 | Codex | Not started |
| 12 | Google/Antigravity | Not started |

## 7. Phase 1 report

### Completed

- Ten domain entities from the brief now have a real, persisted shape:
  `Provider`, `ProviderAccount`, `ProviderBackend` (the persisted
  `ExecutionBackend` record), `Team`, `Session`, `Worktree` as new tables;
  `Agent`, `Task`, `Project` extended (Project needed no change); `Memory`
  generalized from project-only to four scopes.
- Every new/extended repository is real and tested against a real SQLite
  connection (via the existing `tmp_db` fixture) — no mocks standing in
  for the database layer.
- `BridgeContext`/`build_context()` now constructs and exposes
  `teams_repo`, `providers_repo`, `provider_accounts_repo`,
  `provider_backends_repo`, `sessions_repo`, `worktrees_repo` alongside
  every existing repository, so later phases can consume them without
  another wiring pass.
- `docs/refactor-v2-plan.md` (this document) written per Phase 0's
  requirement, and kept as a living document (this section appended, not
  a separate report file).

### Changed

- `core/agents/models.py`: `Agent` gained `role`, `avatar`, `status`
  (`AgentStatus`), `preferred_backend`/`fallback_backend`
  (`ExecutionBackendType`), `memory_profile`. `AgentsRepository` extended
  to match.
- `core/tasks/models.py`: `Task`/`TaskCreate` gained
  `assigned_agent_id`/`assigned_team_id`/`session_id` (all nullable).
  `TasksRepository` extended to match, plus a new `assign_session()`
  method.
- `core/memory/models.py`: `MemoryRecord`/`MemoryWrite` gained `scope`
  (`MemoryScope`), `agent_id`, `session_id`; `project_id` is now optional.
  A `model_validator` on `MemoryWrite` rejects any scope/identifier
  mismatch (e.g. `AGENT` scope with a `session_id` instead of an
  `agent_id`) at construction time. `ProjectMemoriesRepository` gained
  `get_active_for_scope`/`list_active_for_scope`; `SqliteMemoryStore`
  gained `recall_global`/`recall_all_global`/`recall_for_agent`/
  `recall_all_for_agent`/`recall_for_session`/`recall_all_for_session`.
  The existing `remember`/`recall`/`recall_all`/`history` (project scope)
  are behaviorally unchanged — verified by the full pre-existing
  `test_memory.py`/`test_memory_provenance.py` suites passing untouched.

### New architecture

- `core/runtime/execution_backend.py`: `ExecutionBackendType`
  (subscription/session/api) — the one new cross-cutting enum, imported
  by `Agent`, `ProviderBackend`, and `Session`.
- `core/providers/catalog.py`: `Provider`, `ProviderAccount`,
  `ProviderBackend` domain models — deliberately separate from
  `core/providers/base.py` (the adapter/runtime interface) and
  `core/providers/registry.py` (the model catalog); see the module's own
  docstring for the three-way distinction.
- `core/teams/models.py`, `core/sessions/models.py`,
  `core/worktrees/models.py`: new per-domain model modules, following the
  exact convention `core/projects/models.py`/`core/tasks/models.py`
  already established.
- `core/database/repositories/{teams,providers,provider_accounts,
  provider_backends,sessions,worktrees}_repo.py`: new repositories, each
  following the existing `ProjectsRepository`/`AgentsRepository` pattern
  (`Database.execute`/`fetch_one`/`fetch_all`, `json_codec` for JSON
  columns, `new_id()` for ids, `NotFoundError` for missing rows).

### Migrations

`0006_teams.sql` · `0007_providers.sql` · `0008_worktrees.sql` ·
`0009_sessions.sql` · `0010_agent_presence_fields.sql` ·
`0011_task_assignment_fields.sql` · `0012_memory_scopes.sql` — all
additive; `0012` is the one table-rebuild (documented in §5), verified by
a dedicated test that seeds a legacy-shape row, applies only that
migration, and asserts the data survived (`test_migration_0012_memory_scopes.py`).

### Tests

- New: `test_teams_repo.py`, `test_providers_repo.py`,
  `test_sessions_repo.py`, `test_worktrees_repo.py`,
  `test_memory_scopes.py`, `test_migration_0012_memory_scopes.py`.
- Extended: `test_agents_repo.py` (presence/backend fields, including an
  explicit "nothing computes real status yet, IDLE is the inert default"
  assertion), `test_tasks.py` (assignment fields + `assign_session`).
- Full Python suite: **566 passed, 6 skipped** (up from the 527/6
  baseline — 39 new tests, 0 regressions). `ruff check .` clean except the
  same 2 pre-existing findings in `scripts/generate_office_map.py`
  (untracked, unrelated). `mypy core` clean across 158 source files (up
  from 143 — 15 new modules, 0 new errors).
- Frontend gate re-verified unchanged (Phase 1 touched no frontend code):
  typecheck/lint/build clean, 119/119 Vitest tests passing.
- `cargo test` still not run (`cargo` unavailable in this environment) —
  irrelevant to Phase 1 since no Rust file was touched.

### Known limitations (disclosed, not hidden)

- `Agent.status` is schema-only — nothing computes or displays it yet
  (by design; Phase 8's job). Documented in the model's own docstring and
  asserted explicitly in `test_agents_repo.py` so a future change to the
  default doesn't silently start being read as "real."
- `memory_conflicts` (the audit trail for a superseded fact) still only
  fires for `PROJECT`-scope memories — its `project_id` column is `NOT
  NULL`, and widening it was judged out of Phase 1's declared table list.
  Supersession itself (`valid_until`/`superseded_by`) works correctly for
  all four scopes; only the *audit mirror* is project-scope-only for now.
- No bridge command/handler exposes any of the six new repositories yet —
  intentional (§4), but it means nothing in the running app can create a
  `Team`/`Session`/`Worktree`/`ProviderAccount` through the UI yet. That
  is Phase 2/3/6/9 wiring, not a Phase 1 gap.
- `ExecutionBackendType` and `ProviderAccessMethod` are intentionally two
  separate enums with related-but-not-identical meaning (§4) — a future
  reader should not assume they can be merged without checking both
  call sites first.
- `cargo test` baseline remains unverified in this environment (§1) —
  carried forward, not newly introduced.

### Next phase

Phase 2 (Runtime): `ProcessManager` (the one place every CLI subprocess
must go through — arg-list only, no `shell=True`, per the brief's explicit
security rule), then `SubscriptionRuntime`/`SessionRuntime`/`APIRuntime`
built on top of it and on the `ExecutionBackendType`/`ProviderBackend`
model this phase just persisted, plus `RuntimeRegistry` tying a
`(Provider, ExecutionBackendType)` pair to the concrete runtime that
handles it. Not started; no code for Phase 2 exists yet.
