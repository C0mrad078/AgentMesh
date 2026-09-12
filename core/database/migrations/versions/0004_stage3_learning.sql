-- 0004_stage3_learning.sql
--
-- Stage 3 adds a controlled, evidence-based self-improvement system:
-- Reflection Engine, Learning Engine, learned rules with a full lifecycle,
-- a versioned Orchestration Playbook, per-model/agent performance
-- knowledge, expanded (typed, versioned) prompts, expanded project memory
-- with provenance/conflict tracking, and user feedback. Nothing here
-- deletes or replaces Stage 1/2 data -- existing tables are extended with
-- ALTER TABLE, never dropped.

PRAGMA foreign_keys = ON;

-- prompt_versions (Stage 1/2): add typing, authorship, and provenance so a
-- prompt can be one of several kinds (core/agent/planner/router/verifier/
-- reflection/synthesizer), not just an agent's system prompt, and so every
-- version can answer "who changed this, why, and from what".
ALTER TABLE prompt_versions ADD COLUMN prompt_type TEXT NOT NULL DEFAULT 'agent';
ALTER TABLE prompt_versions ADD COLUMN owner_key TEXT;
ALTER TABLE prompt_versions ADD COLUMN author TEXT NOT NULL DEFAULT 'system';
ALTER TABLE prompt_versions ADD COLUMN origin TEXT NOT NULL DEFAULT 'seed';
ALTER TABLE prompt_versions ADD COLUMN reason TEXT NOT NULL DEFAULT '';
ALTER TABLE prompt_versions ADD COLUMN previous_version_id TEXT;
ALTER TABLE prompt_versions ADD COLUMN protected INTEGER NOT NULL DEFAULT 0;

UPDATE prompt_versions SET owner_key = agent_id WHERE owner_key IS NULL AND agent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_prompt_versions_owner_key ON prompt_versions(owner_key);

-- learned_rules (Stage 1 placeholder, never populated): extend into the
-- full Stage 3 rule shape rather than replacing it.
ALTER TABLE learned_rules ADD COLUMN title TEXT NOT NULL DEFAULT '';
ALTER TABLE learned_rules ADD COLUMN category TEXT NOT NULL DEFAULT 'general';
ALTER TABLE learned_rules ADD COLUMN scope_type TEXT NOT NULL DEFAULT 'global';
ALTER TABLE learned_rules ADD COLUMN scope_value TEXT;
ALTER TABLE learned_rules ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE learned_rules ADD COLUMN status TEXT NOT NULL DEFAULT 'candidate';
ALTER TABLE learned_rules ADD COLUMN observations INTEGER NOT NULL DEFAULT 0;
ALTER TABLE learned_rules ADD COLUMN successes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE learned_rules ADD COLUMN failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE learned_rules ADD COLUMN distinct_projects TEXT NOT NULL DEFAULT '[]';
ALTER TABLE learned_rules ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
ALTER TABLE learned_rules ADD COLUMN last_observed_at TEXT;

CREATE INDEX IF NOT EXISTS idx_learned_rules_status ON learned_rules(status);
CREATE INDEX IF NOT EXISTS idx_learned_rules_category ON learned_rules(category);

