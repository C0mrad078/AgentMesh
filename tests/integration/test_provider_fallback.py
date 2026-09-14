"""Integration test for Stage 3's real fallback-on-unavailable-provider
wiring (spec section 9/44/45): a correction round normally goes back to
the *same* agent to fix their own work (the repair loop, spec section
52), but when that agent's own provider is genuinely unavailable, the
engine re-routes to a different agent (excluding the unavailable one)
and publishes a real `EventType.FALLBACK_USED` -- never silently, and
never for a plain code-quality correction (see
`tests/integration/test_review_loop.py`, which proves the *same*-agent
path this file's control test also checks).
"""

from __future__ import annotations

from pathlib import Path

from core.agents.models import Agent, AgentCapability, AgentPermissions
from core.bridge.context import build_context
from core.orchestrator.event_bus import EventType, OrchestrationEvent
from core.projects.models import ProjectCreate, ProjectUpdate
from core.providers.mock_provider import MockProvider, MockScenario
from core.security.secret_store import InMemorySecretStore
from core.tasks.models import TaskCreate
from core.utils.errors import ProviderRateLimitError

# `AgentRegistry` has no public "register one more agent" method (by
# design -- see its docstring) and `build_context` doesn't accept an
# override for it, so this test-only second "testing"-capable mock agent
# is injected directly into the constructed registry's backing dict. Its
# only purpose is giving the Router a real second candidate to fall back
# to -- none of the *default* mock agents share a capability with any
# other default mock agent, so proving a genuine cross-agent fallback
# needs one.
_EXTRA_TESTER = Agent(
    id="agent_tester_mock",
    name="Tester (mock, test-only)",
    description="Second mock testing-capable agent, registered only by this test.",
    provider="mock",
    model="mock-review-1",
    system_prompt="You are a careful QA engineer.",
    capabilities=[AgentCapability(name="testing", description="Runs and evaluates tests.")],
    tools=["ReadFile", "ListFiles", "SearchFiles"],
    permissions=AgentPermissions(can_read_files=True, can_write_files=False),
)


class _NoopAsync:
    """Replaces `ProviderHealthMonitor.report_success` for one test so a
    later successful mock call can't silently heal the provider back to
    ONLINE before the correction round runs -- see the comment where this
    is assigned."""

    async def __call__(self, provider: str) -> None:
        return None


async def _make_context(tmp_path: Path, db_name: str):
    ctx = await build_context(
        tmp_path / db_name, provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore(),
    )
    ctx.agent_registry._agents[_EXTRA_TESTER.id] = _EXTRA_TESTER  # noqa: SLF001 - test-only injection, see above
    await ctx.agents_repo.upsert(_EXTRA_TESTER)  # keep the DB in sync -- execution_steps.agent_id is a real FK
    return ctx


def _write_failing_project(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (workspace / "test_always_fails.py").write_text(
        "def test_always_fails():\n    assert False\n", encoding="utf-8",
    )
    return workspace


async def test_correction_round_falls_back_to_a_different_agent_when_provider_is_unavailable(
    tmp_path: Path,
) -> None:
    ctx = await _make_context(tmp_path, "fallback.db")
    try:
        workspace = _write_failing_project(tmp_path)
        fallback_events: list[OrchestrationEvent] = []
        ctx.event_bus.subscribe(
            lambda e: fallback_events.append(e) if e.type == EventType.FALLBACK_USED else None
        )

        project = await ctx.project_service.create_project(ProjectCreate(name="Fallback Project"))
        project = await ctx.project_service.update_project(
            project.id, ProjectUpdate(workspace_path=str(workspace)),
        )
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id, title="Fix the bug in the failing test",
                input={"scenario": MockScenario.SUCCESS.value},
            )
        )

        # The one and only provider in this test is now "unavailable" --
        # a real `ProviderRateLimitError` shape, exactly what a live CLI
        # adapter raises, not a fabricated flag. `MockProvider` always
        # succeeds its own calls (only the real pytest run fails), and
        # each success would otherwise call `report_success` and silently
        # heal this back to ONLINE before the correction round ever sees
        # it -- stubbed out here so this test can actually observe the
        # engine's *reaction* to a provider that's still unavailable,
        # which is what it exists to prove, not
        # `ProviderHealthMonitor`'s own (separately, correctly tested)
        # recovery bookkeeping.
        await ctx.health_monitor.report_failure(
            "mock", ProviderRateLimitError("Rate limited", retry_after_seconds=30.0),
        )
        ctx.health_monitor.report_success = _NoopAsync()

        execution = await ctx.engine.run(task)

        steps = await ctx.steps_repo.list_for_execution(execution.id)
        correction_steps = [s for s in steps if s.name.startswith("Correção")]
        assert len(correction_steps) >= 1, "the real pytest failure must still force a correction round"

        # The step that actually fails verification here is the "run the
        # real tests" step -- which is why the fallback candidate is the
        # extra testing-capable agent injected above, not agent_coder.
        original_testing_agent = next(
            s.agent_id for s in steps if s.name == "Executar testes para confirmar a correção."
        )
        assert original_testing_agent == _EXTRA_TESTER.id

        assert len(fallback_events) >= 1, "a real FALLBACK_USED event must be published"
        payload = fallback_events[0].payload
        assert payload["from_agent_id"] == _EXTRA_TESTER.id
        assert payload["to_agent_id"] != _EXTRA_TESTER.id
        assert payload["reason"] == "provider_unavailable"

        # And the correction step itself was actually executed by the new
        # agent -- a real consequence, not just an event with no effect.
        assert correction_steps[0].agent_id == payload["to_agent_id"]
    finally:
        await ctx.close()


async def test_correction_round_keeps_the_same_agent_when_provider_is_healthy(tmp_path: Path) -> None:
    """Control case: a plain code-quality correction must NOT reroute to a
    different agent just because verification failed -- only an
    unavailable provider should ever do that."""
    ctx = await _make_context(tmp_path, "no_fallback.db")
    try:
        workspace = _write_failing_project(tmp_path)
        fallback_events: list[OrchestrationEvent] = []
        ctx.event_bus.subscribe(
            lambda e: fallback_events.append(e) if e.type == EventType.FALLBACK_USED else None
        )

        project = await ctx.project_service.create_project(ProjectCreate(name="No Fallback Project"))
        project = await ctx.project_service.update_project(
            project.id, ProjectUpdate(workspace_path=str(workspace)),
        )
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id, title="Fix the bug in the failing test",
                input={"scenario": MockScenario.SUCCESS.value},
            )
        )

        execution = await ctx.engine.run(task)

        steps = await ctx.steps_repo.list_for_execution(execution.id)
        original_testing_agent = next(
            s.agent_id for s in steps if s.name == "Executar testes para confirmar a correção."
        )
        correction_steps = [s for s in steps if s.name.startswith("Correção")]
        assert len(correction_steps) >= 1
        assert all(s.agent_id == original_testing_agent for s in correction_steps)
        assert fallback_events == []
    finally:
        await ctx.close()
