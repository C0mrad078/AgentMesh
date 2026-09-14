-- 0006_teams.sql
--
-- Refactor V2, Phase 1 (docs/refactor-v2-plan.md §4): `Team` is a
-- persistent grouping of agents, optionally scoped to one project (a team
-- can also exist unassigned, e.g. while being set up). Membership is
-- many-to-many via `team_agents` -- an agent could in principle serve more
-- than one team, even though the common case is one.

CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_teams_project_id ON teams(project_id);

CREATE TABLE IF NOT EXISTS team_agents (
    team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    PRIMARY KEY (team_id, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_team_agents_agent_id ON team_agents(agent_id);
