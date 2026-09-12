from __future__ import annotations

import pytest
from core.database.connection import Database
from core.database.repositories.prompt_versions_repo import PromptVersionsRepository
from core.learning.models import PromptType
from core.utils.errors import ImmutablePolicyError


async def test_seed_by_key_creates_the_first_version_only_once(tmp_db: Database) -> None:
    repo = PromptVersionsRepository(tmp_db)
    first = await repo.seed_by_key("planner", name="planner_default", content="v1", prompt_type="planner")
    second = await repo.seed_by_key("planner", name="planner_default", content="v2 -- should be ignored", prompt_type="planner")
    assert first["id"] == second["id"]
    assert second["content"] == "v1"


async def test_new_version_deactivates_the_previous_one(tmp_db: Database) -> None:
    repo = PromptVersionsRepository(tmp_db)
    v1 = await repo.seed_by_key("router", name="router_default", content="v1", prompt_type="router")
    v2 = await repo.create_version_by_key(
        owner_key="router", name="router_v2", content="v2", prompt_type="router",
        author="user", origin="user", reason="tuning",
    )
    versions = await repo.list_by_key("router")
    by_id = {v["id"]: v for v in versions}
    assert by_id[v1["id"]]["active"] is False
    assert by_id[v2["id"]]["active"] is True
    assert v2["version"] == v1["version"] + 1
    assert v2["previous_version_id"] == v1["id"]


async def test_rollback_creates_a_new_version_rather_than_rewriting_history(tmp_db: Database) -> None:
    repo = PromptVersionsRepository(tmp_db)
    v1 = await repo.seed_by_key("verifier", name="v", content="original", prompt_type="verifier")
    await repo.create_version_by_key(
        owner_key="verifier", name="v2", content="changed", prompt_type="verifier",
        author="user", origin="user", reason="edit",
    )
    rolled_back = await repo.rollback_to("verifier", v1["id"], reason="regressed")

    active = await repo.get_active_by_key("verifier")
    assert active["id"] == rolled_back["id"]
    assert active["content"] == "original"
    assert active["origin"] == "rollback"

    history = await repo.list_by_key("verifier")
    assert len(history) == 3  # v1, v2, and the rollback version -- nothing deleted


async def test_core_prompt_cannot_be_changed_automatically(tmp_db: Database) -> None:
    repo = PromptVersionsRepository(tmp_db)
    await repo.seed_by_key("core", name="core_prompt", content="original core text", prompt_type=PromptType.CORE.value)

    with pytest.raises(ImmutablePolicyError):
        await repo.create_version_by_key(
            owner_key="core", name="core_v2", content="mutated by automation", prompt_type=PromptType.CORE.value,
            author="learning_engine", origin="learning_engine", reason="auto-improvement",
        )

    active = await repo.get_active_by_key("core")
    assert active["content"] == "original core text"


async def test_core_prompt_can_be_changed_by_an_explicit_user_action(tmp_db: Database) -> None:
    repo = PromptVersionsRepository(tmp_db)
    await repo.seed_by_key("core", name="core_prompt", content="original", prompt_type=PromptType.CORE.value)

    updated = await repo.create_version_by_key(
        owner_key="core", name="core_v2", content="user-approved change", prompt_type=PromptType.CORE.value,
        author="user", origin="user", reason="explicit admin edit",
    )
    assert updated["content"] == "user-approved change"
    assert updated["protected"] is True


async def test_agent_prompt_can_be_created_by_the_learning_engine(tmp_db: Database) -> None:
    repo = PromptVersionsRepository(tmp_db)
    await repo.seed_by_key("agent_claude_reviewer", name="v", content="Revise o código.", prompt_type=PromptType.AGENT.value)
    updated = await repo.create_version_by_key(
        owner_key="agent_claude_reviewer", name="v2",
        content="Revise o código verificando regressões e segurança.", prompt_type=PromptType.AGENT.value,
        author="learning_engine", origin="prompt_optimizer", reason="reflection feedback",
    )
    assert updated["active"] is True
    assert updated["protected"] is False
