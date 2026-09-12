"""Turns a plan's step dependency list into an executable DAG.

`PlanStep.dependencies` is just a list of step ids; this module is the only
place that interprets those ids as a graph. `build_execution_layers` runs a
standard Kahn's-algorithm topological sort but groups the result into
*layers*: every step within a layer has all of its dependencies already
satisfied by a previous layer, so a layer's steps are safe to run
concurrently (bounded by `core.orchestrator.concurrency.ConcurrencyManager`)
while layers themselves still run in order.

    A ──→ C        layer 0: [A, B]   (no deps -- run in parallel)
    B ──→ C        layer 1: [C]      (waits for both A and B)
"""

from __future__ import annotations

from core.orchestrator.models import PlanStep
from core.utils.errors import ValidationError


def build_execution_layers(steps: list[PlanStep]) -> list[list[PlanStep]]:
    by_id = {step.id: step for step in steps}

    for step in steps:
        for dep in step.dependencies:
            if dep not in by_id:
                raise ValidationError(
                    f"Plan step '{step.id}' depends on unknown step '{dep}'.",
                )
            if dep == step.id:
                raise ValidationError(f"Plan step '{step.id}' cannot depend on itself.")

    remaining: dict[str, set[str]] = {step.id: set(step.dependencies) for step in steps}
    resolved: set[str] = set()
    layers: list[list[PlanStep]] = []

    while remaining:
        ready_ids = [step_id for step_id, deps in remaining.items() if deps <= resolved]
        if not ready_ids:
            raise ValidationError(
                "Plan contains a dependency cycle and cannot be executed.",
                details={"unresolved_step_ids": sorted(remaining)},
            )
        layers.append([by_id[step_id] for step_id in ready_ids])
        for step_id in ready_ids:
            resolved.add(step_id)
            del remaining[step_id]

    return layers
