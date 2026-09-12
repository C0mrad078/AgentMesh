"""Post-Execution Pipeline.

    Execution -> Verification -> Result -> Metrics Finalization
        -> Reflection Trigger -> Reflection Engine -> Learning Candidates
        -> Rule Evaluation -> Prompt Evaluation -> Playbook Update
        -> Model Performance Update

Run once per completed/failed/partial/cancelled execution, *after* the
result has already been returned to the user (see
`core.orchestrator.engine.ExecutionEngine.run`, which schedules this as a
background task rather than awaiting it inline) -- this is the "não deve
bloquear desnecessariamente a entrega do resultado" requirement. Project
Memory updates from execution content are deliberately not part of this
pipeline yet (see the Stage 3 report's limitations: automatically inferring
project facts from execution output risks writing hallucinated "facts"
into long-term memory without a deterministic extraction signal).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.database.repositories.reflections_repo import ReflectionsRepository
from core.learning.learning_engine import LearningEngine
from core.learning.model_performance import ModelPerformanceTracker
from core.learning.models import ReflectionResult
from core.learning.playbooks import PlaybookMatcher
from core.learning.prompt_optimizer import PromptOptimizer
from core.learning.reflection_engine import ExecutionEvidence, ReflectionEngine
from core.learning.rule_resolver import RuleResolver
from core.orchestrator.event_bus import EventBus, EventType, OrchestrationEvent
from core.utils.logging import get_logger

logger = get_logger("learning.post_execution")


@dataclass(frozen=True)
class PostExecutionSummary:
    execution_id: str
    reflection_id: str
    overall_score: float
    insights: int
    candidates_processed: int
    promoted_rule_ids: tuple[str, ...]


class PostExecutionPipeline:
    def __init__(
        self,
        reflection_engine: ReflectionEngine,
        reflections_repo: ReflectionsRepository,
        learning_engine: LearningEngine,
        performance_tracker: ModelPerformanceTracker,
        playbook_matcher: PlaybookMatcher,
        rule_resolver: RuleResolver,
        event_bus: EventBus,
        prompt_optimizer: PromptOptimizer | None = None,
    ) -> None:
        self._reflection = reflection_engine
        self._reflections_repo = reflections_repo
        self._learning = learning_engine
        self._performance = performance_tracker
        self._playbooks = playbook_matcher
        self._rules = rule_resolver
        self._events = event_bus
        self._prompt_optimizer = prompt_optimizer

    async def process(self, execution_id: str) -> PostExecutionSummary:
        await self._events.publish(OrchestrationEvent(
            type=EventType.REFLECTION_STARTED, execution_id=execution_id,
            payload={},
        ))
        try:
            evidence = await self._reflection.collect_evidence(execution_id)
            reflection = await self._reflection.reflect(execution_id)
            reflection_id = await self._reflections_repo.record(reflection)

            await self._update_model_performance(evidence)
            await self._update_playbook_outcome(evidence)
            promoted_ids = await self._process_candidates(evidence, reflection, reflection_id)
            await self._apply_rule_feedback(evidence)
            await self._process_prompt_feedback(evidence, reflection)

            await self._events.publish(OrchestrationEvent(
                type=EventType.REFLECTION_COMPLETED, execution_id=execution_id,
                payload={
                    "reflection_id": reflection_id, "overall_score": reflection.overall_score,
                    "insights": len(reflection.findings) + len(reflection.problems),
                    "candidates": len(reflection.improvement_candidates),
                    "promoted_rules": len(promoted_ids),
                },
            ))
            if promoted_ids:
                await self._events.publish(OrchestrationEvent(
                    type=EventType.LEARNING_UPDATED, execution_id=execution_id,
                    payload={"promoted_rule_ids": list(promoted_ids)},
                ))

            return PostExecutionSummary(
                execution_id=execution_id, reflection_id=reflection_id,
                overall_score=reflection.overall_score,
                insights=len(reflection.findings) + len(reflection.problems),
                candidates_processed=len(reflection.improvement_candidates),
                promoted_rule_ids=promoted_ids,
            )
        except Exception:
            # Logged here with pipeline-specific context, then re-raised --
            # the caller (ExecutionEngine._run_post_execution_safely) is
            # what actually guarantees this never takes down the app or
            # affects execution state, since this method also runs directly
            # in tests without that wrapper.
            logger.exception("post_execution_pipeline_failed", extra={"context": {"execution_id": execution_id}})
            raise

    async def _update_model_performance(self, evidence: ExecutionEvidence) -> None:
        category_by_step = {s["id"]: s.get("input", {}).get("category", "general") for s in evidence.steps}
        step_type_by_step = {s["id"]: s.get("step_type", "implementation") for s in evidence.steps}
        checks_by_step = {}
        for check_name, passed in _verification_checks(evidence):
            if check_name.startswith("step:"):
                checks_by_step[check_name.removeprefix("step:")] = passed

        for entry in evidence.usage_entries:
            step_id = entry.get("step_id") or ""
            provider = entry.get("provider") or "unknown"
            model = entry.get("model") or "unknown"
            agent_id = entry.get("agent_id") or "unknown"
            category = category_by_step.get(step_id, evidence.categories[0] if evidence.categories else "general")
            step_type = step_type_by_step.get(step_id, "implementation")
            success = bool(entry.get("success"))
            verified = checks_by_step.get(step_id, success and evidence.verification_passed)
            retried = (entry.get("retries") or 0) > 0
            review_rejected = step_type == "review" and evidence.correction_iterations > 0

            await self._performance.record_execution_outcome(
                provider=provider, model=model, agent_id=agent_id, task_category=category,
                risk=evidence.risk, success=success, verified_success=bool(verified), retried=retried,
                review_rejected=review_rejected, latency_seconds=entry.get("duration_seconds", 0.0),
                input_tokens=entry.get("input_tokens", 0), output_tokens=entry.get("output_tokens", 0),
                cost_usd=entry.get("estimated_cost_usd", 0.0), iterations=evidence.correction_iterations,
            )

    async def _update_playbook_outcome(self, evidence: ExecutionEvidence) -> None:
        # `execution.plan["playbook_version_id"]` is only present when the
        # Planner adopted a matching playbook -- see `core.orchestrator
        # .planner._plan_from_playbook`.
        if evidence.playbook_version_id:
            await self._playbooks.record_outcome(
                evidence.playbook_version_id, success=evidence.verification_passed,
            )

    async def _process_candidates(
        self, evidence: ExecutionEvidence, reflection: ReflectionResult, reflection_id: str,
    ) -> tuple[str, ...]:
        promoted: list[str] = []
        for candidate in reflection.improvement_candidates:
            outcome = await self._learning.process_candidate(
                candidate, project_id=evidence.project_id, reflection_id=reflection_id,
                execution_id=evidence.execution_id,
            )
            if outcome is not None and outcome.promoted_rule_id:
                promoted.append(outcome.promoted_rule_id)
        return tuple(promoted)

    async def _apply_rule_feedback(self, evidence: ExecutionEvidence) -> None:
        for step_id, category in {
            (s["id"], s.get("input", {}).get("category", "general")) for s in evidence.steps
        }:
            adjustments = await self._rules.routing_adjustments(category=category, project_id=evidence.project_id)
            if not adjustments:
                continue
            winning_agent = next(
                (rd["agent_id"] for rd in evidence.routing_decisions if rd["step_id"] == step_id), None,
            )
            if winning_agent is None:
                continue
            for adjustment in adjustments:
                if adjustment.agent_id != winning_agent:
                    continue
                success = evidence.verification_passed and evidence.task_status not in ("failed",)
                await self._learning.record_rule_outcome(
                    adjustment.rule_id, execution_id=evidence.execution_id, project_id=evidence.project_id,
                    success=success,
                )


    async def _process_prompt_feedback(self, evidence: ExecutionEvidence, reflection: ReflectionResult) -> None:
        """Prompt Optimizer flow: Current Prompt -> Historical Performance
        (implicit in *why* this feedback was raised) -> Reflection Findings
        -> Proposal -> Evaluation -> Candidate Version.

        A candidate version is only ever activated automatically when the
        Learning Policy allows the "prompt" category to auto-apply (it is
        in `requires_approval_categories` by default -- ASSISTED mode never
        does this on its own). Otherwise the proposal is recorded as a
        `prompt_proposal_generated` learning event carrying the full
        proposed content, for a human to review and apply via
        `prompt.proposals.apply`."""
        if not reflection.prompt_feedback or self._prompt_optimizer is None:
            return

        target_step_id = next(
            (s["id"] for s in evidence.steps if s.get("step_type") not in ("review", "synthesis", "correction")),
            None,
        )
        if target_step_id is None:
            return
        routing = next((rd for rd in evidence.routing_decisions if rd["step_id"] == target_step_id), None)
        if routing is None:
            return
        agent_id = routing["agent_id"]

        proposal = await self._prompt_optimizer.propose_from_feedback(
            agent_id, prompt_type="agent", agent_id=agent_id,
            feedback_lines=list(reflection.prompt_feedback),
            reason=f"Reflexão da execução {evidence.execution_id} identificou pontos a revisar no prompt.",
        )
        if proposal is None:
            return

        evaluation = await self._prompt_optimizer.evaluate(proposal)
        if not evaluation.allowed:
            await self._learning.record_event(
                event_type="prompt_proposal_rejected_safety", target_type="prompt", target_id=agent_id,
                evidence={"reason": evaluation.reason},
            )
            return

        if await self._learning.can_auto_apply("prompt"):
            version = await self._prompt_optimizer.create_candidate_version(proposal, evaluation)
            if version is not None:
                await self._learning.record_event(
                    event_type="prompt_version_activated", target_type="prompt_version", target_id=version["id"],
                    evidence={"owner_key": proposal.owner_key, "reason": proposal.reason},
                )
        else:
            await self._learning.record_event(
                event_type="prompt_proposal_generated", target_type="prompt", target_id=proposal.owner_key,
                evidence={
                    "owner_key": proposal.owner_key, "prompt_type": proposal.prompt_type,
                    "agent_id": proposal.agent_id, "current_version_id": proposal.current_version_id,
                    "proposed_content": proposal.proposed_content, "reason": proposal.reason,
                    "evidence_summary": proposal.evidence_summary,
                },
            )


def _verification_checks(evidence: ExecutionEvidence) -> list[tuple[str, bool]]:
    return [(c["name"], c["passed"]) for c in evidence.verification_checks]
