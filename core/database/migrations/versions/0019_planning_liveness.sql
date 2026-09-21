ALTER TABLE tasks ADD COLUMN waiting_reason TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_tasks_waiting_reason ON tasks(status, waiting_reason);
