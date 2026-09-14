-- 0011_task_assignment_fields.sql
--
-- Refactor V2, Phase 1 (docs/refactor-v2-plan.md §4): a `Task` can now be
-- explicitly assigned to an agent and/or a team, and linked to the
-- `Session` that is (or was) executing it. All three are nullable --
-- today's automatic/DAG-routed tasks leave them unset and are entirely
-- unaffected; the DAG-level `PlanStep`/routing system is untouched.

ALTER TABLE tasks ADD COLUMN assigned_agent_id TEXT REFERENCES agents(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN assigned_team_id TEXT REFERENCES teams(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL;
