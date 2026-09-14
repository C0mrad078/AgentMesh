-- 0008_worktrees.sql
--
-- Refactor V2, Phase 1 (docs/refactor-v2-plan.md §4): a `Worktree` is a
-- real `git worktree` checkout under a project's `.agentmash/worktrees/`
-- directory, used so two concurrent sessions never edit the same checkout.
-- Deliberately does not reference `sessions` (created one migration later)
-- to avoid a circular FK -- `sessions.worktree_id` is the one direction of
-- that relationship; a worktree does not need to know which session (if
-- any) currently holds it to exist as a row.

CREATE TABLE IF NOT EXISTS worktrees (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    branch_name TEXT NOT NULL,
    path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    removed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_worktrees_project_id ON worktrees(project_id);
