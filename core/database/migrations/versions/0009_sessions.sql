-- 0009_sessions.sql
--
-- Refactor V2, Phase 1 (docs/refactor-v2-plan.md §4): `Session` is a real
-- execution turn -- distinct from `executions` (the DAG-run bookkeeping
-- for a single `Task`, unchanged and untouched by this migration). A
-- Session belongs to exactly one agent and project, runs through exactly
-- one provider/backend/account combination, and may optionally be tied to
-- a task and a worktree. How the engine reconciles `sessions` with
-- `executions` is a Phase 2/3 wiring question -- this migration only adds
-- the durable record.
--
-- Created last among Phase 1's new tables so every table it references
-- (agents, projects, providers, provider_accounts, tasks, worktrees)
-- already exists.

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE RESTRICT,
    backend_type TEXT NOT NULL,
    account_id TEXT REFERENCES provider_accounts(id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    worktree_id TEXT REFERENCES worktrees(id) ON DELETE SET NULL,
    external_session_id TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    started_at TEXT,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent_id ON sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_project_id ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_task_id ON sessions(task_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
