-- V3 Marco 2.1: provider installations/accounts expose independent capacity slots.
CREATE TABLE runtime_bindings (
 id TEXT PRIMARY KEY,
 provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
 account_id TEXT REFERENCES provider_accounts(id) ON DELETE SET NULL,
 label TEXT NOT NULL,
 configured_capacity INTEGER NOT NULL CHECK(configured_capacity BETWEEN 1 AND 32),
 observed_capacity INTEGER NOT NULL CHECK(observed_capacity BETWEEN 0 AND 32),
 reserved_slots INTEGER NOT NULL DEFAULT 0 CHECK(reserved_slots >= 0),
 health TEXT NOT NULL DEFAULT 'unknown',
 backoff_until TEXT,
 metadata TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(provider_id, account_id, label)
);
CREATE INDEX idx_runtime_bindings_provider ON runtime_bindings(provider_id);

ALTER TABLE agents ADD COLUMN runtime_binding_id TEXT REFERENCES runtime_bindings(id) ON DELETE SET NULL;
ALTER TABLE agents ADD COLUMN max_sessions INTEGER NOT NULL DEFAULT 1 CHECK(max_sessions BETWEEN 1 AND 8);
ALTER TABLE sessions ADD COLUMN runtime_binding_id TEXT REFERENCES runtime_bindings(id) ON DELETE SET NULL;
ALTER TABLE sessions ADD COLUMN process_id TEXT;
ALTER TABLE sessions ADD COLUMN process_started_at TEXT;
ALTER TABLE sessions ADD COLUMN process_exit_code INTEGER;
ALTER TABLE mission_concurrency_leases ADD COLUMN runtime_binding_id TEXT REFERENCES runtime_bindings(id) ON DELETE SET NULL;
CREATE INDEX idx_agents_runtime_binding ON agents(runtime_binding_id);
CREATE INDEX idx_sessions_runtime_binding ON sessions(runtime_binding_id);
CREATE INDEX idx_leases_runtime_binding ON mission_concurrency_leases(runtime_binding_id);

INSERT OR IGNORE INTO runtime_bindings(id, provider_id, label, configured_capacity, observed_capacity, reserved_slots, health, metadata, created_at, updated_at)
SELECT 'runtime_' || name || '_cli', id, display_name || ' CLI', 4, 4, 0, 'unknown', '{}', datetime('now'), datetime('now')
FROM providers WHERE name IN ('openai', 'claude');

UPDATE agents SET runtime_binding_id = CASE provider
 WHEN 'codex_cli' THEN 'runtime_openai_cli'
 WHEN 'claude_code_cli' THEN 'runtime_claude_cli'
 ELSE NULL END
WHERE runtime_binding_id IS NULL;
