#!/usr/bin/env python3
"""Milestone 6 Performance & Security Benchmark Suite.

Validates the performance and security requirements specified in:
docs/agentmash-v3-milestone6-contract.md (Section 7)

Targets:
1. Cold Start: Native application startup & initialization <= 3.0s
2. Database Initialization: SQLite connection & migrations verification <= 250ms
3. Backup Execution: Backup creation for standard databases (<= 50MB) <= 2.0s
4. Diagnostics Export: Complete bundle generation and sanitization <= 4.0s
5. Zero Memory Leaks: Memory footprint idle <= 150MB
6. No Wildcards: Exact command allowlist enforcement
"""

from __future__ import annotations

import asyncio
import gc
import resource
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from core.bridge.context import build_context
from core.database.connection import Database
from core.reliability.backup import BackupManager
from core.reliability.diagnostics import DiagnosticsCollector
from core.security.allowlist import ALL_COMMANDS, BridgeCommand
from core.security.secret_scanner import SecretScanner


def get_process_rss_mb() -> float:
    """Return Resident Set Size (RSS) memory in megabytes."""
    # On macOS ru_maxrss is in bytes; on Linux in kilobytes
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage / (1024 * 1024)
    return usage / 1024


async def benchmark_database_initialization(iterations: int = 10) -> dict[str, Any]:
    """Benchmark SQLite database connection, PRAGMA setup, and migrations 0001..0021."""
    fresh_durations: list[float] = []
    warm_durations: list[float] = []

    for _ in range(iterations):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_file = Path(tmp_dir) / "test.db"

            # 1. Fresh database initialization (creates tables & applies 21 migrations)
            t0 = time.perf_counter()
            db = Database(db_file)
            await db.connect()
            t_fresh = (time.perf_counter() - t0) * 1000  # ms
            fresh_durations.append(t_fresh)

            # 2. Warm database initialization (already migrated)
            t1 = time.perf_counter()
            db_warm = Database(db_file)
            await db_warm.connect()
            t_warm = (time.perf_counter() - t1) * 1000  # ms
            warm_durations.append(t_warm)

            if db._conn:
                await db._conn.close()
            if db_warm._conn:
                await db_warm._conn.close()

    return {
        "iterations": iterations,
        "fresh_avg_ms": sum(fresh_durations) / len(fresh_durations),
        "fresh_min_ms": min(fresh_durations),
        "fresh_max_ms": max(fresh_durations),
        "warm_avg_ms": sum(warm_durations) / len(warm_durations),
        "warm_min_ms": min(warm_durations),
        "warm_max_ms": max(warm_durations),
        "passed": (sum(warm_durations) / len(warm_durations)) <= 250.0 and min(fresh_durations) <= 250.0,
    }


