"""Refactor V2, Phase 1 (docs/refactor-v2-plan.md §4): the four memory
scopes (global/project/agent/session). `test_memory.py` already covers
project scope end-to-end (unchanged by this refactor); this file covers
the three new ones plus the validator that keeps a `MemoryWrite`'s scope
and identifier columns from disagreeing.
"""

from __future__ import annotations

import pytest
from core.agents.models import Agent
from core.database.connection import Database
from core.database.repositories.agents_repo import AgentsRepository
from core.database.repositories.project_memories_repo import ProjectMemoriesRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.database.repositories.providers_repo import ProvidersRepository
from core.database.repositories.sessions_repo import SessionsRepository
from core.memory.models import MemoryScope, MemoryWrite
from core.memory.store import SqliteMemoryStore
from core.projects.models import ProjectCreate
from core.runtime.execution_backend import ExecutionBackendType
from core.sessions.models import SessionCreate
from pydantic import ValidationError


async def _real_agent(tmp_db: Database, agent_id: str) -> str:
    # `project_memories.agent_id` carries a real FK to `agents(id)` -- an
    # agent-scoped memory can only ever point at a real, persisted agent.
    await AgentsRepository(tmp_db).upsert(Agent(id=agent_id, name=agent_id, provider="claude_code_cli"))
    return agent_id


async def _real_session(tmp_db: Database) -> str:
    project = await ProjectsRepository(tmp_db).create(ProjectCreate(name="P"))
    agent_id = await _real_agent(tmp_db, "agent_session_owner")
    claude = await ProvidersRepository(tmp_db).get_by_name("claude")
    assert claude is not None
    session = await SessionsRepository(tmp_db).create(
        SessionCreate(
            agent_id=agent_id, project_id=project.id, provider_id=claude.id,
            backend_type=ExecutionBackendType.SUBSCRIPTION,
        )
    )
    return session.id


async def test_global_memory_round_trips_with_no_project(tmp_db: Database) -> None:
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))
    written = await store.remember(
        MemoryWrite(scope=MemoryScope.GLOBAL, key="operating.rule", value={"rule": "no arbitrary shell"})
    )
    assert written.project_id is None
    assert written.scope == MemoryScope.GLOBAL

    recalled = await store.recall_global("operating.rule")
    assert recalled is not None
    assert recalled.value == {"rule": "no arbitrary shell"}


async def test_agent_memory_is_scoped_per_agent(tmp_db: Database) -> None:
    atlas_id = await _real_agent(tmp_db, "agent_atlas")
    forge_id = await _real_agent(tmp_db, "agent_forge")
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))
    await store.remember(
        MemoryWrite(scope=MemoryScope.AGENT, agent_id=atlas_id, key="learned.fact", value={"v": "a"})
    )
    await store.remember(
        MemoryWrite(scope=MemoryScope.AGENT, agent_id=forge_id, key="learned.fact", value={"v": "b"})
    )

    atlas_memory = await store.recall_for_agent(atlas_id, "learned.fact")
    forge_memory = await store.recall_for_agent(forge_id, "learned.fact")
    assert atlas_memory is not None and atlas_memory.value == {"v": "a"}
    assert forge_memory is not None and forge_memory.value == {"v": "b"}

    all_for_atlas = await store.recall_all_for_agent(atlas_id)
    assert [m.key for m in all_for_atlas] == ["learned.fact"]


async def test_session_memory_is_scoped_per_session(tmp_db: Database) -> None:
    session_id = await _real_session(tmp_db)
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))
    await store.remember(
        MemoryWrite(scope=MemoryScope.SESSION, session_id=session_id, key="current.file", value={"path": "a.py"})
    )

    recalled = await store.recall_for_session(session_id, "current.file")
    assert recalled is not None
    assert recalled.value == {"path": "a.py"}
    assert await store.recall_for_session("sess_does_not_exist", "current.file") is None


async def test_updating_a_scoped_memory_supersedes_not_duplicates(tmp_db: Database) -> None:
    agent_id = await _real_agent(tmp_db, "agent_x")
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))
    await store.remember(MemoryWrite(scope=MemoryScope.AGENT, agent_id=agent_id, key="k", value={"v": 1}))
    await store.remember(MemoryWrite(scope=MemoryScope.AGENT, agent_id=agent_id, key="k", value={"v": 2}))

    all_for_agent = await store.recall_all_for_agent(agent_id)
    matching = [m for m in all_for_agent if m.key == "k"]
    assert len(matching) == 1
    assert matching[0].value == {"v": 2}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scope": MemoryScope.GLOBAL, "project_id": "proj_x", "key": "k"},  # global must have no identifier
        {"scope": MemoryScope.PROJECT, "key": "k"},  # project scope requires project_id
        {"scope": MemoryScope.AGENT, "session_id": "sess_x", "key": "k"},  # wrong identifier for scope
        {"scope": MemoryScope.SESSION, "key": "k"},  # session scope requires session_id
    ],
)
def test_mismatched_scope_and_identifier_is_rejected(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        MemoryWrite(**kwargs)
