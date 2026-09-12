from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.database.connection import Database
from core.projects.models import ProjectCreate
from core.security.secret_store import InMemorySecretStore


@pytest.fixture
async def ctx(tmp_path: Path):
    context = await build_context(tmp_path / "db_bridge.db", secret_store=InMemorySecretStore())
    try:
        yield context
    finally:
        await context.close()

async def test_backup_create_list_restore_via_bridge(ctx) -> None:
    await ctx.project_service.create_project(ProjectCreate(name="Before"))
    backup = await dispatch("database.backup.create", {}, ctx)
    assert Path(backup["path"]).exists()  # noqa: ASYNC240 - test-only convenience check

    backups = await dispatch("database.backup.list", {}, ctx)
    assert len(backups) == 1

    await ctx.project_service.create_project(ProjectCreate(name="After"))
    result = await dispatch("database.backup.restore", {"path": backup["path"], "confirm": True}, ctx)
    assert result["restart_recommended"] is True

    projects = await ctx.project_service.list_projects()
    names = {p.name for p in projects}
    assert names == {"Before"}

async def test_integrity_check_via_bridge(ctx) -> None:
    result = await dispatch("database.integrity_check", {}, ctx)
    assert result["ok"] is True

async def test_build_context_runs_a_quick_integrity_check_at_startup(tmp_path: Path) -> None:
    with patch.object(Database, "quick_integrity_check", new=AsyncMock(return_value=True)) as spy:
        context = await build_context(tmp_path / "startup_check.db", secret_store=InMemorySecretStore())
        try:
            spy.assert_awaited_once()
        finally:
            await context.close()
