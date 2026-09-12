"""Learning Engine.

    Reflection -> Candidate Learning -> Deduplication -> Evidence Evaluation
        -> Confidence Update -> Rule State

A single reflection's finding never jumps straight to an active rule (see
`core.learning.models.PROMOTABLE_STATUSES`): it starts as a `candidate`,
accumulates `observing` evidence across executions, and is only promoted
to `active` once it clears both `minimum_observations_for_activation` and
`minimum_confidence` from the current `LearningPolicy` -- and even then,
only when the policy's mode/category rules allow *automatic* promotion;
otherwise it is left ready for a human to approve via `approve_candidate`.

Every state transition that changes live behavior (a rule going active, a
rule being deprecated/rolled back, a prompt version being activated) is
recorded in `learning_events` (see `core.database.repositories
.learning_events_repo`) and is throttled by `LearningRateLimiter` -- this
is the "Learning Rate Limit" / "evitar instabilidade" requirement.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.database.repositories.learned_rules_repo import LearnedRulesRepository
from core.database.repositories.learning_candidates_repo import LearningCandidatesRepository
from core.database.repositories.learning_events_repo import LearningEventsRepository
from core.database.repositories.rule_evidence_repo import RuleEvidenceRepository
from core.learning.confidence import calculate_confidence
from core.learning.dedup import find_best_match, normalize
from core.learning.models import (
    PROMOTABLE_STATUSES,
    ConfidenceInputs,
    ImprovementCandidate,
    LearningMode,
    LearningPolicySettings,
    RuleCategory,
    RuleStatus,
)
from core.learning.policy import LearningPolicyManager, LearningRateLimiter
from core.learning.safety import SafetyValidator

_DEFAULT_PRIORITY_BY_CATEGORY: dict[RuleCategory, str] = {
    RuleCategory.SAFETY: "critical",
    RuleCategory.VERIFICATION: "high",
    RuleCategory.ERROR_HANDLING: "high",
}


@dataclass(frozen=True)
class CandidateOutcome:
    candidate_id: str
    status: str
    confidence: float
    promoted_rule_id: str | None = None
    rejected_reason: str | None = None


def _infer_rule_action(*, category: RuleCategory, scope_type: str, scope_value: str | None, rule_text: str) -> dict:
    text = rule_text.lower()
    negation_markers = ("não utilizar", "não usar", "evitar", "avoid", "not use", "desnecess")
    if scope_type == "agent" and scope_value:
        is_negative = any(marker in text for marker in negation_markers)
        return {"effect": "avoid_agent" if is_negative else "prefer_agent", "agent_id": scope_value, "magnitude": 1.0}
    if category == RuleCategory.VERIFICATION or "revis" in text or "review" in text:
        return {"effect": "require_review"}
    return {"effect": "note"}


class LearningEngine:
    def __init__(
        self,
        candidates_repo: LearningCandidatesRepository,
        rules_repo: LearnedRulesRepository,
        evidence_repo: RuleEvidenceRepository,
        events_repo: LearningEventsRepository,
        policy_manager: LearningPolicyManager,
        *,
        safety: SafetyValidator | None = None,
        rate_limiter: LearningRateLimiter | None = None,
    ) -> None:
        self._candidates = candidates_repo
        self._rules = rules_repo
        self._evidence = evidence_repo
        self._events = events_repo
        self._policy_manager = policy_manager
        self._safety = safety or SafetyValidator()
        self._rate_limiter = rate_limiter or LearningRateLimiter(events_repo)

    async def process_candidate(
        self,
        candidate: ImprovementCandidate,
        *,
        project_id: str | None,
        reflection_id: str | None,
        execution_id: str | None = None,
    ) -> CandidateOutcome | None:
        verdict = self._safety.validate(candidate)
        if not verdict.allowed:
            await self._events.record(
                event_type="candidate_rejected_safety", target_type="candidate", target_id="n/a",
                actor="learning_engine", evidence={"title": candidate.title, "reason": verdict.reason},
            )
            return None

        normalized_key = normalize(
            category=candidate.category.value, scope_type=candidate.scope.value,
            scope_value=candidate.scope_value, rule_text=candidate.rule_text,
        )

        already_promoted = await self._candidates.find_promoted_by_normalized_key(normalized_key)
        if already_promoted is not None and already_promoted["promoted_rule_id"]:
            rule_id = already_promoted["promoted_rule_id"]
            await self.record_rule_outcome(
                rule_id, execution_id=execution_id, project_id=project_id, success=True,
            )
            rule = await self._rules.get(rule_id)
            confidence = rule["confidence"] if rule else already_promoted["confidence"]
            return CandidateOutcome(
                candidate_id=already_promoted["id"], status="promoted", confidence=confidence,
                promoted_rule_id=rule_id,
            )

        existing = await self._candidates.find_by_normalized_key(normalized_key)
        if existing is None:
            pending = await self._candidates.list_pending()
            same_bucket = [
                c for c in pending
                if c["category"] == candidate.category.value and c["scope_type"] == candidate.scope.value
            ]
            existing = find_best_match(candidate.rule_text, same_bucket)

        if existing is None:
            confidence = calculate_confidence(
                ConfidenceInputs(observations=1, successes=1, failures=0, distinct_projects=1)
            )
            row = await self._candidates.create(
                category=candidate.category.value, title=candidate.title, rule_text=candidate.rule_text,
                scope_type=candidate.scope.value, scope_value=candidate.scope_value,
                normalized_key=normalized_key, source_reflection_id=reflection_id,
                confidence=confidence, project_id=project_id,
            )
            await self._events.record(
                event_type="candidate_created", target_type="candidate", target_id=row["id"],
                evidence={"title": candidate.title, "confidence": confidence},
            )
        else:
            projected_projects = set(existing["distinct_projects"])
            if project_id:
                projected_projects.add(project_id)
            confidence = calculate_confidence(ConfidenceInputs(
                observations=existing["observations"] + 1, successes=existing["successes"] + 1,
                failures=existing["failures"], distinct_projects=max(1, len(projected_projects)),
            ))
            row = await self._candidates.record_observation(
                existing["id"], success=True, confidence=confidence, project_id=project_id,
            )
            await self._events.record(
                event_type="candidate_observed", target_type="candidate", target_id=row["id"],
                evidence={"observations": row["observations"], "confidence": confidence},
            )

        return await self._finalize_candidate_outcome(row, project_id=project_id)

    async def _finalize_candidate_outcome(self, row: dict, *, project_id: str | None) -> CandidateOutcome:
        policy = await self._policy_manager.get()
        eligible = (
            RuleStatus(row["status"]) in PROMOTABLE_STATUSES
            and row["observations"] >= policy.minimum_observations_for_activation
            and row["confidence"] >= policy.minimum_confidence
        )
        if not eligible:
            return CandidateOutcome(candidate_id=row["id"], status=row["status"], confidence=row["confidence"])

        category = row["category"]
        can_auto_apply = await self._can_auto_promote(category, policy)
        if not can_auto_apply:
            await self._events.record(
                event_type="candidate_ready_for_review", target_type="candidate", target_id=row["id"],
                evidence={"confidence": row["confidence"], "observations": row["observations"]},
            )
            return CandidateOutcome(candidate_id=row["id"], status=row["status"], confidence=row["confidence"])

        rule = await self._promote(row)
        return CandidateOutcome(
            candidate_id=row["id"], status="promoted", confidence=row["confidence"], promoted_rule_id=rule["id"],
        )

    async def record_event(
        self, *, event_type: str, target_type: str, target_id: str, evidence: dict | None = None,
        actor: str = "learning_engine",
    ) -> None:
        """Thin passthrough so callers outside this module (e.g.
        `PostExecutionPipeline`) never need their own direct
        `LearningEventsRepository` dependency just to log an event --
        every learning-related mutation is auditable through one place."""
        await self._events.record(
            event_type=event_type, target_type=target_type, target_id=target_id, actor=actor,
            evidence=evidence or {},
        )

    async def can_auto_apply(self, category: str) -> bool:
        """Public entry point for callers outside the candidate lifecycle
        (e.g. `PostExecutionPipeline` deciding whether a prompt proposal
        may activate automatically) that need the same mode/category/rate
        -limit gating `_finalize_candidate_outcome` applies to rules."""
        policy = await self._policy_manager.get()
        return await self._can_auto_promote(category, policy)

    async def _can_auto_promote(self, category: str, policy: LearningPolicySettings) -> bool:
        if policy.mode == LearningMode.MANUAL:
            return False
        if category in policy.requires_approval_categories:
            return False
        if RuleCategory(category) in (RuleCategory.VERIFICATION, RuleCategory.SAFETY, RuleCategory.ERROR_HANDLING):
            return False
        if policy.mode == LearningMode.ASSISTED and category not in policy.auto_apply_categories:
            return False
        return await self._rate_limiter.has_budget(policy)

    async def _promote(self, candidate_row: dict) -> dict:
        category = RuleCategory(candidate_row["category"])
        action = _infer_rule_action(
            category=category, scope_type=candidate_row["scope_type"],
            scope_value=candidate_row["scope_value"], rule_text=candidate_row["rule_text"],
        )
        rule = await self._rules.create(
            title=candidate_row["title"], category=category.value, rule_text=candidate_row["rule_text"],
            scope_type=candidate_row["scope_type"], scope_value=candidate_row["scope_value"],
            priority=_DEFAULT_PRIORITY_BY_CATEGORY.get(category, "normal"),
            confidence=candidate_row["confidence"], observations=candidate_row["observations"],
            successes=candidate_row["successes"], failures=candidate_row["failures"],
            distinct_projects=candidate_row["distinct_projects"], status=RuleStatus.ACTIVE.value,
            origin="learning_engine",
        )
        await self._rules.update_action(rule["id"], action)
        await self._candidates.mark_promoted(candidate_row["id"], rule["id"])
        await self._events.record(
            event_type="rule_activated", target_type="rule", target_id=rule["id"],
            evidence={"confidence": rule["confidence"], "observations": rule["observations"], "action": action},
        )
        return rule

    async def approve_candidate(self, candidate_id: str) -> dict:
        row = await self._candidates.get(candidate_id)
        if row is None:
            raise ValueError(f"Candidate '{candidate_id}' not found.")
        rule = await self._promote(row)
        await self._events.record(
            event_type="rule_activated", target_type="rule", target_id=rule["id"], actor="user",
            evidence={"approved_from_candidate": candidate_id},
        )
        return rule

    async def reject_candidate(self, candidate_id: str, *, reason: str) -> None:
        await self._candidates.mark_rejected(candidate_id, reason=reason)
        await self._events.record(
            event_type="candidate_rejected", target_type="candidate", target_id=candidate_id,
            actor="user", evidence={"reason": reason},
        )

    async def record_rule_outcome(
        self, rule_id: str, *, execution_id: str | None, project_id: str | None, success: bool,
    ) -> None:
        """Feedback loop for an already-active rule: an execution where the
        rule's routing effect was applied either supports or contradicts
        it. Confidence is recomputed from the accumulated evidence, and a
        rule whose recent evidence turns sharply negative is deprecated
        automatically (Automatic Rollback) when the policy allows it."""
        rule = await self._rules.get(rule_id)
        if rule is None:
            return
        await self._evidence.record(
            rule_id, execution_id=execution_id, project_id=project_id,
            outcome="supports" if success else "contradicts",
        )
        observations = rule["observations"] + 1
        successes = rule["successes"] + (1 if success else 0)
        failures = rule["failures"] + (0 if success else 1)
        recent = await self._evidence.list_for_rule(rule_id)
        contradicting_recent = sum(1 for e in recent[:10] if e["outcome"] == "contradicts")
        confidence = calculate_confidence(ConfidenceInputs(
            observations=observations, successes=successes, failures=failures,
            distinct_projects=len(set(rule["distinct_projects"] + ([project_id] if project_id else []))),
            contradicting_recent_evidence=contradicting_recent,
        ))
        await self._rules.update_confidence(
            rule_id, confidence=confidence, observations=observations, successes=successes, failures=failures,
        )

        policy = await self._policy_manager.get()
        failure_rate = failures / observations if observations else 0.0
        if (
            policy.mode != LearningMode.MANUAL
            and observations >= 5
            and failure_rate >= (1.0 - policy.rollback_threshold)
            and not rule["pinned"]
        ):
            await self.rollback_rule(rule_id, reason="automatic rollback: failure rate exceeded policy threshold")

    async def rollback_rule(self, rule_id: str, *, reason: str) -> None:
        rule = await self._rules.get(rule_id)
        if rule is None:
            return
        await self._rules.update_status(rule_id, RuleStatus.DEPRECATED.value)
        await self._events.record(
            event_type="rule_rolled_back", target_type="rule", target_id=rule_id,
            evidence={"reason": reason}, previous_state={"status": rule["status"]},
        )

    async def set_pinned(self, rule_id: str, pinned: bool, *, actor: str = "user") -> None:
        await self._rules.set_pinned(rule_id, pinned)
        await self._events.record(
            event_type="rule_pinned" if pinned else "rule_unpinned", target_type="rule",
            target_id=rule_id, actor=actor,
        )

    async def create_user_rule(
        self, *, title: str, category: str, rule_text: str, scope_type: str, scope_value: str | None, priority: str,
    ) -> dict:
        action = _infer_rule_action(
            category=RuleCategory(category), scope_type=scope_type, scope_value=scope_value, rule_text=rule_text,
        )
        rule = await self._rules.create_user_rule(
            title=title, category=category, rule_text=rule_text, scope_type=scope_type,
            scope_value=scope_value, priority=priority,
        )
        await self._rules.update_action(rule["id"], action)
        await self._events.record(
            event_type="user_rule_created", target_type="rule", target_id=rule["id"], actor="user",
        )
        return rule
