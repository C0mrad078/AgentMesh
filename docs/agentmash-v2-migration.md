# AgentMash V2 — Migration Plan (Interface Rebuild)

This document is the required deliverable for **AGENTMASH V2 — PROMPT 0**:
freezing V1, auditing the current interface, and bootstrapping the new
shell around the Pixel Office. It is a *separate* document from
`docs/refactor-v2-plan.md` (the backend/domain-model refactor plan from
the previous prompt) — that plan's Phase 0/1 work is now part of the
**V1 baseline** this document freezes and builds the new frontend on top
of. Backend/domain work continues to be tracked there; this document
tracks the frontend rebuild specifically.

## 1. V1 freeze

- Commit `161e733` — "Freeze AgentMash V1 baseline before the V2
  pixel-office rebuild" — contains everything built through Estágio 1-3
  plus Refactor V2 Phase 0-1 (backend domain model).
- Tag `v1-legacy` (annotated) and branch `legacy/v1` both point at that
  commit. V1 remains fully recoverable (`git checkout legacy/v1`) at any
  point during the V2 rebuild.
- Baseline gate at freeze time: **566 passed, 6 skipped** (Python),
  ruff clean (2 pre-existing, unrelated findings in untracked asset
  scripts), mypy clean (158 files), **131 passed** (frontend Vitest, after
  this prompt's own changes below), typecheck/lint/build clean. `cargo
  test` still not runnable in this environment (unchanged limitation).

## 2. The rule this document enforces

> **The V1 interface is not the foundation of V2.** V1 is a technical
> reference only (backend, Tauri/Rust bridge, database, security, tests) —
> never a visual/UX/layout reference. Every interface module defaults to
> **REBUILD** unless it is (a) purely neutral technical infrastructure, or
> (b) — the one exception actually invoked below — already, in substance,
> the exact target artifact the V2 brief describes, not a dashboard
> skin around it.

## 3. Frontend audit: classification

### 3a. REBUILT (the shell — the part the brief calls out explicitly)

| Module | V1 shape | V2 disposition |
|---|---|---|
| `layouts/AppShell.tsx` | Fixed `w-64` `Sidebar` + `h-12` per-page header wrapping a padded content area; Office was the one exception already given edge-to-edge treatment *inside* that shell. | **Rebuilt.** New shell is a `h-9` `TopBar` (brand + connection status) and a `h-12` `BottomNav` (thin strip, all destinations), nothing else — 84px of chrome total, leaving the rest of the window (>90% on any real desktop size) to whatever page is active, Office above all. |
| `layouts/Sidebar.tsx` | Persistent left rail: brand, 6-item nav list, project list, "new project" button. Exactly the "sidebar antiga" the brief names as forbidden. | **Deleted outright** (not hidden behind a flag — `git rm`, zero remaining imports). Its two real behaviors were not lost, they moved: navigation → `BottomNav`; project list/retry/empty-state → the new `ProjectsPage` (§3c). |
| `pages/AgentsPage.tsx` | A grid of `Card`s (name, provider/model, active badge, capability badges) — classic dashboard-card identity. | **Deleted outright.** The brief explicitly forbids reusing this exact pattern for "Team" ("Não utilizar antiga UI de agents. Criar do zero."). Replaced by `pages/TeamPage.tsx` — a plain roster list, not a card grid. |

### 3b. KEPT — the one documented exception, with justification

| Module | Why it's the exception |
|---|---|
| `desktop/src/game/**` (`Game.ts`, `agents/`, `maps/`, `scenes/`, `simulation/`, `systems/`) — the Phaser Pixel Office engine | This is not "old dashboard UI carrying V1 visual identity" — it is, already, the literal artifact V2's own "PIXEL OFFICE ENGINE" section asks to build: a real tilemap/grid/collision system (`NavigationService`, `RoomRegistry`, `OccupancySystem`), real sprites and room objects (desks, sofa, meeting room, recovery room), a `Presence`-shaped pipeline (`RealOfficeAdapter` translates real backend agent/session/provider-health state into `AgentStateMachine` events, which alone decide sprite/animation — the engine never invents state), and zero user-driven character control (no WASD, click-to-move, or joystick anywhere in it — already exactly the brief's "REGRA FUNDAMENTAL"). It took three real, tested stages to build (`GAME_ENGINE.md`, `VIRTUAL_OFFICE.md`) and rebuilding it from scratch would satisfy no requirement in the brief while discarding real, working, already-correct software. Reused as-is. |
| `pages/OfficePage.tsx` / `components/PhaserOffice.tsx` | Already `h-full w-full`, canvas edge-to-edge, every control (zoom, follow, dev-mode drawer, hover tooltip, agent detail panel) rendered as a floating overlay on top of the canvas — never a "widget inside a dashboard card." This already matches the brief's own rule ("painéis aparecem como overlay/drawer... Office não deve ser um widget pequeno dentro de um dashboard") without any change. What *did* need rebuilding was only the shell wrapping it (§3a) — now removed, so the Office is not just visually edge-to-edge but structurally the dominant screen. |
| `components/ConnectionBadge.tsx`, `components/NewProjectDialog.tsx`, `components/EmptyState.tsx`, `components/ErrorBoundary.tsx`, `components/ui/*` (shadcn primitives) | Neutral technical/utility infrastructure per the brief's own exception clause ("ErrorBoundary, generic modal infrastructure, generic hooks... poderá ser considerado individualmente"). A status pill, a form dialog, an empty-state pattern, and unstyled-by-default primitive components (`Button`, `Card`, `Dialog`, `Tabs`...) carry no V1 *product* identity of their own. |
| `stores/*`, `services/api.ts`, `services/bridge.ts`, `hooks/useBridgeSubscription.ts`, `hooks/useRealOfficeSync.ts`, `types/*` | Data/runtime layer, not UI. Explicitly out of scope for a visual rebuild — this is exactly the kind of V1 infrastructure the brief says to keep. |

### 3c. REBUILT — new pages replacing old destinations (this delivery)

| New file | Replaces | Real data, not fake |
|---|---|---|
| `pages/ProjectsPage.tsx` | `Sidebar`'s project list | `useProjectsStore` (real bridge-backed project CRUD) — loading/error/retry/empty states preserved from the old Sidebar's tests, now on a real page. "Abrir Office" selects the project and switches to Office. |
| `pages/TeamPage.tsx` | `AgentsPage`'s card grid | `agentsApi.list()` (real). A plain list (name + role + status dot), matching the brief's own Team mockup shape, not a card grid. `status` is Refactor V2 Phase 1's real, persisted `AgentStatus` column — shown honestly ("Disponível", the inert `idle` default) since nothing computes a live value yet; never fabricated as "Working." |
| `pages/MemoryPage.tsx` | *(nothing — new)* | `memoryApi.list(project_id)`, an endpoint that already existed and was already wired end-to-end but had **zero** frontend consumers before this change. Real records for the selected project; an honest empty state, never a placeholder pretending to be data. |
| `pages/ProvidersPage.tsx` | The "Providers" tab buried inside `SettingsPage` | Promoted to its own top-level destination per the brief's IA. Composes the existing `ProvidersSettings`/`CliProvidersSettings` forms unchanged (real, functional, already correct) — only their *location* changed. The old tab was removed from `SettingsPage` so the same form doesn't exist reachable from two places. |

### 3d. KEPT AS-IS FOR NOW (secondary utility screens, explicitly not in scope for this prompt)

`pages/WorkspacePage.tsx`, `pages/ExecutionsPage.tsx`, `pages/LearningPage.tsx`,
`pages/SettingsPage.tsx` (minus the Providers tab) still use pre-V2 visual
patterns (card/table layouts) and are reachable from `BottomNav` under
their existing labels ("Tarefas", "Execuções", "Aprendizado",
"Config."). This is a **disclosed, deliberate deferral**, not an oversight:
the brief's own phase plan treats "NOVA EXPERIÊNCIA DE PROJECTS/TEAM" as
distinct, later work, and explicitly warns against a "big bang" rewrite
that leaves the app broken across dozens of commits. These four screens
are secondary/administrative, not the product's home or identity (Office
already is, and already was before this prompt) — they will be rebuilt
incrementally in later phases (Domain Connection / Presence / Polish),
each with its own real-data-only, non-card-grid treatment, the same way
Team/Projects/Memory/Providers were handled in this delivery.

## 4. New frontend structure

Reorganized **in place** under `desktop/src/` rather than a parallel
`src-v2/` tree — the entire toolchain (Vite/Vitest/ESLint config, path
aliases, Tailwind setup) stays single-sourced, and the actual blast radius
of this rebuild (§3a/§3c) did not justify duplicating it. `game/`,
`stores/`, `services/`, `types/`, `hooks/` are unchanged in location and
shape (§3b). New/changed shape:

```text
desktop/src/
├── layouts/
│   ├── AppShell.tsx    # rebuilt: TopBar + <page> + BottomNav, no Sidebar
│   ├── TopBar.tsx       # new: brand + connection status + new-project
│   └── BottomNav.tsx    # new: replaces Sidebar's nav list entirely
├── pages/
│   ├── OfficePage.tsx   # kept (§3b) — already V2-shaped
│   ├── ProjectsPage.tsx # new (§3c)
│   ├── TeamPage.tsx     # new (§3c), AgentsPage.tsx deleted
│   ├── MemoryPage.tsx   # new (§3c)
│   ├── ProvidersPage.tsx# new (§3c)
│   ├── WorkspacePage.tsx, ExecutionsPage.tsx, LearningPage.tsx,
│   │   SettingsPage.tsx # kept for now, deferred rebuild (§3d)
├── game/                 # untouched (§3b) — the Pixel Office engine
├── stores/, services/, hooks/, types/  # untouched — data/runtime layer
```

`uiStore.AppPage` gained `"projects" | "team" | "memory" | "providers"`
and dropped `"agents"` (renamed `"team"`); `App.tsx`'s page map updated to
match.

## 5. Home = Office (items 12/13/14 verified, not just asserted)

- `uiStore`'s `activePage` already defaulted to `"office"` before this
  prompt (Estágio 3) and still does — verified unchanged, not re-derived.
- With `Sidebar`/the old header gone, nothing wraps the Office in
  left-rail-plus-header dashboard chrome anymore: `AppShell` renders
  `TopBar` → `<OfficePage/>` (edge-to-edge, `isOffice` branch) → `BottomNav`
  directly. The old interface cannot "load inside" the new Office because
  the component that used to wrap it (`Sidebar`) no longer exists in the
  tree at all.

## 6. Quality gates (this delivery)

| Gate | Result |
|---|---|
| Python: pytest | 566 passed, 6 skipped (unchanged — no backend files touched this prompt) |
| Python: ruff | clean (2 pre-existing, unrelated) |
| Python: mypy | clean, 158 files |
| Frontend: typecheck | clean |
| Frontend: lint | clean |
| Frontend: test | **131 passed** (was 119 before this prompt: -3 for the deleted `Sidebar.test.tsx`, +15 for `ProjectsPage`/`TeamPage`/`MemoryPage`/`BottomNav` new tests) |
| Frontend: build | clean |
| Rust: fmt/clippy/test | not run — `cargo` unavailable in this environment (unchanged, disclosed limitation; no Rust file touched) |

No test was skipped, disabled, or weakened to make this pass.

## 7. OLD UI REUSED: **PARTIAL — disclosed, not hidden**

Being precise instead of giving a single yes/no that would misrepresent
either direction:

- **The shell (Sidebar, per-page header) — NO.** Fully rebuilt, old code
  deleted, zero remaining references.
- **"Team" — NO.** The brief explicitly named this one; `AgentsPage`'s
  card grid is deleted, not adapted.
- **The Pixel Office engine and Office page — YES, deliberately, with the
  justification in §3b.** This is the one case the brief itself allows
  ("Só preserve elemento visual antigo se existir uma justificativa
  técnica excepcional") — it is already the target artifact, not a
  dashboard skin, and discarding it would be pure regression with no
  product benefit.
- **Four secondary utility pages (Workspace/Executions/Learning/Settings)
  — YES, temporarily, explicitly deferred (§3d), not silently kept.** They
  are reachable, functional, and unchanged in visual style; they are
  scheduled for the same treatment Team/Projects/Memory/Providers got,
  in a later phase, so the app never breaks across dozens of commits.

## 8. Known limitations

- `TeamPage`'s status dot reads a real column that nothing computes yet
  (Presence Engine is a later phase) — every agent shows "Disponível"
  until real sessions exist. Documented in the component itself and
  asserted by its own test (`test("never claims an agent is working when
  status is the inert idle default")`).
- `ProjectsPage` does not yet show per-project agent/session counts from
  the brief's own mockup — no bridge command aggregates them yet. Shown
  honestly as name/path/description only.
- `MemoryPage` only reads project-scope memory (the one bridge command
  that exists, `memory.list`) — Global/Agent/Session scopes have real
  backend support (Refactor V2 Phase 1) but no bridge command yet.
- Providers tab duplication was resolved (removed from `SettingsPage`),
  but `SettingsPage`'s "Execuções" tab still duplicates the standalone
  `ExecutionsPage` — not addressed this prompt, deferred to §3d's rebuild.

## 9. Next phase

**Phase 3 — Pixel Office prototype validation.** Since the engine was
kept rather than rebuilt from zero (§3b), this phase's brief-mandated
criterion ("1 map, 3 fake agents, 3 desks, coffee area, lounge, meeting
room, walking/sitting/working/idle") is **already satisfied by the
existing, real, event-driven office** — verified in `GAME_ENGINE.md`/
`VIRTUAL_OFFICE.md` and by `game/**`'s own test suite (this prompt
touched none of it). The next real increment is **Phase 4 (Domain
Connection)**: swapping the office's static 4-character role mapping
(`realAgentMapping.ts`) for something that reflects the *actual* set of
persisted `Team`/`Agent` rows (Refactor V2 Phase 1) per selected project,
so "All Projects / AgentMash / NerdVerso" project-switching in the Office
becomes real. Not started; no code for it exists yet.