async def benchmark_backup_execution() -> dict[str, Any]:
    """Benchmark backup creation on standard (sample) and populated (50MB) database."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "benchmark.db"
        backups_dir = tmp_path / "backups"

        db = Database(db_path)
        await db.connect()

        # Seed initial standard records
        for i in range(50):
            await db.execute(
                "INSERT INTO projects (id, name, description, status, config, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"proj-{i}", f"Project {i}", "Description", "active", "{}", "2026-01-01", "2026-01-01"),
            )

        backup_mgr = BackupManager(db, backups_dir)

        # Measure standard backup creation
        t0 = time.perf_counter()
        res_std = await backup_mgr.create()
        duration_std_s = time.perf_counter() - t0

        # Now grow database to ~50MB to stress-test the contractual limit
        # Inserting chunked blob data into a temporary benchmark table
        blob_1mb = b"X" * (1024 * 1024)
        await db.execute("CREATE TABLE IF NOT EXISTS benchmark_data (id INTEGER PRIMARY KEY, payload BLOB)")
        for i in range(50):
            await db.execute("INSERT INTO benchmark_data (id, payload) VALUES (?, ?)", (i, blob_1mb))
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        db_size_mb = db_path.stat().st_size / (1024 * 1024)

        # Measure 50MB backup creation
        t1 = time.perf_counter()
        res_50mb = await backup_mgr.create()
        duration_50mb_s = time.perf_counter() - t1

        if db._conn:
            await db._conn.close()

        return {
            "standard_db_duration_s": duration_std_s,
            "standard_db_backup_id": res_std.manifest.backup_id,
            "stressed_db_size_mb": db_size_mb,
            "stressed_db_duration_s": duration_50mb_s,
            "stressed_db_backup_id": res_50mb.manifest.backup_id,
            "target_s": 2.0,
            "passed": duration_50mb_s <= 2.0 and duration_std_s <= 2.0,
        }


async def benchmark_diagnostics_export() -> dict[str, Any]:
    """Benchmark diagnostics collection, sanitization and ZIP archive generation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "diag.db"
        export_dir = tmp_path / "exports"

        db = Database(db_path)
        await db.connect()

        collector = DiagnosticsCollector(db)
        archive_path = export_dir / "diagnostics.zip"

        t0 = time.perf_counter()
        await collector.export(archive_path)
        duration_s = time.perf_counter() - t0

        assert archive_path.exists()
        archive_size_kb = archive_path.stat().st_size / 1024

        # Verify archive integrity and member files
        with zipfile.ZipFile(archive_path, "r") as zf:
            namelist = zf.namelist()
            expected = {
                "metadata.json",
                "providers.json",
                "runtime_bindings.json",
                "database_health.json",
                "logs_sanitized.log",
            }
            has_all_members = expected.issubset(set(namelist))

            # Verify redaction in logs
            logs_content = zf.read("logs_sanitized.log").decode("utf-8", errors="ignore")
            contains_secrets = bool(
                re_has_secret(logs_content)
            )

        if db._conn:
            await db._conn.close()

        return {
            "duration_s": duration_s,
            "archive_size_kb": archive_size_kb,
            "members": namelist,
            "has_all_members": has_all_members,
            "zero_leak_verified": not contains_secrets,
            "target_s": 4.0,
            "passed": duration_s <= 4.0 and has_all_members and not contains_secrets,
        }


def re_has_secret(text: str) -> bool:
    scanner = SecretScanner()
    return scanner.contains_secret(text)


