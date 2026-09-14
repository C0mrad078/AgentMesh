from __future__ import annotations

from pathlib import Path

from core.agents.models import Agent, AgentStatus
from core.database.connection import Database
from core.database.repositories.agents_repo import AgentsRepository
from core.runtime.execution_backend import ExecutionBackendType


async def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "agents.db")
    await db.connect()
    return db


async def test_preferred_provider_and_fallback_providers_round_trip(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        repo = AgentsRepository(db)
        agent = Agent(
            id="agent_test_fallback", name="Test", provider="codex_cli",
            preferred_provider="codex_cli", fallback_providers=["claude_code_cli", "openai"],
        )
        await repo.upsert(agent)

        loaded = await repo.get("agent_test_fallback")
        assert loaded is not None
        assert loaded.preferred_provider == "codex_cli"
        assert loaded.fallback_providers == ["claude_code_cli", "openai"]
        assert loaded.effective_preferred_provider == "codex_cli"
    finally:
        await db.close()


async def test_agent_without_preferred_provider_falls_back_to_the_provider_field(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        repo = AgentsRepository(db)
        agent = Agent(id="agent_plain", name="Plain", provider="anthropic")
        await repo.upsert(agent)

        loaded = await repo.get("agent_plain")
        assert loaded is not None
        assert loaded.preferred_provider is None
        assert loaded.fallback_providers == []
        assert loaded.effective_preferred_provider == "anthropic"
    finally:
        await db.close()


async def test_presence_and_backend_fields_round_trip(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        repo = AgentsRepository(db)
        agent = Agent(
            id="agent_atlas", name="Atlas", provider="claude_code_cli", role="Software Architect",
            avatar="preset_architect", status=AgentStatus.WORKING,
            preferred_backend=ExecutionBackendType.SUBSCRIPTION,
            fallback_backend=ExecutionBackendType.API,
            memory_profile={"style": "concise"},
        )
        await repo.upsert(agent)

        loaded = await repo.get("agent_atlas")
        assert loaded is not None
        assert loaded.role == "Software Architect"
        assert loaded.avatar == "preset_architect"
        assert loaded.status == AgentStatus.WORKING
        assert loaded.preferred_backend == ExecutionBackendType.SUBSCRIPTION
        assert loaded.fallback_backend == ExecutionBackendType.API
        assert loaded.memory_profile == {"style": "concise"}
    finally:
        await db.close()


async def test_presence_and_backend_fields_default_sensibly(tmp_path: Path) -> None:
    db = await _db(tmp_path)
    try:
        repo = AgentsRepository(db)
        agent = Agent(id="agent_plain", name="Plain", provider="anthropic")
        await repo.upsert(agent)

        loaded = await repo.get("agent_plain")
        assert loaded is not None
        assert loaded.role == ""
        assert loaded.avatar is None
        # Nothing computes real presence yet (Phase 8) -- IDLE is the inert
        # default, not a claimed live signal. See docs/refactor-v2-plan.md §4.
        assert loaded.status == AgentStatus.IDLE
        assert loaded.preferred_backend is None
        assert loaded.fallback_backend is None
        assert loaded.memory_profile == {}
    finally:
        await db.close()
