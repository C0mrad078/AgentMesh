-- 0007_providers.sql
--
-- Refactor V2, Phase 1 (docs/refactor-v2-plan.md §4): the persisted
-- "Provider is not Backend" model. `providers` is a small, mostly-static
-- catalog (Claude/OpenAI/Google today); `provider_accounts` lets a
-- provider have zero or more signed-in accounts (e.g. two Google
-- accounts); `provider_backends` records, per provider, which of the
-- three execution modes (subscription/session/api) is configured and its
-- last-known connection state -- the persisted half of what
-- `core.providers.provider_manager.ProviderManager` already discovers live
-- for CLI providers. This table does not replace that live discovery; it
-- is the durable record the Providers UI (Phase 9) reads on startup before
-- a fresh diagnostic completes, and what `ProviderAccount`/`Session` rows
-- reference.

CREATE TABLE IF NOT EXISTS providers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_accounts (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    external_identifier TEXT,
    status TEXT NOT NULL DEFAULT 'disconnected',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_provider_accounts_provider_id ON provider_accounts(provider_id);

CREATE TABLE IF NOT EXISTS provider_backends (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    backend_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'not_installed',
    detail TEXT,
    config TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (provider_id, backend_type)
);

CREATE INDEX IF NOT EXISTS idx_provider_backends_provider_id ON provider_backends(provider_id);

-- Seed the three providers the brief names explicitly. Rows are looked up
-- by `name` (stable) everywhere else, never by this seed's `id` literal.
INSERT INTO providers (id, name, display_name, created_at, updated_at)
VALUES
    ('provider_claude', 'claude', 'Claude', datetime('now'), datetime('now')),
    ('provider_openai', 'openai', 'OpenAI', datetime('now'), datetime('now')),
    ('provider_google', 'google', 'Google', datetime('now'), datetime('now'))
ON CONFLICT (name) DO NOTHING;
