from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.model_performance_repo import ModelPerformanceRepository
from core.learning.model_performance import ModelPerformanceTracker, summarize


def _dimensions() -> dict:
    return dict(provider="anthropic", model="claude-x", agent_id="agent_claude_architect", task_category="debugging", risk="low")


async def test_first_outcome_creates_a_row_with_the_right_counts(tmp_db: Database) -> None:
    tracker = ModelPerformanceTracker(ModelPerformanceRepository(tmp_db))
    await tracker.record_execution_outcome(
        **_dimensions(), success=True, verified_success=True, retried=False, review_rejected=False,
        latency_seconds=2.0, input_tokens=100, output_tokens=50, cost_usd=0.01, iterations=0,
    )
    summary = await tracker.get_summary(**_dimensions())
    assert summary is not None
    assert summary.executions == 1
    assert summary.success_rate == 1.0
    assert summary.verified_success_rate == 1.0


async def test_success_and_verified_success_are_tracked_separately(tmp_db: Database) -> None:
    tracker = ModelPerformanceTracker(ModelPerformanceRepository(tmp_db))
    # The model claimed success but it was not deterministically verified.
    await tracker.record_execution_outcome(
        **_dimensions(), success=True, verified_success=False, retried=False, review_rejected=False,
        latency_seconds=1.0, input_tokens=10, output_tokens=10, cost_usd=0.001, iterations=0,
    )
    summary = await tracker.get_summary(**_dimensions())
    assert summary.success_rate == 1.0
    assert summary.verified_success_rate == 0.0


async def test_rates_accumulate_correctly_across_multiple_outcomes(tmp_db: Database) -> None:
    tracker = ModelPerformanceTracker(ModelPerformanceRepository(tmp_db))
    outcomes = [True, True, False, True]
    for success in outcomes:
        await tracker.record_execution_outcome(
            **_dimensions(), success=success, verified_success=success, retried=not success,
            review_rejected=False, latency_seconds=1.0, input_tokens=10, output_tokens=10,
            cost_usd=0.001, iterations=1,
        )
    summary = await tracker.get_summary(**_dimensions())
    assert summary.executions == 4
    assert summary.success_rate == 0.75
    assert summary.failure_rate == 0.25
    assert summary.retry_rate == 0.25


async def test_latency_percentiles_reflect_the_sample_distribution() -> None:
    row = {
        "executions": 5, "successes": 5, "verified_successes": 5, "failures": 0, "retries": 0,
        "review_rejections": 0, "total_latency_seconds": 15.0, "total_input_tokens": 0,
        "total_output_tokens": 0, "total_cost_usd": 0.0, "total_iterations": 0,
        "latency_samples": [1.0, 2.0, 3.0, 4.0, 5.0],
    }
    summary = summarize(row)
    assert summary.p50_latency_seconds == 3.0
    assert summary.p95_latency_seconds == 5.0


async def test_empty_row_summarizes_to_all_zero() -> None:
    summary = summarize({
        "executions": 0, "successes": 0, "verified_successes": 0, "failures": 0, "retries": 0,
        "review_rejections": 0, "total_latency_seconds": 0.0, "total_input_tokens": 0,
        "total_output_tokens": 0, "total_cost_usd": 0.0, "total_iterations": 0, "latency_samples": [],
    })
    assert summary.executions == 0
    assert summary.success_rate == 0.0


async def test_get_verified_success_rate_returns_neutral_prior_with_zero_weight_when_no_history(tmp_db: Database) -> None:
    tracker = ModelPerformanceTracker(ModelPerformanceRepository(tmp_db))
    rate, observations = await tracker.get_verified_success_rate(**_dimensions())
    assert rate == 0.5
    assert observations == 0


async def test_dimensions_are_isolated_from_each_other(tmp_db: Database) -> None:
    tracker = ModelPerformanceTracker(ModelPerformanceRepository(tmp_db))
    await tracker.record_execution_outcome(
        **_dimensions(), success=True, verified_success=True, retried=False, review_rejected=False,
        latency_seconds=1.0, input_tokens=10, output_tokens=10, cost_usd=0.001, iterations=0,
    )
    other = _dimensions()
    other["agent_id"] = "agent_codex_developer"
    summary = await tracker.get_summary(**other)
    assert summary is None
