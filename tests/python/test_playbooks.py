from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.playbooks_repo import (
    PlaybooksRepository,
    PlaybookVersionsRepository,
)
from core.learning.playbooks import PlaybookMatcher


def _matcher(db: Database) -> PlaybookMatcher:
    return PlaybookMatcher(PlaybooksRepository(db), PlaybookVersionsRepository(db))


async def test_seed_defaults_creates_the_two_worked_examples(tmp_db: Database) -> None:
    matcher = _matcher(tmp_db)
    await matcher.seed_defaults()
    playbooks = await PlaybooksRepository(tmp_db).list_all()
    names = {p["name"] for p in playbooks}
    assert "Debugging simples com contexto local suficiente" in names
    assert "Mudança de arquitetura com revisão independente" in names


async def test_seed_defaults_is_idempotent(tmp_db: Database) -> None:
    matcher = _matcher(tmp_db)
    await matcher.seed_defaults()
    await matcher.seed_defaults()
    playbooks = await PlaybooksRepository(tmp_db).list_all()
    assert len(playbooks) == 2


async def test_find_matching_returns_playbook_when_conditions_are_satisfied(tmp_db: Database) -> None:
    matcher = _matcher(tmp_db)
    await matcher.seed_defaults()
    match = await matcher.find_matching(task_type="debugging", context_tags=frozenset({"risk:low", "coding"}))
    assert match is not None
    assert match.name == "Debugging simples com contexto local suficiente"


async def test_find_matching_returns_none_when_conditions_are_not_satisfied(tmp_db: Database) -> None:
    matcher = _matcher(tmp_db)
    await matcher.seed_defaults()
    match = await matcher.find_matching(task_type="debugging", context_tags=frozenset({"risk:high"}))
    assert match is None


async def test_find_matching_ignores_low_confidence_versions(tmp_db: Database) -> None:
    playbooks_repo = PlaybooksRepository(tmp_db)
    versions_repo = PlaybookVersionsRepository(tmp_db)
    playbook = await playbooks_repo.create(task_type="testing", name="Weak playbook", conditions=[])
    await versions_repo.create_version(
        playbook["id"], strategy=[{"capability": "testing", "step_type": "verification", "description": "x"}],
        confidence=0.2, reason="seed",
    )
    matcher = PlaybookMatcher(playbooks_repo, versions_repo)
    match = await matcher.find_matching(task_type="testing", context_tags=frozenset())
    assert match is None


async def test_versioning_keeps_only_one_active_version(tmp_db: Database) -> None:
    playbooks_repo = PlaybooksRepository(tmp_db)
    versions_repo = PlaybookVersionsRepository(tmp_db)
    playbook = await playbooks_repo.create(task_type="testing", name="Evolving playbook", conditions=[])
    v1 = await versions_repo.create_version(playbook["id"], strategy=[], confidence=0.7, reason="seed")
    v2 = await versions_repo.create_version(playbook["id"], strategy=[], confidence=0.8, reason="adapted")

    history = await versions_repo.list_for_playbook(playbook["id"])
    active = [v for v in history if v["active"]]
    assert len(active) == 1
    assert active[0]["id"] == v2["id"]
    assert v2["version"] == v1["version"] + 1


async def test_record_outcome_updates_observations_and_successes(tmp_db: Database) -> None:
    playbooks_repo = PlaybooksRepository(tmp_db)
    versions_repo = PlaybookVersionsRepository(tmp_db)
    playbook = await playbooks_repo.create(task_type="testing", name="Tracked playbook", conditions=[])
    version = await versions_repo.create_version(playbook["id"], strategy=[], confidence=0.7, reason="seed")

    matcher = PlaybookMatcher(playbooks_repo, versions_repo)
    await matcher.record_outcome(version["id"], success=True)
    await matcher.record_outcome(version["id"], success=False)

    refreshed = await versions_repo.get_active(playbook["id"])
    assert refreshed["observations"] == 2
    assert refreshed["successes"] == 1


async def test_deprecating_a_playbook_removes_it_from_matching(tmp_db: Database) -> None:
    matcher = _matcher(tmp_db)
    await matcher.seed_defaults()
    playbooks = await PlaybooksRepository(tmp_db).list_all()
    debugging_playbook = next(p for p in playbooks if p["task_type"] == "debugging")
    await PlaybooksRepository(tmp_db).deprecate(debugging_playbook["id"])

    match = await matcher.find_matching(task_type="debugging", context_tags=frozenset({"risk:low"}))
    assert match is None