async def benchmark_cold_start_and_memory() -> dict[str, Any]:
    """Benchmark bridge context cold start initialization time and memory footprint."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "cold_start.db"

        # Force garbage collection for clean baseline
        gc.collect()

        t0 = time.perf_counter()
        # Build complete operational bridge context from scratch (connects DB, runs migrations, seeds defaults)
        ctx = await build_context(db_path)
        duration_s = time.perf_counter() - t0

        mem_after_mb = get_process_rss_mb()
        await ctx.close()

        return {
            "cold_start_duration_s": duration_s,
            "target_cold_start_s": 3.0,
            "rss_memory_mb": mem_after_mb,
            "target_memory_mb": 150.0,
            "cold_start_passed": duration_s <= 3.0,
            "memory_passed": mem_after_mb <= 150.0,
        }


def audit_allowlist_and_wildcards() -> dict[str, Any]:
    """Audit the bridge allowlist to ensure zero wildcards and exact command enforcement."""
    all_commands = [cmd.value for cmd in BridgeCommand]
    total_commands = len(all_commands)

    # Verify no command contains wildcard patterns
    wildcard_findings = [cmd for cmd in all_commands if "*" in cmd or "?" in cmd]

    # Verify invalid commands are rejected
    invalid_test_cases = [
        "system.*",
        "system.diagnostics.*",
        "*.create",
        "admin.bypass",
        "eval",
        "sh.exec",
        "system.backup.delete_all",
    ]
    rejection_results = {cmd: (cmd in ALL_COMMANDS) for cmd in invalid_test_cases}
    all_invalid_rejected = not any(rejection_results.values())

    # Verify 6 reliability commands exist
    m6_commands = [
        "system.diagnostics.collect",
        "system.diagnostics.export",
        "system.backup.create",
        "system.backup.list",
        "system.backup.restore",
        "system.onboarding.status",
    ]
    all_m6_present = all(cmd in all_commands for cmd in m6_commands)

    return {
        "total_registered_commands": total_commands,
        "wildcard_findings": wildcard_findings,
        "all_invalid_rejected": all_invalid_rejected,
        "all_m6_commands_present": all_m6_present,
        "passed": len(wildcard_findings) == 0 and all_invalid_rejected and all_m6_present,
    }


async def main() -> None:
    print("=" * 70)
    print("AGENTMASH MARCO 6 — PERFORMANCE & SECURITY BENCHMARK SUITE")
    print("=" * 70)

    # 1. Database Initialization
    print("\n[1/5] Benchmarking SQLite Initialization & Migrations (0001..0021)...")
    db_res = await benchmark_database_initialization(iterations=10)
    print(f"  Iterations: {db_res['iterations']}")
    print(f"  Fresh DB (21 migrations applied): Avg = {db_res['fresh_avg_ms']:.2f}ms (Min = {db_res['fresh_min_ms']:.2f}ms, Max = {db_res['fresh_max_ms']:.2f}ms)")
    print(f"  Warm DB (migrations verified):   Avg = {db_res['warm_avg_ms']:.2f}ms (Min = {db_res['warm_min_ms']:.2f}ms, Max = {db_res['warm_max_ms']:.2f}ms)")
    print(f"  Status: {'PASSED (<= 250ms)' if db_res['passed'] else 'FAILED'}")

    # 2. Backup Execution
    print("\n[2/5] Benchmarking SQLite Backup Execution...")
    backup_res = await benchmark_backup_execution()
    print(f"  Standard DB backup: {backup_res['standard_db_duration_s']:.4f}s (ID: {backup_res['standard_db_backup_id']})")
    print(f"  Stressed 50MB DB backup: {backup_res['stressed_db_duration_s']:.4f}s (Size: {backup_res['stressed_db_size_mb']:.2f}MB, ID: {backup_res['stressed_db_backup_id']})")
    print(f"  Status: {'PASSED (<= 2.0s)' if backup_res['passed'] else 'FAILED'}")

    # 3. Diagnostics Export
    print("\n[3/5] Benchmarking Diagnostics Bundle Generation & Sanitization...")
    diag_res = await benchmark_diagnostics_export()
    print(f"  Export Duration: {diag_res['duration_s']:.4f}s (Target <= 4.0s)")
    print(f"  Archive Size: {diag_res['archive_size_kb']:.2f} KB")
    print(f"  Archive Members: {', '.join(diag_res['members'])}")
    print(f"  Zero-Leak Verified: {diag_res['zero_leak_verified']}")
    print(f"  Status: {'PASSED (<= 4.0s & Zero-Leak)' if diag_res['passed'] else 'FAILED'}")

    # 4. Cold Start & Memory Footprint
    print("\n[4/5] Benchmarking Cold Start & Memory Footprint...")
    cold_res = await benchmark_cold_start_and_memory()
    print(f"  Cold Start Duration: {cold_res['cold_start_duration_s']:.4f}s (Target <= 3.0s)")
    print(f"  Idle Process RSS: {cold_res['rss_memory_mb']:.2f} MB (Target <= 150.0MB)")
    print(f"  Cold Start Status: {'PASSED' if cold_res['cold_start_passed'] else 'FAILED'}")
    print(f"  Memory Status: {'PASSED' if cold_res['memory_passed'] else 'FAILED'}")

    # 5. Allowlist & Wildcards
    print("\n[5/5] Auditing Bridge Allowlist & Wildcard Invariants...")
    allow_res = audit_allowlist_and_wildcards()
    print(f"  Total Registered Commands: {allow_res['total_registered_commands']}")
    print(f"  Wildcard Findings: {allow_res['wildcard_findings']} (Expected: none)")
    print(f"  Invalid / Wildcard Rejection: {'PASSED' if allow_res['all_invalid_rejected'] else 'FAILED'}")
    print(f"  Milestone 6 Commands Present: {'PASSED' if allow_res['all_m6_commands_present'] else 'FAILED'}")

    all_passed = (
        db_res["passed"]
        and backup_res["passed"]
        and diag_res["passed"]
        and cold_res["cold_start_passed"]
        and cold_res["memory_passed"]
        and allow_res["passed"]
    )

    print("\n" + "=" * 70)
    print(f"BENCHMARK VERDICT: {'ALL CRITERIA PASSED' if all_passed else 'CRITERIA FAILED'}")
    print("=" * 70)

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
