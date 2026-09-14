-- 0010_agent_presence_fields.sql
--
-- Refactor V2, Phase 1 (docs/refactor-v2-plan.md §4): fields the new
-- office/runtime model needs on `Agent` that Stage 1-3 never needed.
-- `status` is added now purely as a place for Phase 8's Presence Engine to
-- write real state later -- nothing in this phase computes or displays it
-- (no UI change), so it is inert schema, not a claimed live signal.
-- `preferred_backend`/`fallback_backend` are the new Subscription/Session/
-- API dimension, orthogonal to the existing `preferred_provider`/
-- `fallback_providers` (Stage 3, which provider) added in migration 0005.

ALTER TABLE agents ADD COLUMN role TEXT NOT NULL DEFAULT '';
ALTER TABLE agents ADD COLUMN avatar TEXT;
ALTER TABLE agents ADD COLUMN status TEXT NOT NULL DEFAULT 'idle';
ALTER TABLE agents ADD COLUMN preferred_backend TEXT;
ALTER TABLE agents ADD COLUMN fallback_backend TEXT;
ALTER TABLE agents ADD COLUMN memory_profile TEXT NOT NULL DEFAULT '{}';
