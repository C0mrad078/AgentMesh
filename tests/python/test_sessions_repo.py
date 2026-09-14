from __future__ import annotations

from core.agents.models import Agent
from core.database.connection import Database
from core.database.repositories.agents_repo import AgentsRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.providers_repo import ProvidersRepository
from core.database.repositories.sessions_repo import SessionsRepository
from core.projects.models import ProjectCreate
from core.runtime.execution_backend import ExecutionBackendType
from core.sessions.models import SessionCreate, SessionStatus


async def _setup(tmp_db: Database) -> tuple[str, str, str]:
    project = await ProjectsRepository(tmp_db).create(ProjectCreate(name="AgentMash"))
    agent = Agent(id="agent_atlas", name="Atlas", provider="claude_code_cli")
    await AgentsRepository(tmp_db).upsert(agent)
    claude = await ProvidersRepository(tmp_db).get_by_name("claude")
    assert claude is not None
    return project.id, agent.id, claude.id


async def test_create_session_starts_in_created_status(tmp_db: Database) -> None:
    project_id, agent_id, provider_id = await _setup(tmp_db)
    repo = SessionsRepository(tmp_db)

    session = await repo.create(
        SessionCreate(
            agent_id=agent_id, project_id=project_id, provider_id=provider_id,
            backend_type=ExecutionBackendType.SUBSCRIPTION,
        )
    )
    assert session.status == SessionStatus.CREATED
    assert session.started_at is None
    assert session.finished_at is None


async def test_update_status_sets_started_at_once(tmp_db: Database) -> None:
    project_id, agent_id, provider_id = await _setup(tmp_db)
    repo = SessionsRepository(tmp_db)
    session = await repo.create(
        SessionCreate(
            agent_id=agent_id, project_id=project_id, provider_id=provider_id,
            backend_type=ExecutionBackendType.SUBSCRIPTION,
        )
    )

    working = await repo.update_status(session.id, SessionStatus.WORKING, started=True)
    assert working.started_at is not None
    first_started_at = working.started_at

    waiting = await repo.update_status(session.id, SessionStatus.WAITING, started=True)
    assert waiting.started_at == first_started_at  # never overwritten once set


async def test_update_status_to_terminal_sets_finished_at(tmp_db: Database) -> None:
    project_id, agent_id, provider_id = await _setup(tmp_db)
    repo = SessionsRepository(tmp_db)
    session = await repo.create(
        SessionCreate(
            agent_id=agent_id, project_id=project_id, provider_id=provider_id,
            backend_type=ExecutionBackendType.SUBSCRIPTION,
        )
    )
    completed = await repo.update_status(session.id, SessionStatus.COMPLETED, finished=True)
    assert completed.finished_at is not None


async def test_set_external_session_id(tmp_db: Database) -> None:
    project_id, agent_id, provider_id = await _setup(tmp_db)
    repo = SessionsRepository(tmp_db)
    session = await repo.create(
        SessionCreate(
            agent_id=agent_id, project_id=project_id, provider_id=provider_id,
            backend_type=ExecutionBackendType.SESSION,
        )
    )
    updated = await repo.set_external_session_id(session.id, "claude-session-A92F")
    assert updated.external_session_id == "claude-session-A92F"


async def test_merge_metadata_preserves_existing_keys(tmp_db: Database) -> None:
    project_id, agent_id, provider_id = await _setup(tmp_db)
    repo = SessionsRepository(tmp_db)
    session = await repo.create(
        SessionCreate(
            agent_id=agent_id, project_id=project_id, provider_id=provider_id,
            backend_type=ExecutionBackendType.API, metadata={"a": 1},
        )
    )
    updated = await repo.merge_metadata(session.id, {"b": 2})
    assert updated.metadata == {"a": 1, "b": 2}


async def test_list_active_excludes_terminal_sessions(tmp_db: Database) -> None:
    project_id, agent_id, provider_id = await _setup(tmp_db)
    repo = SessionsRepository(tmp_db)
    active = await repo.create(
        SessionCreate(
            agent_id=agent_id, project_id=project_id, provider_id=provider_id,
            backend_type=ExecutionBackendType.SUBSCRIPTION,
        )
    )
    done = await repo.create(
        SessionCreate(
            agent_id=agent_id, project_id=project_id, provider_id=provider_id,
            backend_type=ExecutionBackendType.SUBSCRIPTION,
        )
    )
    await repo.update_status(done.id, SessionStatus.COMPLETED, finished=True)

    active_sessions = await repo.list_active()
    assert [s.id for s in active_sessions] == [active.id]


async def test_list_by_agent_and_project(tmp_db: Database) -> None:
    project_id, agent_id, provider_id = await _setup(tmp_db)
    repo = SessionsRepository(tmp_db)
    session = await repo.create(
        SessionCreate(
            agent_id=agent_id, project_id=project_id, provider_id=provider_id,
            backend_type=ExecutionBackendType.SUBSCRIPTION,
        )
    )
    assert [s.id for s in await repo.list_by_agent(agent_id)] == [session.id]
    assert [s.id for s in await repo.list_by_project(project_id)] == [session.id]
