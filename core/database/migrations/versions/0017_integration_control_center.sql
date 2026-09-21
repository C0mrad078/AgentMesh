-- V3 Marco 3: operational runtime bindings, project quality gates and
-- auditable assisted integration conflicts.
ALTER TABLE runtime_bindings ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1));
ALTER TABLE runtime_bindings ADD COLUMN last_diagnostic TEXT NOT NULL DEFAULT '';
ALTER TABLE runtime_bindings ADD COLUMN last_reconciled_at TEXT;

CREATE TABLE quality_gate_profiles (
 id TEXT PRIMARY KEY,
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 name TEXT NOT NULL,
 is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
 gates TEXT NOT NULL CHECK(json_valid(gates)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(project_id, name)
);
CREATE INDEX idx_quality_gate_profiles_project ON quality_gate_profiles(project_id);

CREATE TABLE integration_conflicts (
 id TEXT PRIMARY KEY,
 mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
 integration_attempt_id TEXT REFERENCES mission_integration_attempts(id) ON DELETE SET NULL,
 status TEXT NOT NULL,
 classification TEXT NOT NULL,
 base_sha TEXT NOT NULL,
 ours_sha TEXT NOT NULL,
 theirs_sha TEXT NOT NULL,
 integration_head TEXT NOT NULL,
 resolution_worktree_id TEXT REFERENCES worktrees(id) ON DELETE SET NULL,
 integrator_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
 reviewer_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
 data TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(data)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX idx_integration_conflicts_mission ON integration_conflicts(mission_id, created_at);

CREATE TABLE integration_conflict_files (
 id TEXT PRIMARY KEY,
 conflict_id TEXT NOT NULL REFERENCES integration_conflicts(id) ON DELETE CASCADE,
 path TEXT NOT NULL,
 classification TEXT NOT NULL,
 base TEXT NOT NULL DEFAULT '',
 ours TEXT NOT NULL DEFAULT '',
 theirs TEXT NOT NULL DEFAULT '',
 stages TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(stages)),
 created_at TEXT NOT NULL
);
CREATE INDEX idx_conflict_files_conflict ON integration_conflict_files(conflict_id);

CREATE TABLE resolution_attempts (
 id TEXT PRIMARY KEY,
 conflict_id TEXT NOT NULL REFERENCES integration_conflicts(id) ON DELETE CASCADE,
 attempt_no INTEGER NOT NULL,
 status TEXT NOT NULL,
 worktree_id TEXT REFERENCES worktrees(id) ON DELETE SET NULL,
 integrator_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
 proposal_artifact_id TEXT REFERENCES mission_artifacts(id) ON DELETE SET NULL,
 commit_sha TEXT,
 strategy TEXT NOT NULL DEFAULT '',
 data TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(data)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(conflict_id, attempt_no)
);

CREATE TABLE resolution_reviews (
 id TEXT PRIMARY KEY,
 conflict_id TEXT NOT NULL REFERENCES integration_conflicts(id) ON DELETE CASCADE,
 attempt_id TEXT NOT NULL REFERENCES resolution_attempts(id) ON DELETE CASCADE,
 reviewer_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
 verdict TEXT NOT NULL,
 findings TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(findings)),
 created_at TEXT NOT NULL
);

CREATE TABLE resolution_decisions (
 id TEXT PRIMARY KEY,
 conflict_id TEXT NOT NULL REFERENCES integration_conflicts(id) ON DELETE CASCADE,
 attempt_id TEXT REFERENCES resolution_attempts(id) ON DELETE SET NULL,
 decision TEXT NOT NULL,
 rationale TEXT NOT NULL DEFAULT '',
 actor_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX idx_resolution_decisions_conflict ON resolution_decisions(conflict_id, created_at);
