# AgentMash V2 — Phase 4: Domain Connection

Connects the Pixel Office to real, persistent `Project`/`Team`/`Agent`/
`Session` domain data, replacing the fixed 4-character mapping Estágio
1-3 built the office around. This document is the required deliverable
for **AGENTMASH V2 — PHASE 4**.

## 0. Audit of the existing domain model (done before any new code)

Before writing anything, the existing model was checked against the
brief's own "não recrie entidade já existente" rule:

| Entity the brief asks for | Already existed (Refactor V2 Phase 1, `docs/refactor-v2-plan.md`) | What Phase 4 actually needed |
|---|---|---|
| Project | Yes — `core.projects` (id, name, workspace_path, status, config...). | Nothing. Reused as-is. |
| Team | Yes — `core.teams` (id, name, project_id, description) + `team_agents` join table + `TeamsRepository` (create/update/list/delete/add_agent/remove_agent/list_agent_ids/list_team_ids_for_agent). | Nothing structural. Just needed bridge commands (§3). |
| Agent | Yes — `core.agents.models.Agent` already had `role`, `status`, `avatar`, `preferred_backend`/`fallback_backend`, `memory_profile` (Phase 1). **Missing**: no `project_id` (the primary project-assignment signal the brief's own "TESTE CRÍTICO" scenario needs), no real create/update repository methods (only `upsert`, used for registry-seeding), no bridge commands beyond read-only `agent.list`. | One additive migration (`project_id`, `visual_profile`); `AgentCreate`/`AgentUpdate` models; `AgentsRepository.create`/`update`/`list_by_project`; `agent.create`/`agent.update` bridge commands. |
| Session | Yes — `core.sessions` (id, agent_id, project_id, provider_id, backend_type, status...) + `SessionsRepository`, fully modeled in Phase 1. **Missing**: no bridge command exposed it to the frontend at all. | `session.list` bridge command only. |

No parallel table was created for anything already covered. No entity
was rebuilt from scratch.

## 1. Domain changes

- `core/agents/models.py`: `Agent` gained `project_id: str | None` (the
  primary signal the Office uses for per-project filtering — Team
  membership is a secondary, orthogonal grouping, not what drives it)
  and `visual_profile: dict[str, str]` (deliberately just
  `{"preset": "<key>"}`, never the richer skin/hair/outfit breakdown the
  brief sketches conceptually — nothing renders that yet, and persisting
  it would be fabricated-looking data). New `AgentCreate`/`AgentUpdate`
  models (the latter distinguishes "field not sent" from "field
  explicitly set to null" for `project_id`, so "unassign from project" is
  a real, expressible operation, not indistinguishable from "no change").

## 2. Database changes

One additive migration, `0013_agent_project_assignment.sql`:
`ALTER TABLE agents ADD COLUMN project_id ...`, `ADD COLUMN
visual_profile ...`, plus an index on `project_id`. Nothing in
`0001`-`0012` was touched.

## 3. Bridge changes

New, typed commands (no `generic.execute`), added to the allowlist and
implemented as real handlers over the repositories above:

```
agent.create          agent.update
team.create            team.update            team.delete
team.list               team.assign_agent       team.remove_agent
session.list
```

`agent.list`/`agent.create`/`agent.update` responses are enriched with a
real, computed `team_ids` field (`ctx.teams_repo.list_team_ids_for_agent`)
so the frontend never needs a second round-trip to know which team(s) an
agent belongs to. `team.list` responses are enriched with a real
`agent_ids` field the same way.

## 4. Frontend changes

- **Types** (`types/domain.ts`): `Team`, `Session`, `SessionStatus`; `Agent`
  gained `project_id`, `visual_profile`, `team_ids`.
- **Services** (`services/api.ts`): `agentsApi.create`/`update`,
  new `teamsApi`, new `sessionsApi`.
- **Stores** (one concern each, per the brief's own warning against a
  monolithic store): `agentsStore.ts`, `teamsStore.ts`, `sessionsStore.ts`,
  `officeSelectionStore.ts` (just `viewMode: "project" | "all"` — the
  Office's own project-filter, distinct from `projectsStore`'s
  app-wide "current project").
- **`pages/TeamPage.tsx`** (rewritten from Phase "0"'s plain read-only
  list into the real management surface the brief asks for): create
  agent, edit agent (`components/AgentFormDialog.tsx`, new), assign
  project, assign/remove team (inline, real API calls), set role, set
  visual preset, enable/disable. Still a plain list, not the V1 card
  grid the brief explicitly forbids reusing for this.
- **`pages/OfficePage.tsx`**: gained the real project filter
  (`<select>`: "Todos os projetos" + every real project) driving
  `officeSelectionStore`; Developer Mode's per-agent debug buttons
  (rate-limit/recover/testing/error/complete) now target the real
  selected/hovered agent instead of the retired hardcoded
  `"agent_codex"`/`"agent_claude_code"` ids.

## 5. Office (Pixel Office engine) changes

The visual engine itself (tilemap, sprites, pathfinding, rooms, camera)
is **unchanged** — Phase 4's brief explicitly forbids rewriting it, and
nothing about connecting it to real domain data required touching
`Character.ts`, `BootScene.ts`, `NavigationService`, `RoomRegistry`, the
four spritesheets, or the tilemap. What changed is *what decides which
characters exist and where they came from*:

- **New pure domain layer** (`game/office-domain/`, zero Phaser imports,
  fully unit-tested): `types.ts` (`OfficeAgentModel`,
  `OfficePresenceState`), `visualProfile.ts` (`VISUAL_PRESETS` — the 4
  real spritesheets as a finite preset pool; `resolveVisualProfile()` —
  real persisted preset, or a deterministic FNV-1a hash of the agent's
  own id as fallback, never `Math.random()`), `buildOfficeAgents.ts` —
  the pure function that turns real `Agent[]`/`Project[]`/`Team[]`/
  `Session[]` + the office's view-mode/selected-project into
  `OfficeAgentModel[]`. This is the function the brief's own "TESTE
  CRÍTICO" scenario is written against directly, with no Phaser involved
  (brief "PHASER TESTABILITY").
- **`game/agents/appearancePresets.ts`**: `AGENT_DEFINITIONS` (a fixed
  4-entry array) and `agentDefinition(id)` (lookup by one of 4 fixed
  ids) are gone. `buildAgentDefinition(model, showProjectLabel)` builds
  one `AgentDefinition` per real agent on demand.
- **`game/systems/WorkstationSystem.ts`**: the four physical desk
  positions the map has always had (`ceo_office`/`design_desk`/
  `frontend_desk`/`backend_desk` — real named points in
  `agentmashHq.json`, unchanged) are now a real, anonymous *pool*
  (`WORKSTATION_CAPACITY = 4`), claimed by whichever real agent id asks
  first via `OccupancySystem.claimAny` — exactly the pattern
  `SofaSystem`/`BedSystem`/`MeetingRoomSystem` already used (this system
  was the one outlier still doing fixed 1:1 binding).
- **`game/agents/AgentStateMachine.ts`**: no longer seeded from
  `AGENT_DEFINITIONS` at construction. Gained `ensureAgent(id)` (register
  on demand, idempotent) and `removeAgent(id)` (forget + release every
  spot it held). `apply()` auto-registers an unknown id instead of
  silently no-op'ing on one absent from a static list.
- **`game/agents/officeRosterStore.ts`** (new) + **`game/agents/OfficeDomainAdapter.ts`**
  (new, replaces the retired `RealOfficeAdapter.ts`): the one channel
  real data reaches the scene through, mirroring the existing
  `agentStateMachine` singleton-subscription pattern exactly so
  `OfficeScene` never imports `@/services`, `@/stores`, or `@/types`
  directly (brief "NÃO ACOPLAR PHASER AO BACKEND"). `OfficeDomainAdapter`
  no longer needs the old adapter's "N real agents compressed onto 4
  visual slots with priority resolution" logic at all — every real,
  persisted agent *is* its own office character now, 1:1, up to desk
  capacity.
- **`game/scenes/OfficeScene.ts`**: `create()` no longer loops a fixed
  array to spawn exactly 4 characters. It applies whatever
  `officeRosterStore` already knows immediately (crash/reload recovery)
  and reacts to every future change via a new `applyRoster()` method
  that spawns a real `Agent` game object for a roster id never seen
  before, destroys one no longer present, and respawns one whose visual
  identity changed (edited in Team while the Office was open) — never
  reinitializing the whole scene. `inspect()`/`listAgents()`/the debug
  overlay read from the now-dynamic `this.definitions` map instead of
  the deleted static array.
- **`game/simulation/OfficeSimulationService.ts`** (Developer Mode
  fixture — the brief explicitly still allows fixtures here): made
  roster-agnostic (`currentAgentIds()` reads whatever `agentStateMachine`
  currently knows) instead of hardcoding the old 4 character ids, so the
  debug panel stays useful against whatever real agents are on screen.

## 6. Static mocks removed

Deleted outright (not hidden behind a flag, zero remaining references):
`game/agents/RealOfficeAdapter.ts` + its test, `game/agents/realAgentMapping.ts`
(the fixed real-routing-agent → 1-of-4-visual-slots table — the literal
"sprite hardcoded" the brief's central rule is about), `hooks/useRealOfficeSync.ts`,
and the entire `office/` module (`types.ts`, `stateMachine.ts`,
`roleMapping.ts` + tests) — the Stage-1-era DAG-execution-driven office
model, superseded by the domain-driven one. `RoomRegistry.ts`'s one real
dependency on `office/types.ts` (a `RoomId` re-export) was redirected to
its actual source, `game/maps/roomTypes.ts`, before deletion.

`OfficePage` no longer initializes any mocked agents in production — the
Office starts with whatever `useOfficeDomainSync` finds in the real
domain (possibly zero, rendered as a real, playable-but-empty office, not
an EmptyState blocking the canvas). `OfficeSimulationService`'s fixtures
remain reachable **only** behind the Developer Mode toggle, exactly as
before.

## 7. Persistence verified

`tests/python/test_agents_repo.py::test_agent_project_assignment_survives_a_reconnect`:
creates a project and an agent assigned to it against one `Database`
handle, closes it, opens a **fresh** `Database`/`AgentsRepository`
against the same file (simulating closing and reopening AgentMash), and
asserts the assignment is still there — not held only in memory.

## 8. Multiproject support verified

Both layers carry the brief's own "TESTE CRÍTICO" scenario (`Project A:
Agent A, Agent B` / `Project B: Agent C, Agent D`) as an explicit test,
not just incidentally covered:

- Backend: `tests/python/test_agents_repo.py::test_list_by_project_scopes_correctly_across_multiple_projects`.
- Frontend (pure, no Phaser): `game/office-domain/__tests__/buildOfficeAgents.test.ts::"Project A / Project B / All Projects filtering is real, not static"` — asserts `Office(Project A) => [A,B]`, `Office(Project B) => [C,D]`, `Office(All) => [A,B,C,D]` from the exact same real domain data, driven only by `viewMode`/`selectedProjectId`.

## 9. Tests

New/changed this phase:

- Backend: `test_agents_repo.py` (+7 tests: create, update project
  reassignment/unassignment, partial-update discipline, `list_by_project`
  multiproject scoping, reconnect persistence), `test_bridge_agents.py`,
  `test_bridge_teams.py`, `test_bridge_sessions.py` (new files, 13 tests
  total).
- Frontend: `game/office-domain/__tests__/buildOfficeAgents.test.ts` (8,
  including the critical multiproject scenario), `visualProfile.test.ts`
  (6, determinism), `game/agents/__tests__/OfficeDomainAdapter.test.ts`
  (5, new), `AgentStateMachine.test.ts` (rewritten for the desk *pool*
  model — 18, up from 14, including a real overflow-to-lounge case),
  `TeamPage.test.tsx` (rewritten for the functional page — 11, up from
  4), `OfficePage.test.tsx` (+2: real project filter, real
  selected-agent-targeted debug actions), `ProjectsPage.test.tsx`/
  `MemoryPage.test.tsx` unaffected.

## 10. Quality gates

| Gate | Result |
|---|---|
| Python: pytest | **586 passed, 6 skipped** (was 566 at the end of the V2 shell-rebuild prompt — +20 new, 0 regressions) |
| Python: ruff | clean (2 pre-existing, unrelated findings in untracked `scripts/generate_office_*.py`) |
| Python: mypy | clean, 158 source files |
| Frontend: typecheck | clean |
| Frontend: lint | clean |
| Frontend: test | **141 passed** (was 132 — +9 net: several old fixed-roster tests were replaced with pool/dynamic-roster equivalents, plus the new domain-layer and bridge-command test files) |
| Frontend: build | clean |
| Rust: fmt/clippy/test | **not run** — `cargo` is still not on PATH in this environment (same disclosed limitation as every prior phase's report; no Rust file was touched this phase either) |

No test was skipped, disabled, or weakened to make any of this pass.

## 11. Known limitations (disclosed, not hidden)

- **Presence is domain-only, not runtime-driven yet.** No Claude/Codex/API
  runtime exists (explicitly out of scope this phase), so `OfficePresenceState`
  comes only from `Agent.active`/`Agent.status` (the Phase 1 inert default)
  and whether a real `Session` row exists — an agent with no session is
  honestly `AVAILABLE`, never fabricated as busier. Phase 5's job.
- **`WORKSTATION_CAPACITY` is 4** (the map's own 4 authored desk
  positions) — a 5th simultaneously-active agent in one project goes to
  the lounge (a real, tested, non-crashing overflow), not a 5th desk.
  Documented, not hidden; growing it means adding desk points to the
  tilemap, not changing the pool's shape.
- **Only 4 real visual presets exist** (the four spritesheets Estágio 2
  baked) — multiple real agents legitimately share a look, told apart by
  their real name label, not by unique pixel art. The richer
  skin/hair/outfit `AgentVisualProfile` the brief sketches conceptually
  is not implemented (nothing would render it).
- **`session.list` has no live push channel** — Phase 4 polls it every
  15s while the Office is mounted (mirroring the existing provider-health
  poll's own restraint) because no runtime yet emits a session-changed
  event to react to instead. Phase 5, which introduces a real runtime,
  should replace this with a real event.
- **`TeamPage`'s team-membership UI is intentionally minimal** (inline
  add/remove, no drag-and-drop or bulk actions) — functional and
  real-data-only, not polished; the brief's phased plan explicitly treats
  "Polish" as later work.
- `cargo test` still unverified in this environment (carried forward
  from every prior phase's report).

## 12. Legacy remaining

`WorkspacePage`, `ExecutionsPage`, `LearningPage`, and `SettingsPage`
(documented in `docs/agentmash-v2-migration.md` §3d) still use pre-V2
visual patterns and are untouched this phase — out of Phase 4's declared
scope (domain → Office connection), not an oversight.

## 13. Next phase

**Phase 5**, per the brief's own "PREPARAÇÃO PARA PHASE 5": wire a real
runtime (Claude Code first) so `Agent → Session → Claude Code Runtime →
Presence Event → Office animation` becomes real end-to-end, replacing
this phase's domain-only (`Agent.status`/session-existence) presence
derivation with real, event-driven state — without needing to touch the
`Agent`/`Project`/`Team`/`Session` models again, since Phase 1 and this
phase already gave them the shape a real runtime needs (`provider_id`,
`backend_type`, `external_session_id`, `preferred_backend` are all
already there, just unused by anything real yet). Not started; no code
for it exists yet.

---

## Required declarations

```
OFFICE USING STATIC AGENTS: NO
PROJECT FILTERING REAL: YES
AGENT PERSISTENCE REAL: YES
MULTIPROJECT SUPPORT: YES
```
