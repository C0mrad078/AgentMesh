-- 0005_agent_fallback_providers.sql
--
-- AgentMash Stage 3, spec section 8/9/44/45: an Agent is a logical role,
-- not the provider that happens to execute it right now. These two
-- columns are the persisted form of `Agent.preferred_provider` /
-- `Agent.fallback_providers` (core/agents/models.py) -- read by the
-- desktop agent panel/tooltip to show "Provider: Claude Code / Fallback
-- from: Codex" when a real `provider.fallback_used`-style event indicates
-- the currently active provider differs from the agent's own preference.

ALTER TABLE agents ADD COLUMN preferred_provider TEXT;
ALTER TABLE agents ADD COLUMN fallback_providers TEXT NOT NULL DEFAULT '[]';
