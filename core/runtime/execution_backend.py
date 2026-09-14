"""The `ExecutionBackend` abstraction (Refactor V2, spec "MODELO UNIFICADO").

Three, and only three, ways an agent's work can actually run:

    SUBSCRIPTION -- an officially-authenticated CLI the user already has a
                    subscription for (Claude Code, Codex CLI, Antigravity).
                    AgentMash spawns the real, official tool; it never
                    stores a password, steals an OAuth token, or reads a
                    browser cookie/session for this.
    SESSION      -- attaching to / resuming a previously-started run of one
                    of those same CLIs, when the CLI itself supports it.
    API          -- a traditional provider API called with a user-supplied
                    API key (Anthropic/OpenAI/Gemini).

This is deliberately a *different* axis from
`core.providers.base.ProviderAccessMethod` (http_api/cli/mock), which
describes how a `ProviderAdapter` *implementation* talks to the world.
`ExecutionBackendType` is the user-facing execution mode; a `Provider` can
have more than one backend at once (e.g. Claude via Subscription *and* via
API, both configured, chosen per-agent), which `ProviderAccessMethod` alone
cannot express since it is a property of one adapter instance, not of a
provider as a whole. See docs/refactor-v2-plan.md §4.
"""

from __future__ import annotations

from enum import Enum


class ExecutionBackendType(str, Enum):
    SUBSCRIPTION = "subscription"
    SESSION = "session"
    API = "api"
