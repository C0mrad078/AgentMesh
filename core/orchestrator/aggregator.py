"""Result Aggregator.

Consolidates per-step results and the verification outcome into the single
`AggregatedResult` persisted as the task's final result, including the
total cost/token usage across every step (and every tool-loop round-trip
within each step) -- this is what the UI's cost panel ultimately reads.
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

        total_cost = sum(r.cost_usd for r in results)
        total_tokens = sum(r.usage.total_tokens for r in results if r.usage is not None)

        return AggregatedResult(
            summary=summary,
            step_outputs=[_step_result_to_dict(r) for r in results],
            verification=asdict(verification),
            total_cost_usd=total_cost,
            total_tokens=total_tokens,
        )


def _step_result_to_dict(result: StepResult) -> dict:
    data = asdict(result)
    if result.usage is not None:
        data["usage"] = {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "total_tokens": result.usage.total_tokens,
        }
    return data