CREATE TABLE IF NOT EXISTS rule_evidence (
    id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL REFERENCES learned_rules(id) ON DELETE CASCADE,
    execution_id TEXT REFERENCES executions(id) ON DELETE SET NULL,
    project_id TEXT,
    outcome TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rule_evidence_rule_id ON rule_evidence(rule_id);

CREATE TABLE IF NOT EXISTS learning_candidates (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    rule_text TEXT NOT NULL,
    scope_type TEXT NOT NULL DEFAULT 'global',
    scope_value TEXT,
    normalized_key TEXT NOT NULL,
    source_reflection_id TEXT,
    observations INTEGER NOT NULL DEFAULT 1,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    distinct_projects TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'candidate',
    promoted_rule_id TEXT REFERENCES learned_rules(id) ON DELETE SET NULL,
    rejection_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learning_candidates_normalized_key ON learning_candidates(normalized_key);
CREATE INDEX IF NOT EXISTS idx_learning_candidates_status ON learning_candidates(status);

CREATE TABLE IF NOT EXISTS reflections (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    task_id TEXT,
    depth TEXT NOT NULL DEFAULT 'light',
    overall_score REAL NOT NULL DEFAULT 0.5,
    findings TEXT NOT NULL DEFAULT '[]',
    successful_patterns TEXT NOT NULL DEFAULT '[]',
    problems TEXT NOT NULL DEFAULT '[]',
    improvement_candidates TEXT NOT NULL DEFAULT '[]',
    routing_feedback TEXT NOT NULL DEFAULT '[]',
    prompt_feedback TEXT NOT NULL DEFAULT '[]',
    cost_feedback TEXT NOT NULL DEFAULT '[]',
    context_feedback TEXT NOT NULL DEFAULT '[]',
    deterministic_evidence TEXT NOT NULL DEFAULT '{}',
    ai_narrative TEXT,
    reflection_cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reflections_execution_id ON reflections(execution_id);

CREATE TABLE IF NOT EXISTS playbooks (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    name TEXT NOT NULL,
    conditions TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    origin TEXT NOT NULL DEFAULT 'seed',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS playbook_versions (
    id TEXT PRIMARY KEY,
    playbook_id TEXT NOT NULL REFERENCES playbooks(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    strategy TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.5,
    active INTEGER NOT NULL DEFAULT 1,
    reason TEXT NOT NULL DEFAULT '',
    observations INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_playbook_versions_playbook_id ON playbook_versions(playbook_id);

CREATE TABLE IF NOT EXISTS model_performance (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    task_category TEXT NOT NULL DEFAULT 'general',
    risk TEXT NOT NULL DEFAULT 'low',
    executions INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    verified_successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    review_rejections INTEGER NOT NULL DEFAULT 0,
    total_latency_seconds REAL NOT NULL DEFAULT 0,
    total_input_tokens INTEGER NOT NULL DEFAULT 0,
    total_output_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0,
    total_iterations INTEGER NOT NULL DEFAULT 0,
    latency_samples TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL,
    UNIQUE(provider, model, agent_id, task_category, risk)
);

CREATE TABLE IF NOT EXISTS prompt_evaluations (
    id TEXT PRIMARY KEY,
    prompt_version_id TEXT NOT NULL REFERENCES prompt_versions(id) ON DELETE CASCADE,
    baseline_version_id TEXT REFERENCES prompt_versions(id) ON DELETE SET NULL,
    regression_pass INTEGER NOT NULL DEFAULT 0,
    regression_results TEXT NOT NULL DEFAULT '[]',
    verdict TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompt_evaluations_prompt_version_id ON prompt_evaluations(prompt_version_id);

CREATE TABLE IF NOT EXISTS prompt_regression_cases (
    id TEXT PRIMARY KEY,
    target TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_feedback (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    rating TEXT NOT NULL,
    feedback_type TEXT,
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_feedback_execution_id ON user_feedback(execution_id);

-- project_memories (Stage 1): add provenance, confidence, and validity so
-- memory can be superseded instead of silently duplicated. The Stage 1
-- unique index enforced exactly one row per (project_id, key) forever,
-- which is incompatible with keeping superseded history -- replace it with
-- a partial unique index that only constrains the currently-valid row.
DROP INDEX IF EXISTS uq_project_memories_project_key;

ALTER TABLE project_memories ADD COLUMN category TEXT NOT NULL DEFAULT 'other';
ALTER TABLE project_memories ADD COLUMN confidence REAL NOT NULL DEFAULT 0.7;
ALTER TABLE project_memories ADD COLUMN provenance TEXT NOT NULL DEFAULT '{}';
ALTER TABLE project_memories ADD COLUMN valid_from TEXT;
ALTER TABLE project_memories ADD COLUMN valid_until TEXT;
ALTER TABLE project_memories ADD COLUMN superseded_by TEXT;

UPDATE project_memories SET valid_from = created_at WHERE valid_from IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_memories_active_key
    ON project_memories(project_id, key) WHERE valid_until IS NULL;

CREATE TABLE IF NOT EXISTS memory_conflicts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    old_memory_id TEXT NOT NULL,
    new_memory_id TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_conflicts_project_id ON memory_conflicts(project_id);

CREATE TABLE IF NOT EXISTS learning_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'learning_engine',
    evidence TEXT NOT NULL DEFAULT '{}',
    previous_state TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learning_events_created_at ON learning_events(created_at);
CREATE INDEX IF NOT EXISTS idx_learning_events_target ON learning_events(target_type, target_id);

CREATE TABLE IF NOT EXISTS context_metrics (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    agent_id TEXT,
    files_count INTEGER NOT NULL DEFAULT 0,
    bytes_total INTEGER NOT NULL DEFAULT 0,
    file_paths TEXT NOT NULL DEFAULT '[]',
    files_used TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_context_metrics_execution_id ON context_metrics(execution_id);

CREATE TABLE IF NOT EXISTS learning_policy (
    id TEXT PRIMARY KEY DEFAULT 'global',
    mode TEXT NOT NULL DEFAULT 'assisted',
    minimum_observations_for_activation INTEGER NOT NULL DEFAULT 5,
    minimum_confidence REAL NOT NULL DEFAULT 0.75,
    auto_apply_categories TEXT NOT NULL DEFAULT '["playbook"]',
    requires_approval_categories TEXT NOT NULL DEFAULT '["prompt", "routing", "verification"]',
    max_changes_per_day INTEGER NOT NULL DEFAULT 5,
    rollback_threshold REAL NOT NULL DEFAULT 0.2,
    updated_at TEXT NOT NULL
);
