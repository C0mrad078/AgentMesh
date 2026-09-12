from __future__ import annotations

import pytest
from core.orchestrator.dag import build_execution_layers
from core.orchestrator.models import PlanStep
from core.utils.errors import ValidationError


def _step(step_id: str, deps: tuple[str, ...] = ()) -> PlanStep:
    return PlanStep(
        id=step_id, name=step_id, description=step_id, required_capability="general",
        dependencies=deps,
    )


def test_sequential_plan_produces_one_step_per_layer() -> None:
    steps = [_step("a"), _step("b", ("a",)), _step("c", ("b",))]
    layers = build_execution_layers(steps)
    assert [ [s.id for s in layer] for layer in layers ] == [["a"], ["b"], ["c"]]


def test_independent_steps_share_a_layer() -> None:
    steps = [_step("a"), _step("b"), _step("c", ("a", "b"))]
    layers = build_execution_layers(steps)
    assert len(layers) == 2
    assert {s.id for s in layers[0]} == {"a", "b"}
    assert [s.id for s in layers[1]] == ["c"]


def test_diamond_dependency_resolves_correctly() -> None:
    steps = [_step("a"), _step("b", ("a",)), _step("c", ("a",)), _step("d", ("b", "c"))]
    layers = build_execution_layers(steps)
    assert [s.id for s in layers[0]] == ["a"]
    assert {s.id for s in layers[1]} == {"b", "c"}
    assert [s.id for s in layers[2]] == ["d"]


def test_unknown_dependency_is_rejected() -> None:
    steps = [_step("a", ("ghost",))]
    with pytest.raises(ValidationError):
        build_execution_layers(steps)


def test_self_dependency_is_rejected() -> None:
    steps = [_step("a", ("a",))]
    with pytest.raises(ValidationError):
        build_execution_layers(steps)


def test_cycle_is_rejected() -> None:
    steps = [_step("a", ("b",)), _step("b", ("a",))]
    with pytest.raises(ValidationError):
        build_execution_layers(steps)


def test_single_step_plan() -> None:
    layers = build_execution_layers([_step("only")])
    assert len(layers) == 1
    assert layers[0][0].id == "only"
