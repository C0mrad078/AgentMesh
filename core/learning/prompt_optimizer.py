"""Prompt Optimizer.

    Current Prompt -> Historical Performance -> Reflection Findings
        -> Proposal -> Evaluation -> Candidate Version

Proposals are deterministic and template-based (an ordered checklist
appended from deduplicated reflection feedback lines), not freeform
AI-generated text -- this keeps every proposal auditable (a human can read
exactly what changed and why) and keeps the Safety Validator's pattern
screening meaningful (it can't be evaded by creative phrasing an AI
generation step might produce). `evaluate()` runs the Safety Validator and
the Prompt Regression suite; only a proposal that clears both may ever
become a new prompt version -- and a `prompt_type="core"` proposal never
creates a version at all, only a pending `prompt_evaluations` row for a
human to act on (a "Core Prompt Improvement Proposal").
"""

from __future__ import annotations

from dataclasses import dataclass

from core.agents.prompt_registry import PromptRegistry
from core.database.repositories.prompt_evaluations_repo import PromptEvaluationsRepository
from core.learning.models import PromptType
from core.learning.prompt_regression import PromptRegressionRunner, all_passed
from core.learning.safety import SafetyValidator


@dataclass(frozen=True)
class PromptProposal:
    owner_key: str
    prompt_type: str
    agent_id: str | None
    current_version_id: str
    current_content: str
    proposed_content: str
    reason: str
    evidence_summary: str


@dataclass(frozen=True)
class EvaluationOutcome:
    allowed: bool
    regression_pass: bool
    reason: str
    regression_results: list[dict]


class PromptOptimizer:
    def __init__(
        self,
        prompt_registry: PromptRegistry,
        evaluations_repo: PromptEvaluationsRepository,
        *,
        safety: SafetyValidator | None = None,
        regression_runner: PromptRegressionRunner | None = None,
    ) -> None:
        self._prompts = prompt_registry
        self._evaluations = evaluations_repo
        self._safety = safety or SafetyValidator()
        self._regression = regression_runner or PromptRegressionRunner()

    async def propose_from_feedback(
        self,
        owner_key: str,
        *,
        prompt_type: str,
        agent_id: str | None,
        feedback_lines: list[str],
        reason: str,
    ) -> PromptProposal | None:
        if not feedback_lines:
            return None
        versions = await self._prompts.list_versions_by_key(owner_key) if owner_key else []
        current = next((v for v in versions if v["active"]), None)
        if current is None:
            return None

        checklist = sorted(set(feedback_lines))
        already_covered = [line for line in checklist if line in current["content"]]
        new_items = [line for line in checklist if line not in already_covered]
        if not new_items:
            return None

        addition = (
            "\n\nCom base em execuções anteriores, verifique também:\n"
            + "\n".join(f"- {line}" for line in new_items)
        )
        return PromptProposal(
            owner_key=owner_key, prompt_type=prompt_type, agent_id=agent_id,
            current_version_id=current["id"], current_content=current["content"],
            proposed_content=current["content"] + addition, reason=reason,
            evidence_summary="; ".join(new_items),
        )

    async def evaluate(self, proposal: PromptProposal) -> EvaluationOutcome:
        safety = self._safety.validate_prompt_content(proposal.proposed_content)
        if not safety.allowed:
            return EvaluationOutcome(
                allowed=False, regression_pass=False, reason=safety.reason, regression_results=[],
            )

        results = await self._regression.run_all()
        passed = all_passed(results)
        result_dicts = [{"name": r.name, "passed": r.passed, "detail": r.detail} for r in results]
        if not passed:
            return EvaluationOutcome(
                allowed=False, regression_pass=False,
                reason="Prompt regression suite failed -- candidate not activated.",
                regression_results=result_dicts,
            )
        return EvaluationOutcome(
            allowed=True, regression_pass=True, reason="", regression_results=result_dicts,
        )

    async def create_candidate_version(
        self, proposal: PromptProposal, evaluation: EvaluationOutcome, *, author: str = "learning_engine",
    ) -> dict | None:
        """Only ever called after `evaluate()` returned `allowed=True`. A
        `core` prompt_type proposal still raises `ImmutablePolicyError`
        here (enforced by the repository, not just this check) -- Core
        Prompt proposals are recorded via `propose_core_prompt_improvement`
        instead, which never calls this method."""
        if not evaluation.allowed:
            return None
        version = await self._prompts.create_version_by_key(
            proposal.owner_key, name=f"{proposal.owner_key}_optimized", content=proposal.proposed_content,
            prompt_type=proposal.prompt_type, agent_id=proposal.agent_id, author=author,
            origin="prompt_optimizer", reason=proposal.reason,
        )
        await self._evaluations.record(
            prompt_version_id=version["id"], baseline_version_id=proposal.current_version_id,
            regression_pass=evaluation.regression_pass, regression_results=evaluation.regression_results,
            verdict="approved",
        )
        return version

    async def propose_core_prompt_improvement(self, *, reason: str, evidence_summary: str) -> dict:
        """Records a pending proposal for a human to review -- never creates
        or activates a new Core Prompt version automatically."""
        core_versions = await self._prompts.list_versions_by_key("core")
        current = next((v for v in core_versions if v["active"]), None)
        assert current is not None, "core prompt must be seeded before proposals can reference it"
        return await self._evaluations.record(
            prompt_version_id=current["id"], baseline_version_id=None, regression_pass=False,
            regression_results=[{"name": "core_prompt_improvement_proposal", "passed": False, "detail": evidence_summary}],
            verdict="pending",
        )


__all__ = ["PromptOptimizer", "PromptProposal", "EvaluationOutcome", "PromptType"]
