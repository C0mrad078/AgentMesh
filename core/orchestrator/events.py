"""Execution progress events, streamed from the engine to the bridge (and
from there to the frontend) as they happen, without blocking the pipeline.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from core.orchestrator.models import ExecutionPhase, StepStatus


@dataclass(frozen=True)
class ExecutionEvent:
    execution_id: str
    task_id: str
    phase: ExecutionPhase
    phase_label: str
    status: StepStatus
    detail: str | None = None
    extra: dict[str, Any] | None = None


EventSink = Callable[[ExecutionEvent], Awaitable[None]]


async def noop_sink(_event: ExecutionEvent) -> None:
    return None
