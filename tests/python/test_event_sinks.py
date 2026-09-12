from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.execution_events_repo import ExecutionEventsRepository
from core.database.repositories.executions_repo import ExecutionsRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.provider_health_repo import ProviderHealthRepository
from core.database.repositories.routing_decisions_repo import RoutingDecisionsRepository
from core.database.repositories.tasks_repo import TasksRepository
from core.database.repositories.tool_calls_repo import ToolCallsRepository
from core.database.repositories.usage_metrics_repo import UsageMetricsRepository
from core.orchestrator.event_bus import EventType, OrchestrationEvent
from core.orchestrator.event_sinks import (
    make_audit_trail_sink,
    make_provider_health_sink,
    make_routing_decision_sink,
    make_tool_calls_sink,
    make_usage_metrics_sink,
)
from core.projects.models import ProjectCreate
from core.providers.base import ProviderHealthStatus
from core.providers.health import ProviderHealthSnapshot
from core.tasks.models import TaskCreate


async def _make_execution_id(db: Database) -> str:
    project = await ProjectsRepository(db).create(ProjectCreate(name="Event Sink Test"))
    task = await TasksRepository(db).create(TaskCreate(project_id=project.id, title="x"))
    execution = await ExecutionsRepository(db).create(task_id=task.id, project_id=project.id)
    return execution.id


async def test_audit_trail_sink_records_every_event(tmp_db: Database) -> None:
    execution_id = await _make_execution_id(tmp_db)
    repo = ExecutionEventsRepository(tmp_db)
    sink = make_audit_trail_sink(repo)
    await sink(OrchestrationEvent(type=EventType.STEP_STARTED, execution_id=execution_id, task_id="t1"))
    events = await repo.list_for_execution(execution_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "step.started"


async def test_routing_decision_sink_only_reacts_to_agent_selected(tmp_db: Database) -> None:
    execution_id = await _make_execution_id(tmp_db)
    repo = RoutingDecisionsRepository(tmp_db)
    sink = make_routing_decision_sink(repo)

    await sink(OrchestrationEvent(type=EventType.STEP_STARTED, execution_id=execution_id))
    assert await repo.list_for_execution(execution_id) == []

    await sink(OrchestrationEvent(
        type=EventType.AGENT_SELECTED, execution_id=execution_id,
        payload={"step_id": "s1", "agent_id": "a1", "provider": "mock", "model": "m1", "reason": "r", "score": 1.5},
    ))
    decisions = await repo.list_for_execution(execution_id)
    assert len(decisions) == 1
    assert decisions[0]["agent_id"] == "a1"
    assert decisions[0]["score"] == 1.5


async def test_tool_calls_sink_only_reacts_to_tool_completed(tmp_db: Database) -> None:
    execution_id = await _make_execution_id(tmp_db)
    repo = ToolCallsRepository(tmp_db)
    sink = make_tool_calls_sink(repo)

    await sink(OrchestrationEvent(type=EventType.TOOL_STARTED, execution_id=execution_id))
    assert await repo.list_for_execution(execution_id) == []

    await sink(OrchestrationEvent(
        type=EventType.TOOL_COMPLETED, execution_id=execution_id,
        payload={"step_id": "s1", "agent_id": "a1", "tool": "ReadFile", "arguments": {"path": "a.py"}, "error": None, "duration_seconds": 0.1},
    ))
    calls = await repo.list_for_execution(execution_id)
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "ReadFile"


async def test_usage_metrics_sink_ignores_events_without_usage(tmp_db: Database) -> None:
    execution_id = await _make_execution_id(tmp_db)
    repo = UsageMetricsRepository(tmp_db)
    sink = make_usage_metrics_sink(repo)

    await sink(OrchestrationEvent(
        type=EventType.STEP_COMPLETED, execution_id=execution_id, payload={"step_id": "synth", "status": "completed"},
    ))
    assert await repo.list_for_execution(execution_id) == []


async def test_usage_metrics_sink_records_token_usage(tmp_db: Database) -> None:
    execution_id = await _make_execution_id(tmp_db)
    repo = UsageMetricsRepository(tmp_db)
    sink = make_usage_metrics_sink(repo)

    await sink(OrchestrationEvent(
        type=EventType.STEP_COMPLETED, execution_id=execution_id,
        payload={
            "step_id": "s1", "agent_id": "a1", "provider": "mock", "model": "m1",
            "input_tokens": 10, "output_tokens": 5, "estimated_cost_usd": 0.01,
            "attempts": 2, "success": True,
        },
    ))
    entries = await repo.list_for_execution(execution_id)
    assert len(entries) == 1
    assert entries[0]["input_tokens"] == 10
    assert entries[0]["retries"] == 1


async def test_provider_health_sink_persists_snapshot(tmp_db: Database) -> None:
    repo = ProviderHealthRepository(tmp_db)
    sink = make_provider_health_sink(repo)
    await sink("anthropic", ProviderHealthSnapshot(
        provider="anthropic", status=ProviderHealthStatus.ONLINE, last_error=None, consecutive_failures=0,
    ))
    rows = await repo.list_all()
    assert rows[0]["provider"] == "anthropic"
    assert rows[0]["status"] == "online"
