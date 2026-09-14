"""Integration tests for Stage 3's real meeting detection (spec section
15-19): a DAG layer with 2+ agents genuinely running concurrently under
Debate/Consensus mode is a real collaborative-planning window, not a
decorative one -- `MeetingManager` publishes `meeting.created` /
`meeting.started` / `meeting.completed` around exactly that layer, with
the real, dynamic participant list (spec section 58/59), never a fixed
roster and never for Manual/Pipeline/Automatic tasks that never actually
run agents concurrently.
"""

from __future__ import annotations

from pathlib import Path

from core.bridge.context import build_context
from core.orchestrator.event_bus import EventType, OrchestrationEvent
from core.orchestrator.models import ExecutionStatus
from core.projects.models import ProjectCreate
from core.providers.mock_provider import MockProvider, MockScenario
from core.security.secret_store import InMemorySecretStore
from core.tasks.models import TaskCreate, TaskMode


async def test_debate_mode_publishes_a_real_meeting_around_the_concurrent_layer(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "meeting.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        events: list[OrchestrationEvent] = []
        ctx.event_bus.subscribe(
            lambda e: events.append(e) if e.type in (
                EventType.MEETING_CREATED, EventType.MEETING_STARTED, EventType.MEETING_COMPLETED,
            ) else None
        )

        project = await ctx.project_service.create_project(ProjectCreate(name="Meeting Project"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id, title="Do X", mode=TaskMode.DEBATE,
                input={
                    "agent_ids": ["agent_generalist", "agent_reviewer", "agent_coder"],
                    "scenario": MockScenario.SUCCESS.value,
                },
            )
        )
        execution = await ctx.engine.run(task)
        assert execution.status == ExecutionStatus.COMPLETED

        kinds = [e.type for e in events]
        assert kinds == [EventType.MEETING_CREATED, EventType.MEETING_STARTED, EventType.MEETING_COMPLETED]

        # Real, dynamic participants -- exactly the 3 debating agents, not
        # a hardcoded 4-person roster (spec section 58/59).
        participants = set(events[0].payload["participants"])
        assert participants == {"agent_generalist", "agent_reviewer", "agent_coder"}
        assert events[1].payload["participants"] == events[0].payload["participants"]
        assert events[2].payload["participants"] == events[0].payload["participants"]
    finally:
        await ctx.close()


async def test_consensus_mode_participants_are_only_the_agents_actually_involved(tmp_path: Path) -> None:
    ctx = await build_context(tmp_path / "meeting2.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        events: list[OrchestrationEvent] = []
        ctx.event_bus.subscribe(
            lambda e: events.append(e) if e.type == EventType.MEETING_CREATED else None
        )

        project = await ctx.project_service.create_project(ProjectCreate(name="Consensus Project"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id, title="Do X", mode=TaskMode.CONSENSUS,
                input={"agent_ids": ["agent_generalist", "agent_coder"], "scenario": MockScenario.SUCCESS.value},
            )
        )
        await ctx.engine.run(task)

        assert len(events) == 1
        assert set(events[0].payload["participants"]) == {"agent_generalist", "agent_coder"}
    finally:
        await ctx.close()


async def test_manual_mode_never_publishes_a_meeting_single_agent_never_gathers(tmp_path: Path) -> None:
    """Regression guard: a single agent working alone must never be
    reported as a 'meeting' of one (spec section 58 -- only when it
    actually makes sense)."""
    ctx = await build_context(tmp_path / "no_meeting.db", provider_overrides={"mock": MockProvider()}, secret_store=InMemorySecretStore())
    try:
        events: list[OrchestrationEvent] = []
        ctx.event_bus.subscribe(
            lambda e: events.append(e) if e.type in (
                EventType.MEETING_CREATED, EventType.MEETING_STARTED, EventType.MEETING_COMPLETED,
            ) else None
        )

        project = await ctx.project_service.create_project(ProjectCreate(name="Manual Project"))
        task = await ctx.task_service.create_task(
            TaskCreate(
                project_id=project.id, title="Do X", mode=TaskMode.MANUAL,
                input={"agent_id": "agent_coder", "scenario": MockScenario.SUCCESS.value},
            )
        )
        await ctx.engine.run(task)

        assert events == []
    finally:
        await ctx.close()
