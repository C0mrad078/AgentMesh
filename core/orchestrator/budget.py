"""Cost/budget enforcement.

Tracks spend at three scopes -- per execution, per day, per month -- against
configurable limits (`core.database.repositories.settings_repo`, surfaced in
Settings > Execuções). Daily/monthly totals are computed from the persisted
`usage_metrics` table rather than an in-memory counter, so limits survive an
app restart correctly.

Soft limit (default 80% of any configured limit): the caller (the execution
engine) is expected to react by simplifying strategy (e.g. skip an optional
review pass) -- `BudgetManager` itself only reports the status, it does not
change orchestration behavior.

Hard limit: `check_before_call` raises `BudgetExceededError`, which the
engine treats as a reason to stop starting new provider calls and finalize
with whatever was already produced (see `ExecutionEngine`), rather than a
generic failure.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from core.utils.errors import BudgetExceededError


class UsageCostReader(Protocol):
    async def total_cost_since(self, since_iso: str) -> float: ...


class BudgetStatus(str, Enum):
    OK = "ok"
    SOFT_LIMIT = "soft_limit"
    HARD_LIMIT = "hard_limit"


@dataclass(frozen=True)
class BudgetLimits:
    max_per_execution_usd: float | None = None
    daily_limit_usd: float | None = None
    monthly_limit_usd: float | None = None
    soft_limit_ratio: float = 0.8


def _start_of_day_iso() -> str:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _start_of_month_iso() -> str:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


class BudgetManager:
    def __init__(self, limits: BudgetLimits, usage_reader: UsageCostReader) -> None:
        self._limits = limits
        self._usage_reader = usage_reader
        self._per_execution_spent: dict[str, float] = defaultdict(float)

    @property
    def limits(self) -> BudgetLimits:
        return self._limits

    def update_limits(self, limits: BudgetLimits) -> None:
        self._limits = limits

    async def record_spend(self, execution_id: str, cost_usd: float) -> BudgetStatus:
        self._per_execution_spent[execution_id] += cost_usd
        return await self.status_for(execution_id)

    def spent_for_execution(self, execution_id: str) -> float:
        return self._per_execution_spent[execution_id]

    async def status_for(self, execution_id: str) -> BudgetStatus:
        spent_exec = self._per_execution_spent[execution_id]
        limits = self._limits

        if limits.max_per_execution_usd is not None and spent_exec >= limits.max_per_execution_usd:
            return BudgetStatus.HARD_LIMIT

        daily_spent = await self._usage_reader.total_cost_since(_start_of_day_iso())
        if limits.daily_limit_usd is not None and daily_spent >= limits.daily_limit_usd:
            return BudgetStatus.HARD_LIMIT

        monthly_spent = await self._usage_reader.total_cost_since(_start_of_month_iso())
        if limits.monthly_limit_usd is not None and monthly_spent >= limits.monthly_limit_usd:
            return BudgetStatus.HARD_LIMIT

        soft_hit = (
            (
                limits.max_per_execution_usd is not None
                and spent_exec >= limits.max_per_execution_usd * limits.soft_limit_ratio
            )
            or (
                limits.daily_limit_usd is not None
                and daily_spent >= limits.daily_limit_usd * limits.soft_limit_ratio
            )
            or (
                limits.monthly_limit_usd is not None
                and monthly_spent >= limits.monthly_limit_usd * limits.soft_limit_ratio
            )
        )
        return BudgetStatus.SOFT_LIMIT if soft_hit else BudgetStatus.OK

    async def check_before_call(self, execution_id: str) -> None:
        if await self.status_for(execution_id) == BudgetStatus.HARD_LIMIT:
            raise BudgetExceededError(
                f"Budget limit reached; execution '{execution_id}' cannot make further "
                "provider calls. Increase the limit in Settings or wait for it to reset.",
            )

    def reset_execution(self, execution_id: str) -> None:
        """Test helper / cleanup: drop the in-memory per-execution counter."""
        self._per_execution_spent.pop(execution_id, None)
