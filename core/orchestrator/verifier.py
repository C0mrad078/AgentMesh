"""Verifier.

Layered verification, deterministic first:

  1. **Step-level checks** -- every step actually completed and produced
     non-empty output. Free, instant, always run.
  2. **Project-level checks** -- when the plan touched code
     (coding/debugging/refactoring/testing categories) and the project has
     a workspace, actually run its tests/lint via `CommandPlanner` (which
     itself refuses to invent a command it can't confirm exists). This is
     the "não pergunte ao Claude se `npm test` passou -- rode `npm test`"
     rule: objective, deterministic evidence beats asking a model.

**AI verification** (the "aspectos subjetivos" layer the project brief also
asks for) is *not* a separate hidden call bolted onto this class -- it is
the Planner's own risk-triggered review step (see
`RuleBasedPlanner`/`AIPlanner`: a high/critical-risk task always gets an
explicit review step assigned to a reviewer agent). That step's result
flows through this same `verify()` call like any other step. Keeping it as
a normal plan step rather than a Verifier-internal AI call means: no
duplicate/hidden provider call, it is fully visible in the execution
timeline, and `Verifier` itself stays deterministic, dependency-free, and
trivially testable without a provider.
"""

from __future__ import annotations

from core.orchestrator.models import (
    RiskLevel,
    StepResult,
    StepStatus,
    VerificationCheck,
    VerificationResult,
)
from core.tools.command_planner import CommandPlanner, ProjectAction
from core.utils.errors import ToolExecutionError

_ACTIONS_BY_CATEGORY: dict[str, list[ProjectAction]] = {
    "coding": [ProjectAction.RUN_TESTS, ProjectAction.RUN_LINT],
    "debugging": [ProjectAction.RUN_TESTS],
    "refactoring": [ProjectAction.RUN_TESTS, ProjectAction.RUN_LINT],
    "testing": [ProjectAction.RUN_TESTS],
}

_TRUNCATE_OUTPUT_CHARS = 500


class Verifier:
    async def verify(
        self,
        results: list[StepResult],
        *,
        categories: tuple[str, ...] = (),
        risk: RiskLevel = RiskLevel.LOW,
        workspace_path: str | None = None,
        run_quality_gates: bool = True,
    ) -> VerificationResult:
        if not results:
            return VerificationResult(passed=False, reasons=["No step results to verify."])

        checks = [self._check_step(result) for result in results]

        if run_quality_gates and workspace_path and all(c.passed for c in checks):
            checks.extend(await self._run_quality_gates(categories, workspace_path))

        reasons = [f"{c.name}: {c.detail}" if c.detail else c.name for c in checks if not c.passed]
        _ = risk  # risk already shaped the plan (an extra review step); nothing further to do here
        return VerificationResult(passed=not reasons, reasons=reasons, checks=checks)

    def _check_step(self, result: StepResult) -> VerificationCheck:
        if result.status != StepStatus.COMPLETED:
            return VerificationCheck(
                name=f"step:{result.step_id}", passed=False,
                detail=f"ended as '{result.status.value}'",
            )
        if not result.output or not result.output.strip():
            return VerificationCheck(
                name=f"step:{result.step_id}", passed=False, detail="produced empty output"
            )
        return VerificationCheck(name=f"step:{result.step_id}", passed=True)

    async def _run_quality_gates(
        self, categories: tuple[str, ...], workspace_path: str
    ) -> list[VerificationCheck]:
        actions: set[ProjectAction] = set()
        for category in categories:
            actions.update(_ACTIONS_BY_CATEGORY.get(category, []))
        if not actions:
            return []

        planner = CommandPlanner(workspace_path)
        checks: list[VerificationCheck] = []
        for action in actions:
            if planner.resolve(action) is None:
                # Cannot confirm a real command for this project/stack --
                # skip rather than invent one; this is not a failure, it is
                # "not applicable."
                continue
            try:
                result = await planner.run(action, timeout=180.0)
            except ToolExecutionError as exc:
                checks.append(VerificationCheck(name=action.value, passed=False, detail=exc.message))
                continue
            detail = "ok" if result.success else (result.stdout + result.stderr)[-_TRUNCATE_OUTPUT_CHARS:]
            checks.append(VerificationCheck(name=action.value, passed=result.success, detail=detail))
        return checks
