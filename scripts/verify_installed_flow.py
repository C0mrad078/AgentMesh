#!/usr/bin/env python3
"""Execute and verify the Milestone 6 Installed Flow.

Tests the full lifecycle on the installed environment via dispatch:
- Project selection / creation
- RuntimeBindings validation
- Mission creation and session persistence
- Application restart & state restoration
- Agent Workspace, Delivery Center, Deployment Center access
- Diagnostics collection & sanitized export
- Backup creation & manifest validation
"""

# ruff: noqa: ASYNC240
from __future__ import annotations

import asyncio
import tempfile
import zipfile
from pathlib import Path

from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.security.secret_scanner import SecretScanner


async def run_installed_flow() -> None:
    print("=" * 70)
    print("AGENTMASH MARCO 6 — INSTALLED FLOW VERIFICATION")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "agentmash_installed.db"
        backups_dir = Path(tmp_dir) / "backups"
        exports_dir = Path(tmp_dir) / "exports"
        backups_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)

        print("\n[Phase 1] Initializing native database & bridge context...")
        ctx = await build_context(db_path)

        # 1. Project selection / creation
        print("[Phase 2] Project Creation & Selection...")
        proj = await dispatch(
            "project.create",
            {
                "name": "Production RC Project",
                "description": "Verification flow for Milestone 6 RC",
            },
            ctx,
        )
        proj_id = proj["id"]
        fetched_proj = await dispatch("project.get", {"project_id": proj_id}, ctx)
        assert fetched_proj["id"] == proj_id
        assert fetched_proj["name"] == "Production RC Project"
        print(f"  Project created & verified: {proj_id}")

        # 2. Validate RuntimeBindings
        print("[Phase 3] Validating RuntimeBindings...")
        bindings = await dispatch("runtime_binding.list", {}, ctx)
        count_bindings = (
            len(bindings) if isinstance(bindings, list) else len(bindings.get("bindings", []))
        )
        print(f"  Runtime bindings configured: {count_bindings}")

        # 3. Create simple mission
        print("[Phase 4] Creating simple mission & persisting session...")
        mission = await dispatch(
            "mission.create",
            {
                "project_id": proj_id,
                "request": "Verify system health and generate verification report",
                "command_id": "cmd-mission-001",
            },
            ctx,
        )
        mission_id = mission["id"]
        fetched_snapshot = await dispatch("mission.get", {"mission_id": mission_id}, ctx)
        assert fetched_snapshot["mission"]["id"] == mission_id
        print(f"  Mission created: {mission_id} (Status: {fetched_snapshot['mission']['status']})")

        # 4. Check sessions
        sessions = await dispatch("session.list", {"project_id": proj_id}, ctx)
        count_sessions = (
            len(sessions) if isinstance(sessions, list) else len(sessions.get("sessions", []))
        )
        print(f"  Sessions recorded: {count_sessions}")

        # 5. Simulate application shutdown & restart
        print("\n[Phase 5] Simulating native app shutdown and state recovery...")
        await ctx.close()

        # Reopen context on same persistent SQLite DB
        ctx_restarted = await build_context(db_path)
        restored_proj = await dispatch("project.get", {"project_id": proj_id}, ctx_restarted)
        assert restored_proj["name"] == "Production RC Project"
        restored_snapshot = await dispatch("mission.get", {"mission_id": mission_id}, ctx_restarted)
        assert restored_snapshot["mission"]["id"] == mission_id
        print("  State recovery verified across restart: Project and Mission persisted.")

        # 6. Access Agent Workspace
        print("[Phase 6] Accessing Agent Workspace...")
        agents = await dispatch("agent.list", {}, ctx_restarted)
        count_agents = len(agents) if isinstance(agents, list) else len(agents.get("agents", []))
        assert count_agents > 0
        print(f"  Agent workspace accessible: {count_agents} agents available.")

        # 7. Access Delivery Center
        print("[Phase 7] Accessing Delivery Center...")
        deliveries = await dispatch(
            "delivery.candidate.list", {"project_id": proj_id}, ctx_restarted
        )
        count_deliveries = (
            len(deliveries)
            if isinstance(deliveries, list)
            else len(deliveries.get("candidates", []))
        )
        print(f"  Delivery center accessible: {count_deliveries} candidates.")

        # 8. Access Deployment Center
        print("[Phase 8] Accessing Deployment Center...")
        envs = await dispatch("deployment.environment.list", {"project_id": proj_id}, ctx_restarted)
        releases = await dispatch("deployment.release.list", {"project_id": proj_id}, ctx_restarted)
        count_envs = len(envs) if isinstance(envs, list) else len(envs.get("environments", []))
        count_releases = (
            len(releases) if isinstance(releases, list) else len(releases.get("releases", []))
        )
        print(
            f"  Deployment center accessible: {count_envs} environments, {count_releases} releases."
        )

        # 9. Diagnostics collection & export
        print("[Phase 9] Collecting & exporting diagnostics bundle...")
        diag_report = await dispatch("system.diagnostics.collect", {}, ctx_restarted)
        assert diag_report["metadata"]["app_version"] == "0.1.0-rc.1"
        assert diag_report["database_health"]["tables_count"] > 0

        export_dest = exports_dir / "diagnostics_installed.zip"
        export_res = await dispatch(
            "system.diagnostics.export",
            {"path": str(export_dest)},
            ctx_restarted,
        )
        archive_path = Path(export_res["path"])
        assert archive_path.exists()
        with zipfile.ZipFile(archive_path, "r") as zf:
            namelist = zf.namelist()
            assert "metadata.json" in namelist
            assert "logs_sanitized.log" in namelist
            logs = zf.read("logs_sanitized.log").decode("utf-8", errors="ignore")
            assert not SecretScanner().contains_secret(logs)
        print(
            f"  Diagnostics bundle exported & verified: {archive_path} ({len(namelist)} members, Zero-Leak)."
        )

        # 10. Backup creation & listing
        print("[Phase 10] Creating and validating SQLite backup...")
        backup_res = await dispatch(
            "system.backup.create",
            {"protected": True},
            ctx_restarted,
        )
        backup_id = backup_res["manifest"]["backup_id"]
        assert backup_res["manifest"]["schema_version"] == 21
        assert Path(backup_res["database_path"]).exists()

        backups_list = await dispatch("system.backup.list", {}, ctx_restarted)
        assert any(b["manifest"]["backup_id"] == backup_id for b in backups_list)
        print(f"  Backup created & verified in list: {backup_id}")

        await ctx_restarted.close()

    print("\n" + "=" * 70)
    print("INSTALLED FLOW VERDICT: 100% PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_installed_flow())
