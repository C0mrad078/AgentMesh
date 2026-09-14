-- 0013_agent_project_assignment.sql
--
-- AgentMash V2, Phase 4 (docs/agentmash-v2-phase4.md): an `Agent` can now
-- be assigned directly to a `Project` -- the primary signal the Pixel
-- Office uses to decide which real agents are visible for a selected
-- project (Team membership, migration 0006, remains a secondary/
-- orthogonal grouping: an agent can belong to a team without that being
-- what puts it in a project's Office, and vice versa).
--
-- `visual_profile` is the real, persisted counterpart of
-- `AgentVisualProfile` -- deliberately just `{"preset": "<key>"}` today
-- (one of the finite set of real, already-baked spritesheets the office
-- can actually render), not the richer skin/hair/outfit breakdown the
-- product brief sketches conceptually: persisting fields nothing renders
-- yet would be exactly the kind of fabricated-looking data this project
-- avoids. Widening it later is additive (the column is already JSON).

ALTER TABLE agents ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE agents ADD COLUMN visual_profile TEXT NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_agents_project_id ON agents(project_id);
