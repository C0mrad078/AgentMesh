"""Bridge command tests for `session.list` (AgentMash V2, Phase 4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.security.secret_store import InMemorySecretStore
from core.sessions.models import SessionCreate


@pytest.fixture
async def ctx(tmp_path: Path):
    context = await build_context(tmp_path / "bridge-sessions-test.db", secret_store=InMemorySecretStore())
    try:
        yield context
    finally:
        await context.db.close()


async def _make_session(ctx, *, agent_id: str, project_id: str):
    provider = await ctx.providers_repo.get_by_name("claude")
    assert provider is not None
    return await ctx.sessions_repo.create(
        SessionCreate(
            agent_id=agent_id, project_id=project_id, provider_id=provider.id,
            backend_type="subscription",  # type: ignore[arg-type]
        )
    )


async def test_session_list_by_agent(ctx) -> None:
    project = await dispatch("project.create", {"name": "AgentMash"}, ctx)
    agent = await dispatch("agent.create", {"name": "Atlas", "project_id": project["id"]}, ctx)
    session = await _make_session(ctx, agent_id=agent["id"], project_id=project["id"])

    result = await dispatch("session.list", {"agent_id": agent["id"]}, ctx)
    assert [s["id"] for s in result] == [session.id]


async def test_session_list_by_project(ctx) -> None:
    project = await dispatch("project.create", {"name": "AgentMash"}, ctx)
    agent = await dispatch("agent.create", {"name": "Atlas", "project_id": project["id"]}, ctx)
    session = await _make_session(ctx, agent_id=agent["id"], project_id=project["id"])

    result = await dispatch("session.list", {"project_id": project["id"]}, ctx)
    assert [s["id"] for s in result] == [session.id]


async def test_session_list_with_no_filter_returns_active_sessions(ctx) -> None:
    project = await dispatch("project.create", {"name": "AgentMash"}, ctx)
    agent = await dispatch("agent.create", {"name": "Atlas", "project_id": project["id"]}, ctx)
    session = await _make_session(ctx, agent_id=agent["id"], project_id=project["id"])

    result = await dispatch("session.list", {}, ctx)
    assert session.id in [s["id"] for s in result]
