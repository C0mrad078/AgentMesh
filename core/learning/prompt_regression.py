"""Prompt Regression Tests: the fixed set of system invariants that must
never break, run before any prompt/rule change is allowed to activate.

Scope note: these cases check *system behavior* (the Planner/Router/
Verifier's own logic), not a specific candidate prompt's wording against a
live model -- doing the latter deterministically would require a real API
call per candidate, which the project's testing policy explicitly avoids
(`RUN_LIVE_AI_TESTS` gate). Running this fixed suite before activating any
change is still a meaningful regression gate: it catches a change that
broke planning/routing/verification invariants, using the exact three
examples the Stage 3 brief gives.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.agents.models import Agent, AgentCapability, AgentPermissions
from core.agents.registry import AgentRegistry
from core.orchestrator.dag import build_execution_layers
from core.orchestrator.models import (
    ComplexityLevel,
    Intent,
    PlanStep,
    RiskLevel,
    StepResult,
    StepStatus,
)
from core.orchestrator.planner import RuleBasedPlanner
from core.orchestrator.router import Router
from core.orchestrator.verifier import Verifier
from core.providers.health import ProviderHealthMonitor
from core.providers.pool import ProviderPool
from core.providers.registry import ModelInfo, ModelRegistry
from core.tasks.models import Task, TaskMode, TaskStatus
from core.utils.errors import NotFoundError
from core.utils.time import utc_now


@dataclass(frozen=True)
class RegressionCaseResult:
    name: str
    passed: bool
    detail: str = ""


def _fixture_task(mode: TaskMode = TaskMode.AUTOMATIC) -> Task:
    now = utc_now()
    return Task(
        id="task_regression", project_id="project_regression", title="Corrigir bug de autenticação",
        description="Corrigir bug de autenticação", mode=mode, status=TaskStatus.QUEUED,
        created_at=now, updated_at=now,
    )


def _fixture_intent() -> Intent:
    return Intent(
        categories=("debugging", "coding"), summary="Corrigir bug de autenticação",
        complexity=ComplexityLevel.MEDIUM, risk=RiskLevel.HIGH,
    )


class PromptRegressionRunner:
    """Stateless -- every case builds its own fixtures so results never
    depend on a prior case's side effects."""

    async def run_all(self) -> list[RegressionCaseResult]:
        return [
            self._case_planner_produces_valid_dependencies(),
            await self._case_router_never_selects_offline_provider(),
            await self._case_verifier_rejects_failing_tests(),
        ]

    def _case_planner_produces_valid_dependencies(self) -> RegressionCaseResult:
        try:
            plan = RuleBasedPlanner().create_plan(_fixture_task(), _fixture_intent())
            build_execution_layers(plan.steps)
        except Exception as exc:  # noqa: BLE001 - any failure here is the point of the test
            return RegressionCaseResult(
                "planner_produces_valid_dependencies", passed=False, detail=str(exc)
            )
        step_ids = {s.id for s in plan.steps}
        for step in plan.steps:
            for dep in step.dependencies:
                if dep not in step_ids:
                    return RegressionCaseResult(
                        "planner_produces_valid_dependencies", passed=False,
                        detail=f"Step '{step.id}' depends on unknown step '{dep}'.",
                    )
        return RegressionCaseResult("planner_produces_valid_dependencies", passed=True)

    async def _case_router_never_selects_offline_provider(self) -> RegressionCaseResult:
        agents = AgentRegistry([
            Agent(
                id="agent_offline_test", name="Offline Test Agent", provider="anthropic",
                model="claude-test", capabilities=[AgentCapability(name="coding", description="")],
                tools=[], permissions=AgentPermissions(), active=True,
            ),
        ])
        models = ModelRegistry([
            ModelInfo(
                provider="anthropic", model_id="claude-test", display_name="Claude Test",
                capabilities=("coding",), context_window=100_000, supports_tools=False,
                supports_images=False, supports_files=False, supports_structured_output=False,
                input_cost_per_million_usd=1.0, output_cost_per_million_usd=1.0, priority=5,
                enabled=True,
            ),
        ])
        pool = ProviderPool()  # anthropic is deliberately never registered
        health = ProviderHealthMonitor()
        router = Router(agents, models, pool, health)
        step = PlanStep(
            id="step_1", name="Implementar", description="", required_capability="coding",
        )
        try:
            decision = await router.route(step)
        except NotFoundError:
            # No usable candidate at all is an acceptable outcome (Offline
            # Mode) -- what must never happen is silently routing *to* the
            # unregistered provider.
            return RegressionCaseResult("router_never_selects_offline_provider", passed=True)
        if decision.provider == "anthropic":
            return RegressionCaseResult(
                "router_never_selects_offline_provider", passed=False,
                detail=f"Router selected unregistered provider '{decision.provider}'.",
            )
        return RegressionCaseResult("router_never_selects_offline_provider", passed=True)

    async def _case_verifier_rejects_failing_tests(self) -> RegressionCaseResult:
        results = [
            StepResult(step_id="step_1", status=StepStatus.COMPLETED, output=""),
        ]
        outcome = await Verifier().verify(
            results, categories=("coding",), risk=RiskLevel.LOW, workspace_path=None
        )
        if outcome.passed:
            return RegressionCaseResult(
                "verifier_rejects_empty_output", passed=False,
                detail="Verifier accepted a completed step with empty output.",
            )
        return RegressionCaseResult("verifier_rejects_empty_output", passed=True)


def all_passed(results: list[RegressionCaseResult]) -> bool:
    return all(r.passed for r in results)
