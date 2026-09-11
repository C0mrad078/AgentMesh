"""Wires up every service the bridge handlers depend on.

Constructed once at sidecar startup (`core.bridge.main`) and passed into
`core.bridge.handlers.dispatch`. Centralizing construction here means
`main.py` stays a thin entrypoint and tests can build a `BridgeContext`
against a temporary database without going through the real process
bootstrap.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.agents.registry import AgentRegistry
from core.database.connection import Database
from core.database.repositories.agents_repo import AgentsRepository
from core.database.repositories.audit_logs_repo import AuditLogsRepository
from core.database.repositories.execution_steps_repo import ExecutionStepsRepository
from core.database.repositories.executions_repo import ExecutionsRepository
from core.database.repositories.project_memories_repo import ProjectMemoriesRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.settings_repo import SettingsRepository
from core.database.repositories.tasks_repo import TasksRepository
from core.memory.store import SqliteMemoryStore
from core.orchestrator.engine import ExecutionEngine
from core.orchestrator.events import EventSink, noop_sink
from core.projects.service import ProjectService
from core.providers.base import ProviderAdapter
from core.providers.mock_provider import MockProvider
from core.security.audit import AuditLogger
from core.tasks.service import TaskService


@dataclass
class BridgeContext:
    db: Database
    project_service: ProjectService
    task_service: TaskService
    agent_registry: AgentRegistry
    agents_repo: AgentsRepository
    executions_repo: ExecutionsRepository
    steps_repo: ExecutionStepsRepository
    settings_repo: SettingsRepository
    memory_store: SqliteMemoryStore
    engine: ExecutionEngine
    provider: ProviderAdapter


async def build_context(
    db_path: Path | str, *, event_sink: EventSink | None = None
) -> BridgeContext:
    db = Database(db_path)
    await db.connect()

    audit_logger = AuditLogger(AuditLogsRepository(db))
    project_service = ProjectService(ProjectsRepository(db), audit_logger)
    task_service = TaskService(TasksRepository(db))
    agent_registry = AgentRegistry()
    agents_repo = AgentsRepository(db)
    await agents_repo.seed_defaults(agent_registry.list_agents(only_active=False))

    executions_repo = ExecutionsRepository(db)
    steps_repo = ExecutionStepsRepository(db)
    settings_repo = SettingsRepository(db)
    memory_store = SqliteMemoryStore(ProjectMemoriesRepository(db))
    provider = MockProvider()

    engine = ExecutionEngine(
        executions_repo, steps_repo, task_service, agent_registry, provider,
        event_sink=event_sink or noop_sink,
    )

    return BridgeContext(
        db=db,
        project_service=project_service,
        task_service=task_service,
        agent_registry=agent_registry,
        agents_repo=agents_repo,
        executions_repo=executions_repo,
        steps_repo=steps_repo,
        settings_repo=settings_repo,
        memory_store=memory_store,
        engine=engine,
        provider=provider,
    )
