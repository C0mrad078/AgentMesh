from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.bridge.server import request_timeout_seconds
from core.projects.models import ProjectCreate
from core.security.secret_store import InMemorySecretStore
from core.utils.errors import ValidationError


@pytest.fixture
async def ctx(tmp_path: Path):
    context = await build_context(tmp_path / "reliability_test.db", secret_store=InMemorySecretStore())
    try:
        yield context
    finally:
        await context.close()


async def test_diagnostics_collect_via_bridge(ctx) -> None:
    report = await dispatch(
        "system.diagnostics.collect",
        {"logs": ['{"timestamp": "2026-09-21T12:00:00Z", "level": "INFO", "module": "test", "event": "startup"}']},
        ctx,
    )
    assert "metadata" in report
    assert "database_health" in report
    assert report["database_health"]["pragmas"]["integrity_check"] == "ok"
    assert report["metadata"]["app_version"] == "0.1.0-rc.1"
    assert isinstance(report["logs_sanitized"], list)
    assert len(report["logs_sanitized"]) >= 1


async def test_diagnostics_export_via_bridge(ctx, tmp_path: Path) -> None:
    target_zip = tmp_path / "export_test.zip"
    res = await dispatch("system.diagnostics.export", {"output_path": str(target_zip)}, ctx)
    assert Path(res["path"]).is_file()  # noqa: ASYNC240 - test-only convenience check
    assert res["size_bytes"] > 0


    with zipfile.ZipFile(target_zip, "r") as archive:
        names = archive.namelist()
        assert "metadata.json" in names
        assert "providers.json" in names
        assert "database_health.json" in names
        assert "logs_sanitized.log" in names

    rows = await ctx.db.fetch_all("SELECT * FROM audit_logs WHERE action=?", ("system.diagnostics.export",))
    assert len(rows) == 1



async def test_backup_create_list_restore_flow_via_bridge(ctx) -> None:
    # 1. Create a project
    await ctx.project_service.create_project(ProjectCreate(name="Initial Project"))

    # 2. Create backup
    create_res = await dispatch("system.backup.create", {"protected": True}, ctx)
    backup_id = create_res["manifest"]["backup_id"]
    assert backup_id.startswith("bkp-")
    assert create_res["manifest"]["protected"] is True
    assert len(create_res["manifest"]["sha256"]) == 64

    # 3. List backups
    backups = await dispatch("system.backup.list", {}, ctx)
    assert any(b["manifest"]["backup_id"] == backup_id for b in backups)

    # 4. Modify project database
    await ctx.project_service.create_project(ProjectCreate(name="Ephemeral Project"))
    projects_after = await ctx.project_service.list_projects()
    assert {p.name for p in projects_after} == {"Initial Project", "Ephemeral Project"}

    # 5. Restore backup
    restore_res = await dispatch("system.backup.restore", {"backup_id": backup_id}, ctx)
    assert restore_res["backup_id"] == backup_id
    assert Path(restore_res["safety_snapshot_path"]).is_file()  # noqa: ASYNC240 - test-only convenience check

    # 6. Verify restored data

    projects_restored = await ctx.project_service.list_projects()
    assert {p.name for p in projects_restored} == {"Initial Project"}


async def test_backup_restore_requires_valid_id(ctx) -> None:
    with pytest.raises(ValidationError):
        await dispatch("system.backup.restore", {"backup_id": "invalid-id"}, ctx)


async def test_onboarding_status_via_bridge(ctx) -> None:
    status = await dispatch("system.onboarding.status", {}, ctx)
    assert "completed" in status
    assert "ready_for_completion" in status
    assert "checks" in status
    assert any(c["name"] == "database" and c["status"] == "pass" for c in status["checks"])


def test_reliability_timeout_pairings() -> None:
    assert request_timeout_seconds("system.diagnostics.collect") == 30.0
    assert request_timeout_seconds("system.backup.list") == 30.0
    assert request_timeout_seconds("system.onboarding.status") == 30.0
    assert request_timeout_seconds("system.diagnostics.export") == 60.0
    assert request_timeout_seconds("system.backup.create") == 60.0
    assert request_timeout_seconds("system.backup.restore") == 120.0
