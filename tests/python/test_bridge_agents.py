"""Bridge command tests for `agent.create`/`agent.update`/`agent.list`
(AgentMash V2, Phase 4). `agent.list`'s existing shape/behavior for the
seeded routing agents is covered elsewhere (`test_bridge.py` and friends)
-- this file covers the new project-assignment/team-enrichment path.
"""

from __future__ import annotations

from pathlib import Path

import pydantic
import pytest
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.security.secret_store import InMemorySecretStore


@pytest.fixture
async def ctx(tmp_path: Path):
    context = await build_context(tmp_path / "bridge-agents-test.db", secret_store=InMemorySecretStore())
    try:
        yield context
    finally:
        await context.db.close()


async def test_agent_create_persists_and_returns_a_real_agent(ctx) -> None:
    project = await dispatch("project.create", {"name": "AgentMash"}, ctx)
    result = await dispatch(
        "agent.create",
        {"name": "Atlas", "role": "Software Architect", "project_id": project["id"]},
        ctx,
    )
    assert result["name"] == "Atlas"
    assert result["role"] == "Software Architect"
    assert result["project_id"] == project["id"]
    assert result["team_ids"] == []

    listed = await dispatch("agent.list", {}, ctx)
    assert any(a["id"] == result["id"] for a in listed)


async def test_agent_create_rejects_a_blank_name(ctx) -> None:
    with pytest.raises(pydantic.ValidationError):
        await dispatch("agent.create", {"name": "   "}, ctx)


async def test_agent_update_reassigns_project(ctx) -> None:
    project_a = await dispatch("project.create", {"name": "A"}, ctx)
    project_b = await dispatch("project.create", {"name": "B"}, ctx)
    agent = await dispatch("agent.create", {"name": "Forge", "project_id": project_a["id"]}, ctx)

    updated = await dispatch(
        "agent.update", {"agent_id": agent["id"], "project_id": project_b["id"]}, ctx
    )
    assert updated["project_id"] == project_b["id"]


async def test_agent_update_can_disable_an_agent(ctx) -> None:
    agent = await dispatch("agent.create", {"name": "Nova"}, ctx)
    updated = await dispatch("agent.update", {"agent_id": agent["id"], "active": False}, ctx)
    assert updated["active"] is False


async def test_agent_list_enriches_with_real_team_ids(ctx) -> None:
    agent = await dispatch("agent.create", {"name": "Sentinel"}, ctx)
    team = await dispatch("team.create", {"name": "Core"}, ctx)
    await dispatch("team.assign_agent", {"team_id": team["id"], "agent_id": agent["id"]}, ctx)

    listed = await dispatch("agent.list", {}, ctx)
    found = next(a for a in listed if a["id"] == agent["id"])
    assert found["team_ids"] == [team["id"]]
