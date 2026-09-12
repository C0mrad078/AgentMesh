from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.memory_conflicts_repo import MemoryConflictsRepository
from core.database.repositories.project_memories_repo import ProjectMemoriesRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.memory.models import MemoryCategory, MemoryProvenance, MemoryWrite
from core.memory.store import SqliteMemoryStore
from core.projects.models import ProjectCreate


async def _make_project(db: Database) -> str:
    project = await ProjectsRepository(db).create(ProjectCreate(name="Memory Project"))
    return project.id


async def test_a_new_contradicting_value_supersedes_the_old_one(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db), MemoryConflictsRepository(tmp_db))

    await store.remember(MemoryWrite(project_id=project_id, key="db", category=MemoryCategory.STACK, value={"database": "Supabase"}))
    await store.remember(MemoryWrite(project_id=project_id, key="db", category=MemoryCategory.STACK, value={"database": "PostgreSQL"}))

    active = await store.recall(project_id, "db")
    assert active.value == {"database": "PostgreSQL"}

    history = await store.history(project_id, "db")
    assert len(history) == 2
    assert sum(1 for h in history if h.valid_until is None) == 1


async def test_conflict_is_recorded_for_auditability(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    conflicts_repo = MemoryConflictsRepository(tmp_db)
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db), conflicts_repo)

    await store.remember(MemoryWrite(project_id=project_id, key="db", value={"database": "Supabase"}))
    await store.remember(MemoryWrite(project_id=project_id, key="db", value={"database": "PostgreSQL"}))

    conflicts = await conflicts_repo.list_for_project(project_id)
    assert len(conflicts) == 1
    assert "db" in conflicts[0]["detail"]


async def test_reobserving_an_identical_value_is_not_a_conflict(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    conflicts_repo = MemoryConflictsRepository(tmp_db)
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db), conflicts_repo)

    await store.remember(MemoryWrite(project_id=project_id, key="db", value={"database": "Supabase"}, confidence=0.5))
    await store.remember(MemoryWrite(project_id=project_id, key="db", value={"database": "Supabase"}, confidence=0.9))

    history = await store.history(project_id, "db")
    assert len(history) == 1
    assert history[0].confidence == 0.9
    assert await conflicts_repo.list_for_project(project_id) == []


async def test_user_supplied_facts_are_always_fully_confident(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))

    written = await store.remember(MemoryWrite(
        project_id=project_id, key="stack", value={"language": "TypeScript"}, confidence=0.3,
        provenance=MemoryProvenance(source_user_input=True),
    ))
    assert written.confidence == 1.0


async def test_inferred_facts_keep_their_given_confidence(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))

    written = await store.remember(MemoryWrite(
        project_id=project_id, key="stack", value={"language": "TypeScript"}, confidence=0.4,
        provenance=MemoryProvenance(source_execution_id="exec_1"),
    ))
    assert written.confidence == 0.4
    assert written.provenance.source_execution_id == "exec_1"


async def test_category_taxonomy_is_persisted(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))
    written = await store.remember(MemoryWrite(
        project_id=project_id, key="deploy", category=MemoryCategory.DEPLOYMENT, value={"target": "fly.io"},
    ))
    assert written.category == MemoryCategory.DEPLOYMENT
