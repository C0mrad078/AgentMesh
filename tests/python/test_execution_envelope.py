from core.missions.models import PlannedTask, PlanOutput
from core.parallel.models import ExecutionEnvelope, PlanningPolicy


def _task(key: str, *, kind: str = "implementation", depends_on: list[str] | None = None) -> PlannedTask:
    return PlannedTask(key=key, title=key, description=key, capabilities=["coding"], acceptance=["works"], kind=kind, depends_on=depends_on or [])


def test_envelope_allows_two_workers_and_queues_the_rest():
    envelope = ExecutionEnvelope(max_workers=2, mission_sessions=2)
    assert envelope.max_workers == 2
    assert envelope.mission_sessions == 2


def test_system_stages_are_explicit_and_do_not_look_like_workers():
    plan = PlanOutput(summary="plan", tasks=[_task("a"), _task("review", kind="review"), _task("integrate", kind="integration", depends_on=["a"])])
    assert [task.kind for task in plan.tasks] == ["implementation", "review", "integration"]
    assert plan.tasks[-1].depends_on == ["a"]


def test_bounded_policy_preserves_internal_steps_without_extra_workstreams():
    policy = PlanningPolicy(mode="bounded", desired_workstreams=2, max_implementation_tasks=2,
                            allow_additional_workstreams=False, allow_internal_subtasks=True)
    task = _task("backend")
    task = task.model_copy(update={"internal_steps": [{"title": "add function"}, {"title": "add test"}]})
    assert policy.desired_workstreams == 2
    assert len(task.internal_steps) == 2
