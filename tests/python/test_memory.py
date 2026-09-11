from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.project_memories_repo import ProjectMemoriesRepository
from core.database.repositories.projects_repo import ProjectsRepository
from core.memory.models import MemoryKind, MemoryWrite
from core.memory.store import SqliteMemoryStore
from core.projects.models import ProjectCreate


async def _make_project(db: Database) -> str:
    project = await ProjectsRepository(db).create(ProjectCreate(name="Memory Project"))
    return project.id


async def test_remember_and_recall(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))

    written = await store.remember(
        MemoryWrite(project_id=project_id, key="preference.language", value={"language": "pt-BR"})
    )
    assert written.key == "preference.language"

    recalled = await store.recall(project_id, "preference.language")
    assert recalled is not None
    assert recalled.value == {"language": "pt-BR"}


async def test_remembering_the_same_key_twice_updates_in_place(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))

    await store.remember(MemoryWrite(project_id=project_id, key="k", value={"v": 1}))
    await store.remember(MemoryWrite(project_id=project_id, key="k", value={"v": 2}, importance=0.9))

    all_memories = await store.recall_all(project_id)
    matching = [m for m in all_memories if m.key == "k"]
    assert len(matching) == 1
    assert matching[0].value == {"v": 2}
    assert matching[0].importance == 0.9


async def test_memory_is_scoped_per_project(tmp_db: Database) -> None:
    project_a = await _make_project(tmp_db)
    project_b = await ProjectsRepository(tmp_db).create(ProjectCreate(name="Other"))
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))

    await store.remember(MemoryWrite(project_id=project_a, key="shared-key", value={"owner": "a"}))
    await store.remember(MemoryWrite(project_id=project_b.id, key="shared-key", value={"owner": "b"}))

    assert (await store.recall(project_a, "shared-key")).value == {"owner": "a"}  # type: ignore[union-attr]
    assert (await store.recall(project_b.id, "shared-key")).value == {"owner": "b"}  # type: ignore[union-attr]


async def test_recall_missing_key_returns_none(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))
    assert await store.recall(project_id, "does-not-exist") is None


async def test_memory_kind_defaults_to_fact(tmp_db: Database) -> None:
    project_id = await _make_project(tmp_db)
    store = SqliteMemoryStore(ProjectMemoriesRepository(tmp_db))
    written = await store.remember(MemoryWrite(project_id=project_id, key="k", value={}))
    assert written.kind == MemoryKind.FACT
