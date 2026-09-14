"""Bridge command tests for `team.*` (AgentMash V2, Phase 4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.security.secret_store import InMemorySecretStore


@pytest.fixture
async def ctx(tmp_path: Path):
    context = await build_context(tmp_path / "bridge-teams-test.db", secret_store=InMemorySecretStore())
    try:
        yield context
    finally:
        await context.db.close()


async def test_team_create_and_list(ctx) -> None:
    project = await dispatch("project.create", {"name": "AgentMash"}, ctx)
    team = await dispatch("team.create", {"name": "Core", "project_id": project["id"]}, ctx)
    assert team["project_id"] == project["id"]

    listed = await dispatch("team.list", {}, ctx)
    assert any(t["id"] == team["id"] for t in listed)
    assert next(t for t in listed if t["id"] == team["id"])["agent_ids"] == []


async def test_team_list_scoped_to_a_project(ctx) -> None:
    project_a = await dispatch("project.create", {"name": "A"}, ctx)
    project_b = await dispatch("project.create", {"name": "B"}, ctx)
    team_a = await dispatch("team.create", {"name": "Team A", "project_id": project_a["id"]}, ctx)
    await dispatch("team.create", {"name": "Team B", "project_id": project_b["id"]}, ctx)

    scoped = await dispatch("team.list", {"project_id": project_a["id"]}, ctx)
    assert [t["id"] for t in scoped] == [team_a["id"]]


async def test_team_assign_and_remove_agent(ctx) -> None:
    team = await dispatch("team.create", {"name": "Core"}, ctx)
    agent = await dispatch("agent.create", {"name": "Atlas"}, ctx)

    await dispatch("team.assign_agent", {"team_id": team["id"], "agent_id": agent["id"]}, ctx)
    listed = await dispatch("team.list", {}, ctx)
    assert next(t for t in listed if t["id"] == team["id"])["agent_ids"] == [agent["id"]]

    await dispatch("team.remove_agent", {"team_id": team["id"], "agent_id": agent["id"]}, ctx)
    listed_after = await dispatch("team.list", {}, ctx)
    assert next(t for t in listed_after if t["id"] == team["id"])["agent_ids"] == []


async def test_team_update_and_delete(ctx) -> None:
    team = await dispatch("team.create", {"name": "Old Name"}, ctx)
    updated = await dispatch("team.update", {"team_id": team["id"], "name": "New Name"}, ctx)
    assert updated["name"] == "New Name"

    result = await dispatch("team.delete", {"team_id": team["id"]}, ctx)
    assert result["deleted"] is True
    assert team["id"] not in [t["id"] for t in await dispatch("team.list", {}, ctx)]
