from __future__ import annotations

import pytest
from core.orchestrator.budget import BudgetLimits, BudgetManager, BudgetStatus
from core.utils.errors import BudgetExceededError


class _FakeUsageReader:
    def __init__(self, total: float = 0.0) -> None:
        self.total = total

    async def total_cost_since(self, since_iso: str) -> float:
        return self.total


async def test_no_limits_configured_is_always_ok() -> None:
    manager = BudgetManager(BudgetLimits(), _FakeUsageReader())
    status = await manager.record_spend("exec_1", 1_000_000.0)
    assert status == BudgetStatus.OK


async def test_per_execution_soft_limit() -> None:
    limits = BudgetLimits(max_per_execution_usd=10.0, soft_limit_ratio=0.8)
    manager = BudgetManager(limits, _FakeUsageReader())
    status = await manager.record_spend("exec_1", 8.5)
    assert status == BudgetStatus.SOFT_LIMIT


async def test_per_execution_hard_limit() -> None:
    limits = BudgetLimits(max_per_execution_usd=10.0)
    manager = BudgetManager(limits, _FakeUsageReader())
    status = await manager.record_spend("exec_1", 10.5)
    assert status == BudgetStatus.HARD_LIMIT


async def test_check_before_call_raises_once_hard_limit_reached() -> None:
    limits = BudgetLimits(max_per_execution_usd=5.0)
    manager = BudgetManager(limits, _FakeUsageReader())
    await manager.record_spend("exec_1", 5.0)
    with pytest.raises(BudgetExceededError):
        await manager.check_before_call("exec_1")


async def test_check_before_call_allows_when_under_limit() -> None:
    limits = BudgetLimits(max_per_execution_usd=5.0)
    manager = BudgetManager(limits, _FakeUsageReader())
    await manager.record_spend("exec_1", 1.0)
    await manager.check_before_call("exec_1")  # must not raise


async def test_daily_limit_uses_usage_reader_total() -> None:
    limits = BudgetLimits(daily_limit_usd=20.0)
    manager = BudgetManager(limits, _FakeUsageReader(total=25.0))
    status = await manager.status_for("exec_1")
    assert status == BudgetStatus.HARD_LIMIT


async def test_monthly_soft_limit() -> None:
    limits = BudgetLimits(monthly_limit_usd=100.0, soft_limit_ratio=0.8)
    manager = BudgetManager(limits, _FakeUsageReader(total=85.0))
    status = await manager.status_for("exec_1")
    assert status == BudgetStatus.SOFT_LIMIT


async def test_executions_tracked_independently() -> None:
    limits = BudgetLimits(max_per_execution_usd=5.0)
    manager = BudgetManager(limits, _FakeUsageReader())
    await manager.record_spend("exec_1", 5.0)
    status_2 = await manager.status_for("exec_2")
    assert status_2 == BudgetStatus.OK
