"""Result Aggregator.

Consolidates per-step results and the verification outcome into the single
`AggregatedResult` persisted as the task's final result.
"""

from __future__ import annotations

from dataclasses import asdict

from core.orchestrator.models import AggregatedResult, StepResult, VerificationResult


class ResultAggregator:
    def aggregate(
        self, results: list[StepResult], verification: VerificationResult
    ) -> AggregatedResult:
        outputs = [r.output for r in results if r.output]
        summary = " ".join(outputs).strip() or "Nenhum resultado produzido."

        return AggregatedResult(
            summary=summary,
            step_outputs=[asdict(r) for r in results],
            verification=asdict(verification),
        )
