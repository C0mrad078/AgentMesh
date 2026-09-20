-- V3 Marco 2. All state is additive and recoverable; main is never touched.
ALTER TABLE worktrees ADD COLUMN mission_id TEXT REFERENCES missions(id);
ALTER TABLE worktrees ADD COLUMN task_id TEXT REFERENCES tasks(id);
ALTER TABLE worktrees ADD COLUMN session_id TEXT REFERENCES sessions(id);
ALTER TABLE worktrees ADD COLUMN workspace_root TEXT;
ALTER TABLE worktrees ADD COLUMN base_sha TEXT;
ALTER TABLE worktrees ADD COLUMN head_sha TEXT;
ALTER TABLE worktrees ADD COLUMN last_error TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS uq_worktrees_mission_task ON worktrees(mission_id, task_id);
CREATE INDEX IF NOT EXISTS idx_worktrees_session ON worktrees(session_id);

CREATE TABLE mission_concurrency_leases (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 task_id TEXT REFERENCES tasks(id), session_id TEXT REFERENCES sessions(id),
 project_id TEXT NOT NULL REFERENCES projects(id), provider TEXT NOT NULL,
 account_id TEXT, expires_at TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(mission_id, task_id), UNIQUE(session_id)
);
CREATE INDEX idx_mission_concurrency_expiry ON mission_concurrency_leases(expires_at);

CREATE TABLE mission_conflict_forecasts (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 task_id TEXT NOT NULL REFERENCES tasks(id), other_task_id TEXT REFERENCES tasks(id),
 data TEXT NOT NULL CHECK(json_valid(data)), created_at TEXT NOT NULL
);

CREATE TABLE mission_integration_attempts (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 task_id TEXT NOT NULL REFERENCES tasks(id), integration_branch TEXT NOT NULL,
 source_branch TEXT NOT NULL, base_sha TEXT NOT NULL, result TEXT NOT NULL,
 commit_sha TEXT, message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);

CREATE TABLE mission_quality_gates (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 task_id TEXT REFERENCES tasks(id), name TEXT NOT NULL, command TEXT NOT NULL CHECK(json_valid(command)),
 exit_code INTEGER NOT NULL, duration_ms INTEGER NOT NULL, summary TEXT NOT NULL,
 passed INTEGER NOT NULL CHECK(passed IN (0,1)), created_at TEXT NOT NULL
);

CREATE TABLE mission_human_approvals (
 id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES missions(id),
 decision TEXT NOT NULL CHECK(decision IN ('approved','corrections_requested','rejected','waiting')),
 rationale TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE TRIGGER worktree_parallel_event AFTER UPDATE ON worktrees
WHEN NEW.mission_id IS NOT NULL BEGIN
 INSERT INTO mission_events(mission_id, entity_type, entity_id, record)
 VALUES(NEW.mission_id, 'worktree', NEW.id,
   json_object('schema_version',1,'status',NEW.status,'branch',NEW.branch_name,'head_sha',NEW.head_sha));
END;
