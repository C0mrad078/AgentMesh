"""Judge / Synthesizer.

Used by Debate mode (compare N independent solutions to the same problem)
and Consensus mode (compare N responses, detect divergence, decide whether
another round is warranted). Which agent acts as judge is a Router decision
like any other -- routed by capability ("analysis") and current provider
health -- never hardcoded to a specific model.

Falls back to a deterministic heuristic (prefer the longest successful,
verified response) when no provider is available or the judge call itself
fails, so debate/consensus modes still terminate cleanly offline.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.agents.registry import AgentRegistry
from core.orchestrator.models import PlanStep, RiskLevel, StepResult, StepStatus
from core.orchestrator.router import Router
from core.orchestrator.validation import validate_against_schema
from core.providers.base import AIRequest
from core.providers.pool import ProviderPool
from core.utils.errors import OrchestratorError
from core.utils.ids import new_id
from core.utils.logging import get_logger

logger = get_logger("orchestrator.judge")

JUDGE_SCHEMA: dict = {
    "type": "object",
    "required": ["winner_step_id", "reason"],
    "properties": {
        "winner_step_id": {"type": "string"},
        "synthesis": {"type": "string"},
        "reason": {"type": "string"},
    },
}

_JUDGE_SYSTEM_PROMPT = (
    "You are the Orquestrador's Judge. You are given the same goal and several "
    "independent candidate solutions. Pick the single best one, or combine "
    "their strongest points into a short synthesis. Return JSON matching the "
    "schema: winner_step_id must be exactly one of the given candidate ids."
)


@dataclass(frozen=True)
class JudgeVerdict:
    winner_step_id: str
    synthesis: str
    reason: str


class Judge:
    def __init__(self, router: Router, provider_pool: ProviderPool, agent_registry: AgentRegistry) -> None:
        self._router = router
        self._pool = provider_pool
        self._agents = agent_registry

    async def judge(
        self, *, execution_id: str, goal: str, candidates: list[StepResult], risk: RiskLevel = RiskLevel.LOW
    ) -> JudgeVerdict:
        successful = [c for c in candidates if c.status == StepStatus.COMPLETED and c.output]
        if not successful:
            return JudgeVerdict(
                winner_step_id=candidates[0].step_id if candidates else "",
                synthesis="",
                reason="Nenhuma resposta bem-sucedida para comparar.",
            )
        if len(successful) == 1:
            return JudgeVerdict(
                winner_step_id=successful[0].step_id,
                synthesis=successful[0].output or "",
                reason="Única resposta bem-sucedida disponível.",
            )

        try:
            return await self._ai_judge(execution_id, goal, successful, risk)
        except OrchestratorError as exc:
            logger.warning("judge_ai_failed", extra={"context": {"error": exc.message}})
            return self._heuristic_pick(successful)

    async def _ai_judge(
        self, execution_id: str, goal: str, successful: list[StepResult], risk: RiskLevel
    ) -> JudgeVerdict:
        pseudo_step = PlanStep(
            id=new_id("judge"),
            name="judge",
            description="Compare candidate solutions and select or synthesize the best one.",
            required_capability="analysis",
            step_type="review",
        )
        decision = self._router.route(pseudo_step, risk=risk)
        agent = self._agents.get(decision.agent_id)
        if agent is None or not self._pool.is_registered(decision.provider):
            return self._heuristic_pick(successful)

        provider = self._pool.get(decision.provider)
        prompt_lines = [f"Goal:\n{goal}\n"]
        for candidate in successful:
            prompt_lines.append(f"Candidate '{candidate.step_id}' (agent {candidate.agent_id}):\n{candidate.output}\n")
        prompt = "\n".join(prompt_lines)

        request = AIRequest.simple(
            execution_id=execution_id,
            agent_id=agent.id,
            system_prompt=_JUDGE_SYSTEM_PROMPT,
            prompt=prompt,
            structured_output_schema=JUDGE_SCHEMA,
            metadata={"model": decision.model},
            timeout_seconds=45.0,
        )
        response = await provider.execute(request)
        data = response.structured_output
        if data is None:
            return self._heuristic_pick(successful)

        outcome = validate_against_schema(data, JUDGE_SCHEMA)
        valid_ids = {c.step_id for c in successful}
        if not outcome.valid or data.get("winner_step_id") not in valid_ids:
            return self._heuristic_pick(successful)

        return JudgeVerdict(
            winner_step_id=data["winner_step_id"],
            synthesis=data.get("synthesis", ""),
            reason=data.get("reason", "Selecionado pelo judge."),
        )

    def _heuristic_pick(self, successful: list[StepResult]) -> JudgeVerdict:
        best = max(successful, key=lambda r: len(r.output or ""))
        return JudgeVerdict(
            winner_step_id=best.step_id,
            synthesis=best.output or "",
            reason=(
                "Selecionado por heurística determinística (resposta mais "
                "completa) na ausência de um judge de IA disponível."
            ),
        )
