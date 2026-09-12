"""Integration tests for the engine's review/correction loop against a real,
deterministic quality gate (pytest on a real temporary project) -- proving
the loop actually terminates, never fakes success, and reports a `partial`
outcome when correction rounds don't manage to fix the underlying problem
(which a `MockProvider`-driven correction step cannot do, since it never
touches the filesystem -- see `core.providers.mock_provider` for what it
can simulate). The Verifier's own pass/fail logic is covered in isolation
by `tests/python/test_verifier.py`; this file is specifically about the
engine wiring the loop, the iteration cap, and the resulting task status.
"""

from __future__ import annotations

from pathlib import Path

from core.bridge.context import build_context
from core.orchestrator.models import ExecutionStatus
from core.projects.models import ProjectCreate, ProjectUpdate
from core.providers.mock_provider import MockProvider, MockScenario
from core.security.secret_store import InMemorySecretStore
from core.tasks.models import TaskCreate, TaskStatus


async def test_correction_loop_exhausts_and_marks_task_partial(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (workspace / "test_always_fails.py").write_text(
        "def test_always_fails():\n    assert False\n", encoding="utf-8",
    )

    ctx = await build_context(tmp_path / "review.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        project = await ctx.project_service.create_project(ProjectCreate(name="Review Loop Project"))
        project = await ctx.project_service.update_project(
            project.id, ProjectUpdate(workspace_path=str(workspace))
        )
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id,
                title="Fix the failing test",
                input={"scenario": MockScenario.SUCCESS.value},
            )
        )

        execution = await ctx.engine.run(task)

        # The step itself always "succeeds" (mock), but the real pytest run
        # keeps failing -- verification must never be faked as passing.
        assert execution.status == ExecutionStatus.COMPLETED  # the run itself completed, cleanly
        final_task = await ctx.task_service.get_task(task.id)
        assert final_task.status == TaskStatus.PARTIAL
        assert final_task.result is not None
        assert final_task.result["verification"]["passed"] is False

        steps = await ctx.steps_repo.list_for_execution(execution.id)
        correction_steps = [s for s in steps if s.name.startswith("Correção")]
        verification_phases = [s for s in steps if s.name == "Verificando resultado"]

        # max_review_iterations defaults to 3: 3 verification passes, and a
        # correction round after each of the first two failed ones.
        assert len(verification_phases) == 3
        assert len(correction_steps) == 2
    finally:
        await ctx.close()


async def test_correction_loop_never_exceeds_configured_max_iterations(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (workspace / "test_always_fails.py").write_text(
        "def test_always_fails():\n    assert False\n", encoding="utf-8",
    )

    ctx = await build_context(tmp_path / "review2.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        # Tighten the iteration cap to prove it is actually respected, not
        # just correct at its default value.
        ctx.engine.max_review_iterations = 1

        project = await ctx.project_service.create_project(ProjectCreate(name="Capped Review"))
        project = await ctx.project_service.update_project(
            project.id, ProjectUpdate(workspace_path=str(workspace))
        )
        task = await ctx.task_service.create_task(
            TaskCreate(project_id=project.id, title="Fix it", input={"scenario": MockScenario.SUCCESS.value})
        )

        execution = await ctx.engine.run(task)
        steps = await ctx.steps_repo.list_for_execution(execution.id)
        correction_steps = [s for s in steps if s.name.startswith("Correção")]
        assert len(correction_steps) == 0  # max_review_iterations=1: no room for a correction round
    finally:
        await ctx.close()
