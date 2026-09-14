-- 0012_memory_scopes.sql
--
-- Refactor V2, Phase 1 (docs/refactor-v2-plan.md §4): generalizes
-- `project_memories` from project-only to the brief's four levels (global/
-- project/agent/session). SQLite cannot drop a `NOT NULL` constraint with
-- `ALTER TABLE ADD COLUMN`, so this does the standard SQLite
-- create-copy-drop-rename rebuild instead -- still a strictly additive
-- *migration* (a new numbered file; 0001-0011 are untouched), it just
-- can't be expressed as a bare `ADD COLUMN` this one time. Every existing
-- row is preserved with `scope='project'` and its original `project_id`,
-- so every current caller (`core.memory.store.SqliteMemoryStore`,
-- `ProjectMemoriesRepository`) keeps working unchanged against unscoped
-- calls until Phase 5 teaches them about the other three scopes.
--
-- The single `(project_id, key) WHERE valid_until IS NULL` uniqueness
-- invariant from migration 0002/0004 (one active fact per key, chosen to
-- close a real INSERT-race bug -- see that migration's own comment) is
-- replaced with one partial unique index per scope, since "active key"
-- now means something different depending on what the memory is scoped
-- to: one active fact per (project, key) for project-scope, per
-- (agent, key) for agent-scope, per (session, key) for session-scope, and
-- per (key) alone for global-scope.

PRAGMA foreign_keys = OFF;

CREATE TABLE project_memories_new (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'project',
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    agent_id TEXT REFERENCES agents(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'fact',
    key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '{}',
    importance REAL NOT NULL DEFAULT 0.5,
    category TEXT NOT NULL DEFAULT 'other',
    confidence REAL NOT NULL DEFAULT 0.7,
    provenance TEXT NOT NULL DEFAULT '{}',
    valid_from TEXT,
    valid_until TEXT,
    superseded_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO project_memories_new (
    id, scope, project_id, agent_id, session_id, kind, key, value, importance,
    category, confidence, provenance, valid_from, valid_until, superseded_by,
    created_at, updated_at
)
SELECT
    id, 'project', project_id, NULL, NULL, kind, key, value, importance,
    category, confidence, provenance, valid_from, valid_until, superseded_by,
    created_at, updated_at
FROM project_memories;

DROP TABLE project_memories;
ALTER TABLE project_memories_new RENAME TO project_memories;

PRAGMA foreign_keys = ON;

CREATE INDEX IF NOT EXISTS idx_project_memories_project_id ON project_memories(project_id);
CREATE INDEX IF NOT EXISTS idx_project_memories_agent_id ON project_memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_project_memories_session_id ON project_memories(session_id);
CREATE INDEX IF NOT EXISTS idx_project_memories_scope ON project_memories(scope);

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_memories_active_key_project
    ON project_memories(project_id, key) WHERE valid_until IS NULL AND scope = 'project';
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_memories_active_key_agent
    ON project_memories(agent_id, key) WHERE valid_until IS NULL AND scope = 'agent';
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_memories_active_key_session
    ON project_memories(session_id, key) WHERE valid_until IS NULL AND scope = 'session';
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_memories_active_key_global
    ON project_memories(key) WHERE valid_until IS NULL AND scope = 'global';
