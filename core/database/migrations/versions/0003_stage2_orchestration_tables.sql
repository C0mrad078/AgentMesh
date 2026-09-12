-- 0003_stage2_orchestration_tables.sql
--
-- Stage 2 adds real AI providers, a real Router/Planner, tools, budgets, and
-- an event bus. This migration adds exactly the tables needed to persist
-- what those need *now* plus what Stage 3 (Reflection Engine / learning)
-- will need to read back later: which model executed, which agent, how
-- long, how much it cost, whether it worked, whether it needed a retry,
-- which routing decision was made and why.

PRAGMA foreign_keys = ON;

-- prompt_versions existed since Stage 1 but without an `active` flag --
-- PromptRegistry needs to know which version of an agent's prompt is live.
ALTER TABLE prompt_versions ADD COLUMN active INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS model_registry (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '[]',
    context_window INTEGER NOT NULL DEFAULT 128000,
    supports_tools INTEGER NOT NULL DEFAULT 0,
    supports_images INTEGER NOT NULL DEFAULT 0,
    supports_files INTEGER NOT NULL DEFAULT 0,
    supports_structured_output INTEGER NOT NULL DEFAULT 0,
    input_cost_per_million_usd REAL NOT NULL DEFAULT 0,
    output_cost_per_million_usd REAL NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, model_id)
);

CREATE TABLE IF NOT EXISTS provider_health (
    provider TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'unknown',
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routing_decisions (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    alternatives TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_routing_decisions_execution_id ON routing_decisions(execution_id);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    step_id TEXT,
    agent_id TEXT,
    tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL DEFAULT '{}',
    result TEXT,
    error TEXT,
    duration_seconds REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_execution_id ON tool_calls(execution_id);

CREATE TABLE IF NOT EXISTS usage_metrics (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    step_id TEXT,
    agent_id TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 1,
    retries INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_metrics_execution_id ON usage_metrics(execution_id);
CREATE INDEX IF NOT EXISTS idx_usage_metrics_created_at ON usage_metrics(created_at);

CREATE TABLE IF NOT EXISTS execution_events (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    task_id TEXT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_events_execution_id ON execution_events(execution_id);

CREATE TABLE IF NOT EXISTS budgets (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',
    max_per_execution_usd REAL,
    daily_limit_usd REAL,
    monthly_limit_usd REAL,
    soft_limit_ratio REAL NOT NULL DEFAULT 0.8,
    currency TEXT NOT NULL DEFAULT 'USD',
    updated_at TEXT NOT NULL,
    UNIQUE(scope)
);
