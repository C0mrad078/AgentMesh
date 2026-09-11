"""Planner.

Converts an `Intent` plus the originating `Task` into a structured
`ExecutionPlan`. Stage 1 produces a single-step plan mapped from the
detected category to a required agent capability -- enough structure for
the Router/Executor/Verifier pipeline to be real, while leaving room for a
future multi-step, AI-driven planner to slot in without changing the
`ExecutionPlan`/`PlanStep` shape.
"""

from __future__ import annotations

from core.orchestrator.models import ExecutionPlan, Intent, PlanStep
from core.tasks.models import Task
from core.utils.ids import new_id

_CATEGORY_TO_CAPABILITY: dict[str, str] = {
    "coding": "coding",
    "writing": "writing",
    "research": "planning",
    "review": "verification",
    "general": "planning",
}


class Planner:
    def create_plan(self, task: Task, intent: Intent) -> ExecutionPlan:
        capability = _CATEGORY_TO_CAPABILITY.get(intent.category, "planning")
        step = PlanStep(
            id=new_id("step"),
            name=f"Executar: {intent.summary}"[:200],
            description=task.description or task.title,
            required_capability=capability,
            # `task.input` is forwarded so a caller can steer the mocked
            # provider (e.g. {"scenario": "timeout"}) end-to-end through the
            # whole pipeline -- this is what lets integration tests and,
            # later, real provider configuration flow through unchanged.
            input={**task.input, "task_id": task.id, "category": intent.category},
        )
        return ExecutionPlan(task_id=task.id, intent=intent, steps=[step])
