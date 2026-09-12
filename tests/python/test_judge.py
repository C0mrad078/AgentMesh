from __future__ import annotations

from core.agents.registry import AgentRegistry
from core.orchestrator.judge import Judge
from core.orchestrator.models import RiskLevel, StepResult, StepStatus
from core.orchestrator.router import Router
from core.providers.base import AIRequest, AIResponse, ProviderHealthStatus, TokenUsage
from core.providers.circuit_breaker import CircuitBreaker
from core.providers.health import ProviderHealthMonitor
from core.providers.pool import ProviderPool
from core.providers.registry import ModelRegistry


def _result(step_id: str, output: str | None, status: StepStatus = StepStatus.COMPLETED) -> StepResult:
    return StepResult(step_id=step_id, status=status, output=output, agent_id="agent_1")


def _make_judge(provider=None) -> Judge:
    pool = ProviderPool()
    if provider is not None:
        pool.register(provider)
    health = ProviderHealthMonitor(CircuitBreaker())
    router = Router(AgentRegistry(), ModelRegistry(), pool, health)
    return Judge(router, pool, AgentRegistry())


async def test_single_successful_candidate_wins_without_calling_a_judge() -> None:
    judge = _make_judge()
    verdict = await judge.judge(execution_id="e1", goal="g", candidates=[_result("s1", "answer")])
    assert verdict.winner_step_id == "s1"
    assert verdict.synthesis == "answer"


async def test_no_successful_candidates_returns_a_clear_verdict() -> None:
    judge = _make_judge()
    candidates = [_result("s1", None, StepStatus.FAILED)]
    verdict = await judge.judge(execution_id="e1", goal="g", candidates=candidates)
    assert "bem-sucedida" in verdict.reason.lower() or "sucedida" in verdict.reason.lower()


async def test_heuristic_fallback_picks_longest_answer_when_no_provider() -> None:
    judge = _make_judge()
    candidates = [_result("short", "a"), _result("long", "a much longer and more detailed answer")]
    verdict = await judge.judge(execution_id="e1", goal="g", candidates=candidates)
    assert verdict.winner_step_id == "long"


class _JudgeFakeProvider:
    name = "mock"

    def __init__(self, structured_output: dict) -> None:
        self._structured_output = structured_output

    async def execute(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            content="", provider=self.name, model="mock-general-1", finish_reason="stop",
            usage=TokenUsage(input_tokens=5, output_tokens=5), duration_seconds=0.01,
            structured_output=self._structured_output,
        )

    async def stream(self, request):
        yield ""

    async def health_check(self) -> ProviderHealthStatus:
        return ProviderHealthStatus.ONLINE

    async def list_models(self) -> list[str]:
        return ["mock-general-1"]

    async def cancel(self, execution_id: str) -> None:
        return None


async def test_ai_judge_picks_the_winner_it_names() -> None:
    provider = _JudgeFakeProvider({"winner_step_id": "b", "synthesis": "combined answer", "reason": "b was more complete"})
    judge = _make_judge(provider)
    candidates = [_result("a", "answer a"), _result("b", "answer b")]
    verdict = await judge.judge(execution_id="e1", goal="g", candidates=candidates, risk=RiskLevel.LOW)
    assert verdict.winner_step_id == "b"
    assert verdict.synthesis == "combined answer"


async def test_ai_judge_falls_back_to_heuristic_on_invalid_winner_id() -> None:
    provider = _JudgeFakeProvider({"winner_step_id": "does-not-exist", "reason": "oops"})
    judge = _make_judge(provider)
    candidates = [_result("a", "short"), _result("b", "a much longer detailed answer here")]
    verdict = await judge.judge(execution_id="e1", goal="g", candidates=candidates)
    assert verdict.winner_step_id == "b"
    assert "heurística" in verdict.reason.lower()


async def test_ai_judge_falls_back_to_heuristic_on_malformed_structured_output() -> None:
    provider = _JudgeFakeProvider({"not": "matching schema"})
    judge = _make_judge(provider)
    candidates = [_result("a", "short"), _result("b", "a much longer detailed answer here")]
    verdict = await judge.judge(execution_id="e1", goal="g", candidates=candidates)
    assert verdict.winner_step_id == "b"
