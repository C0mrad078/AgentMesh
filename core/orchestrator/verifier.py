"""Verifier.

Checks whether the collected `StepResult`s satisfy completion criteria
before a task is allowed to be marked `completed`. Stage 1's criteria are
intentionally simple and deterministic (every step succeeded and produced
non-empty output); a future stage can layer AI-driven review on top without
changing the `VerificationResult` contract the engine depends on.
"""

from __future__ import annotations

from core.orchestrator.models import StepResult, StepStatus, VerificationResult


class Verifier:
    def verify(self, results: list[StepResult]) -> VerificationResult:
        if not results:
            return VerificationResult(passed=False, reasons=["No step results to verify."])

        reasons: list[str] = []
        for result in results:
            if result.status != StepStatus.COMPLETED:
                reasons.append(f"Step '{result.step_id}' ended as '{result.status.value}'.")
            elif not result.output or not result.output.strip():
                reasons.append(f"Step '{result.step_id}' produced empty output.")

        return VerificationResult(passed=not reasons, reasons=reasons)
