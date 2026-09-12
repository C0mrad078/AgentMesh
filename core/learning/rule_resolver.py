"""Rule Resolver: turns the set of active/pinned learned rules into a
concrete effect the Router and Planner can use, resolving conflicts along
the way.

Rule hierarchy (highest wins when two rules would apply the same effect to
the same target):

    Core Safety Rules      (hardcoded in the engine/verifier, never here)
        > User Pinned Rules
        > Project-scoped Rules
        > Learned Rules (global/task_type/language/framework/provider/agent/tool)
        > Default Playbook (no explicit rule -- Planner/Router fall back)

A rule's *effect* is a small structured payload stored in `learned_rules
.action` (set once, at promotion time, by `LearningEngine`) rather than
free text the Router would have to parse -- see `core.learning.models` for
the promotion path. Supported effects: `prefer_agent`, `avoid_agent`,
`require_review`. Anything else is informational only (surfaced to the UI,
no automatic behavioral effect) -- this keeps the Router's use of learned
rules auditable and bounded, per the "aprendizado não deve dominar" rule.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.database.repositories.learned_rules_repo import LearnedRulesRepository
from core.learning.models import RulePriority, priority_rank

_SCOPE_PRIORITY_MAP = {
    "global": 0,
    "language": 1,
    "framework": 1,
    "provider": 1,
    "task_type": 2,
    "tool": 2,
    "agent": 3,
    "project": 4,
}


@dataclass(frozen=True)
class RoutingAdjustment:
    agent_id: str
    delta: float
    reason: str
    rule_id: str


class RuleResolver:
    def __init__(self, rules_repo: LearnedRulesRepository) -> None:
        self._rules_repo = rules_repo

    def _matches_scope(
        self, rule: dict, *, category: str | None, project_id: str | None,
        provider: str | None, agent_id: str | None,
    ) -> bool:
        scope_type = rule["scope_type"]
        if scope_type == "global":
            return True
        target = {
            "task_type": category, "project": project_id, "provider": provider,
            "agent": agent_id,
        }.get(scope_type)
        return target is not None and target == rule["scope_value"]

    def _specificity_key(self, rule: dict) -> tuple:
        return (
            1 if rule["pinned"] else 0,
            priority_rank(RulePriority(rule["priority"])),
            _SCOPE_PRIORITY_MAP.get(rule["scope_type"], 0),
            rule["confidence"],
            rule["last_observed_at"] or rule["updated_at"] or "",
        )

    async def applicable_rules(
        self, *, category: str | None = None, project_id: str | None = None,
        provider: str | None = None, agent_id: str | None = None,
    ) -> list[dict]:
        all_rules = await self._rules_repo.list_active_and_pinned()
        matched = [
            r for r in all_rules
            if self._matches_scope(r, category=category, project_id=project_id, provider=provider, agent_id=agent_id)
        ]
        matched.sort(key=self._specificity_key, reverse=True)
        return matched

    async def routing_adjustments(
        self, *, category: str | None, project_id: str | None, provider: str | None = None,
    ) -> list[RoutingAdjustment]:
        """Return one adjustment per agent a rule targets. When multiple
        rules target the *same* agent with the same effect, only the
        highest-ranked one (per `_specificity_key`) is applied -- this is
        the conflict resolution: specificity/priority/confidence/recency
        decide, not "most rules wins"."""
        rules = await self.applicable_rules(category=category, project_id=project_id, provider=provider)
        best_per_agent: dict[str, dict] = {}
        for rule in rules:
            action = rule.get("action") or {}
            effect = action.get("effect")
            target_agent = action.get("agent_id")
            if effect not in ("prefer_agent", "avoid_agent") or not target_agent:
                continue
            if target_agent not in best_per_agent:
                best_per_agent[target_agent] = rule

        adjustments: list[RoutingAdjustment] = []
        for agent_id, rule in best_per_agent.items():
            action = rule["action"]
            magnitude = float(action.get("magnitude", 1.0))
            sign = 1.0 if action["effect"] == "prefer_agent" else -1.0
            adjustments.append(
                RoutingAdjustment(
                    agent_id=agent_id, delta=sign * magnitude,
                    reason=f"regra aprendida: {rule['title']}", rule_id=rule["id"],
                )
            )
        return adjustments

    async def requires_independent_review(
        self, *, category: str | None, project_id: str | None,
    ) -> list[str]:
        """Rules with effect `require_review` matching this context --
        surfaced to the Planner so it can insert a review step, mirroring
        the built-in high/critical-risk review-step behavior."""
        rules = await self.applicable_rules(category=category, project_id=project_id)
        reasons = []
        for rule in rules:
            if (rule.get("action") or {}).get("effect") == "require_review":
                reasons.append(rule["title"])
        return reasons
