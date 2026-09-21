-- Resolution worktrees have their own lifecycle and never reuse a task lease.
ALTER TABLE resolution_attempts ADD COLUMN resolution_path TEXT;
ALTER TABLE resolution_attempts ADD COLUMN resolution_branch TEXT;
