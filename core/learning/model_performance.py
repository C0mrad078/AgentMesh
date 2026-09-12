"""Model Performance Knowledge (Layer 5) + the reader the Router consumes.

`ModelPerformanceTracker.record_execution_outcome()` is called once per
completed step result during the post-execution pipeline; it updates the
per-(provider, model, agent, task_category, risk) row and derives the
metrics the brief asks for (success/verified-success/failure/retry rates,
p50/p95 latency, average cost/tokens/iterations, review-rejection rate).

`verified_success_rate` is the metric the Router actually uses -- it is
deliberately *not* the same as "the model claimed success" (see
`core.orchestrator.verifier`'s deterministic-first design): a step only
counts as a verified success here when it both completed and passed
whatever deterministic/AI-review check applied to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.database.repositories.model_performance_repo import ModelPerformanceRepository


@dataclass(frozen=True)
class PerformanceSummary:
    executions: int
    success_rate: float
    verified_success_rate: float
    failure_rate: float
    retry_rate: float
    avg_latency_seconds: float
    p50_latency_seconds: float
    p95_latency_seconds: float
    avg_input_tokens: float
    avg_output_tokens: float
    avg_cost_usd: float
    avg_iterations: float
    review_rejection_rate: float


def _percentile(sorted_samples: list[float], pct: float) -> float:
    if not sorted_samples:
        return 0.0
    index = min(len(sorted_samples) - 1, max(0, round(pct * (len(sorted_samples) - 1))))
    return sorted_samples[index]


def summarize(row: dict) -> PerformanceSummary:
    executions = row["executions"] or 0
    if executions == 0:
        return PerformanceSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    samples = sorted(row["latency_samples"])
    return PerformanceSummary(
        executions=executions,
        success_rate=row["successes"] / executions,
        verified_success_rate=row["verified_successes"] / executions,
        failure_rate=row["failures"] / executions,
        retry_rate=row["retries"] / executions,
        avg_latency_seconds=row["total_latency_seconds"] / executions,
        p50_latency_seconds=_percentile(samples, 0.50),
        p95_latency_seconds=_percentile(samples, 0.95),
        avg_input_tokens=row["total_input_tokens"] / executions,
        avg_output_tokens=row["total_output_tokens"] / executions,
        avg_cost_usd=row["total_cost_usd"] / executions,
        avg_iterations=row["total_iterations"] / executions,
        review_rejection_rate=row["review_rejections"] / executions,
    )


class ModelPerformanceTracker:
    def __init__(self, repository: ModelPerformanceRepository) -> None:
        self._repository = repository

    async def record_execution_outcome(
        self,
        *,
        provider: str,
        model: str,
        agent_id: str,
        task_category: str,
        risk: str,
        success: bool,
        verified_success: bool,
        retried: bool,
        review_rejected: bool,
        latency_seconds: float,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        iterations: int,
    ) -> None:
        await self._repository.record_outcome(
            provider=provider, model=model, agent_id=agent_id, task_category=task_category,
            risk=risk, success=success, verified_success=verified_success, retried=retried,
            review_rejected=review_rejected, latency_seconds=latency_seconds,
            input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd,
            iterations=iterations,
        )

    async def get_summary(
        self, *, provider: str, model: str, agent_id: str, task_category: str, risk: str,
    ) -> PerformanceSummary | None:
        row = await self._repository.get(
            provider=provider, model=model, agent_id=agent_id, task_category=task_category, risk=risk,
        )
        return summarize(row) if row else None

    async def get_verified_success_rate(
        self, *, provider: str, model: str, agent_id: str, task_category: str, risk: str,
    ) -> tuple[float, int]:
        """Returns (verified_success_rate, observations). Falls back to
        (0.5, 0) -- a neutral prior with zero weight -- when there is no
        history yet, so the Router's shrinkage naturally ignores it."""
        summary = await self.get_summary(
            provider=provider, model=model, agent_id=agent_id, task_category=task_category, risk=risk,
        )
        if summary is None or summary.executions == 0:
            return 0.5, 0
        return summary.verified_success_rate, summary.executions

    async def list_all_summaries(self) -> list[dict]:
        rows = await self._repository.list_all()
        return [
            {
                "provider": row["provider"], "model": row["model"], "agent_id": row["agent_id"],
                "task_category": row["task_category"], "risk": row["risk"],
                **_summary_dict(summarize(row)),
            }
            for row in rows
        ]


def _summary_dict(summary: PerformanceSummary) -> dict:
    return {
        "executions": summary.executions,
        "success_rate": summary.success_rate,
        "verified_success_rate": summary.verified_success_rate,
        "failure_rate": summary.failure_rate,
        "retry_rate": summary.retry_rate,
        "avg_latency_seconds": summary.avg_latency_seconds,
        "p50_latency_seconds": summary.p50_latency_seconds,
        "p95_latency_seconds": summary.p95_latency_seconds,
        "avg_input_tokens": summary.avg_input_tokens,
        "avg_output_tokens": summary.avg_output_tokens,
        "avg_cost_usd": summary.avg_cost_usd,
        "avg_iterations": summary.avg_iterations,
        "review_rejection_rate": summary.review_rejection_rate,
    }
