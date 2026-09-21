"""Real end-to-end smoke test for Milestone 4 against a private disposable GitHub repository.

Validates the complete delivery lifecycle:
1. Project & Mission setup with real worktrees
2. Remote repository binding to disposable GitHub repo
3. Candidate & Snapshot atomic freeze
4. Preflight execution (real git evidence & secret scans)
5. Human approval for push
6. Git push of delivery branch to remote
7. Human approval for PR creation
8. PR creation on GitHub via GitHubAdapter
9. CI status monitoring and green status verification
10. Human approval for merge
11. Merge execution via squash method
12. Post-merge verification in target branch
13. Rollback proposal & approval
14. Rollback execution (revert branch push + revert PR)
15. Verification that AgentMash main SHA is untouched
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from core.agents.models import Agent
from core.bridge.context import build_context
from core.database.migrations.runner import run_migrations
from core.delivery.git_remote import GitRemote
from core.delivery.github_adapter import GitHubAdapter
from core.delivery.models import RemoteRepositoryBindingInput
from core.delivery.service import DeliveryService
from core.integration.models import QualityGateDefinition, QualityGateProfile
from core.missions.models import Choice, Mission, MissionPlan, PlannedTask, ReviewOutput, WorkerOutput
from core.parallel.models import HumanApproval, IntegrationAttempt, QualityGateRun
from core.projects.models import ProjectCreate
from core.security.secret_store import InMemorySecretStore
from core.tasks.models import TaskCreate, TaskStatus
from core.utils.time import utc_now


DISPOSABLE_REPO = "C0mrad078/agentmash-m4-smoke-tmp"
DISPOSABLE_URL = f"https://github.com/{DISPOSABLE_REPO}.git"
AGENTMASH_MAIN_SHA = "8db13456c61fdbe91dfdbe55819b8fec3e6989ab"


def run_cmd(args: list[str], cwd: Path | None = None) -> str:
    res = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


async def main():
    print(f"=== Starting Milestone 4 Real Smoke Test on {DISPOSABLE_REPO} ===")

    # 0. Check AgentMash main SHA first
    current_main_sha = run_cmd(["git", "rev-parse", "main"], cwd=Path.cwd())
    print(f"AgentMash main SHA before smoke: {current_main_sha}")
    assert current_main_sha == AGENTMASH_MAIN_SHA, f"Expected {AGENTMASH_MAIN_SHA}, got {current_main_sha}"

    # Workspace directory
    ws_dir = Path("/tmp/agentmash-m4-smoke-ws")
    if ws_dir.exists():
        shutil.rmtree(ws_dir)
    ws_dir.mkdir(parents=True)

    project_root = ws_dir / "project"
    print(f"Cloning {DISPOSABLE_URL} to {project_root}...")
    run_cmd(["git", "clone", DISPOSABLE_URL, str(project_root)])
    run_cmd(["git", "config", "user.name", "AgentMash Smoke"], cwd=project_root)
    run_cmd(["git", "config", "user.email", "smoke@agentmash.local"], cwd=project_root)

    # Initial baseline commit on main
    ts = int(utc_now().timestamp())
    (project_root / ".gitignore").write_text("__pycache__/\n*.py[cod]\n")
    app_file = project_root / "service_app.py"
    app_file.write_text(f"# Baseline {ts}\ndef app_version():\n    return '1.0.0'\n")
    run_cmd(["git", "add", "."], cwd=project_root)
    run_cmd(["git", "commit", "-m", f"chore: setup smoke test baseline {ts}"], cwd=project_root)
    run_cmd(["git", "push", "origin", "main"], cwd=project_root)
    base_sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=project_root)
    print(f"Remote base SHA: {base_sha}")

    # Set up integration worktree
    digest = hashlib.sha256(str(project_root.resolve()).encode()).hexdigest()[:16]
    worktree_parent = project_root.resolve().parent / ".agentmash-worktrees" / digest
    integration_dir = worktree_parent / "integration"
    worktree_parent.mkdir(parents=True, exist_ok=True)

    integration_branch = f"agentmash/integration-smoke-{ts}"
    run_cmd(["git", "worktree", "add", "-b", integration_branch, str(integration_dir), base_sha], cwd=project_root)
    print(f"Integration worktree created at {integration_dir}")

    # Add delivered feature to integration branch
    feature_file = integration_dir / "delivery_feature.py"
    feature_file.write_text(f"# Feature {ts}\ndef delivered_capability():\n    return 'controlled delivery v3'\n")
    run_cmd(["git", "add", "."], cwd=integration_dir)
    run_cmd(["git", "commit", "-m", "feat: add controlled delivery capability"], cwd=integration_dir)
    integration_head = run_cmd(["git", "rev-parse", "HEAD"], cwd=integration_dir)
    print(f"Integration HEAD SHA: {integration_head}")

    # Initialize BridgeContext and database
    db_path = ws_dir / "smoke.db"
    ctx = await build_context(db_path, secret_store=InMemorySecretStore())
    run_migrations(ctx.db)

    # Create project & mission
    proj = await ctx.project_service.create_project(ProjectCreate(name="Smoke Project"))
    mission = Mission(
        id=f"smoke-mission-{ts}",
        project_id=proj.id,
        request="Deliver controlled capability",
        status="completed",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    await ctx.mission_service.repo.put(mission, command_id="cmd-1")

    # Link workspace
    await ctx.db.execute(
        "UPDATE projects SET workspace_path = ? WHERE id = ?",
        (str(project_root), proj.id),
    )

    # Quality Gate Profile
    await ctx.integration_repo.save_profile(
        QualityGateProfile(
            id=f"profile-{proj.id}",
            project_id=proj.id,
            name="Smoke Gate Profile",
            is_default=True,
            gates=[
                QualityGateDefinition(
                    id="py-syntax",
                    name="Syntax Check",
                    argv=[sys.executable, "-m", "py_compile", "delivery_feature.py"],
                )
            ],
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )

    # Task, Integration attempt, Quality Gate Run, Approval
    task = await ctx.mission_service.repo.tasks.create(
        TaskCreate(project_id=proj.id, title="Implement capability")
    )
    await ctx.mission_service.repo.link("task", mission.id, task.id)
    await ctx.mission_service.repo.tasks.update_status(task.id, TaskStatus.COMPLETED)

    now = utc_now()
    await ctx.parallel_repo.add_integration(
        IntegrationAttempt(
            id="attempt-smoke",
            mission_id=mission.id,
            task_id=task.id,
            integration_branch=integration_branch,
            source_branch="source-branch",
            base_sha=base_sha,
            result="integrated",
            commit_sha=integration_head,
            message="Cleanly integrated",
            created_at=now,
        )
    )
    await ctx.parallel_repo.add_gate(
        QualityGateRun(
            id="gate-smoke",
            mission_id=mission.id,
            name="Syntax Check",
            command=[sys.executable, "-m", "py_compile", "delivery_feature.py"],
            exit_code=0,
            duration_ms=10,
            summary="passed",
            passed=True,
            created_at=now,
        )
    )
    await ctx.parallel_repo.add_approval(
        HumanApproval(
            id="approval-smoke",
            mission_id=mission.id,
            decision="approved",
            rationale="Approved by human reviewer",
            created_at=now,
        )
    )

    # Create DeliveryService with real GitRemote and real GitHubAdapter
    git_remote = GitRemote()
    github_adapter = GitHubAdapter()
    delivery = DeliveryService(ctx, git=git_remote, github=github_adapter)
    ctx.delivery_service = delivery

    # Step 1: Save remote binding
    print("\n--- Step 1: Remote Repository Binding ---")
    binding = await delivery.binding_save(
        RemoteRepositoryBindingInput(
            project_id=proj.id,
            provider="github",
            remote_name="origin",
            remote_url=DISPOSABLE_URL,
            target_branch="main",
            default_merge_method="squash",
        )
    )
    print(f"Binding saved: {binding.id} ({binding.remote_url_sanitized}, target={binding.target_branch})")

    # Step 2: Create candidate & freeze snapshot
    print("\n--- Step 2: Delivery Candidate Freeze ---")
    detail = await delivery.create(mission.id, proj.id)
    candidate_id = detail["candidate"]["id"]
    snapshot = detail["snapshot"]
    print(f"Candidate frozen: {candidate_id} (version {detail['candidate']['version']}, status={detail['candidate']['status']})")
    print(f"Snapshot diff hash: {snapshot['diff_hash']}, insertions: {snapshot['diff_stat']['insertions']}")
    assert detail["candidate"]["status"] == "draft"
    assert snapshot["integration_sha"] == integration_head

    # Step 3: Run preflight
    print("\n--- Step 3: Preflight Execution ---")
    preflight_report = await delivery.run_preflight(candidate_id)
    print(f"Preflight status: {preflight_report.status}, blocking_reasons={preflight_report.blocking_reasons}")
    if preflight_report.status != "passed":
        print(f"PREFLIGHT DUMP: {json.dumps(preflight_report.model_dump(mode='json'), indent=2)}")
    assert preflight_report.status == "passed", f"Preflight failed: {preflight_report.blocking_reasons}"
    detail = await delivery.detail(candidate_id)
    assert detail["candidate"]["status"] == "awaiting_remote_approval"

    # Step 4: Human Approval for Push
    print("\n--- Step 4: Human Approval for Push ---")
    await delivery.approve(candidate_id, "push", "approved", "Lead Integrator", "Smoke approval for push")
    detail = await delivery.detail(candidate_id)
    assert detail["candidate"]["status"] == "awaiting_remote_approval"

    # Step 5: Remote Push
    print("\n--- Step 5: Remote Push to GitHub ---")
    push_res = await delivery.execute(candidate_id, "push", "idemp-push-1")
    print(f"Remote push result: {push_res}")
    detail = await delivery.detail(candidate_id)
    assert detail["candidate"]["status"] == "pr_open"

    # Verify remote branch exists on GitHub
    remote_head = await git_remote.remote_sha(project_root, binding, f"agentmash/delivery-{mission.id}")
    print(f"Remote branch SHA confirmed on GitHub: {remote_head}")
    assert remote_head == integration_head

    # Step 6: Human Approval for PR Creation
    print("\n--- Step 6: Human Approval for PR Creation ---")
    await delivery.approve(candidate_id, "pr_create", "approved", "Lead Integrator", "Smoke approval for PR")

    # Step 7: PR Creation on GitHub
    print("\n--- Step 7: Create PR on GitHub ---")
    pr_res = await delivery.execute(candidate_id, "pr_create", "idemp-pr-1")
    pr_data = pr_res.result or {}
    pr_number = pr_data.get("pr_number")
    pr_url = pr_data.get("pr_url")
    print(f"Pull Request created: #{pr_number} -> {pr_url}")
    assert pr_number and pr_number > 0

    # Step 8: Post CI Status Check on GitHub
    print("\n--- Step 8: Post passing CI check via GitHub API ---")
    run_cmd([
        "gh", "api", f"repos/{DISPOSABLE_REPO}/statuses/{integration_head}",
        "-f", "state=success",
        "-f", "context=ci/test",
        "-f", "description=Milestone 4 smoke CI passed",
    ], cwd=project_root)

    # Step 9: Monitor CI status
    print("\n--- Step 9: Monitor CI status ---")
    runs = await delivery.ci_status(candidate_id, force=True)
    print(f"CI runs observed: {len(runs)}")
    for r in runs:
        print(f"  Check '{r.name}': status={r.status}, conclusion={r.conclusion}")
    detail = await delivery.detail(candidate_id)
    print(f"Candidate status after CI: {detail['candidate']['status']}")
    assert detail["candidate"]["status"] == "awaiting_merge_approval"

    # Step 10: Human Approval for Merge
    print("\n--- Step 10: Human Approval for Merge ---")
    await delivery.approve(candidate_id, "merge", "approved", "Lead Integrator", "Smoke approval for merge")

    # Step 11: Execute Merge (squash)
    print("\n--- Step 11: Execute Merge (squash) ---")
    merge_res = await delivery.execute(candidate_id, "merge", "idemp-merge-1", merge_method="squash")
    print(f"Merge result: {merge_res}")
    detail = await delivery.detail(candidate_id)
    print(f"Candidate status after merge & post-merge verification: {detail['candidate']['status']}")
    assert detail["candidate"]["status"] == "merged"
    assert detail["post_merge"]["status"] == "passed"
    print(f"Merge SHA verified in target: {detail['post_merge']['target_sha_observed']}")

    # Step 12: Propose Rollback
    print("\n--- Step 12: Propose Rollback ---")
    rollback_plan = await delivery.propose_rollback(candidate_id, "Smoke test revert verification")
    print(f"Rollback plan: {rollback_plan.id}, revert_branch={rollback_plan.revert_branch}")
    detail = await delivery.detail(candidate_id)
    assert detail["candidate"]["status"] == "rollback_proposed"

    # Step 13: Human Approval for Rollback
    print("\n--- Step 13: Human Approval for Rollback ---")
    await delivery.approve(candidate_id, "rollback", "approved", "Lead Integrator", "Approve revert PR")

    # Step 14: Execute Rollback (creates revert PR)
    print("\n--- Step 14: Execute Rollback (Revert PR) ---")
    rollback_res = await delivery.execute(candidate_id, "rollback", "idemp-rollback-1")
    print(f"Rollback execution result: {rollback_res}")
    rollback_data = rollback_res.result or {}
    revert_pr_url = rollback_data.get("revert_pr_url")
    print(f"Revert PR opened: {revert_pr_url}")
    assert revert_pr_url is not None

    # Step 15: Check Telemetry
    print("\n--- Step 15: Phase Telemetry & Internal Steps ---")
    telemetry = await delivery.telemetry(candidate_id=candidate_id)
    print(f"Recorded telemetry entries: {len(telemetry)}")
    for t in telemetry:
        print(f"  Phase '{t.phase}': outcome={t.outcome}, duration_ms={t.duration_ms}")
    assert len(telemetry) > 0

    # Step 16: Check AgentMash main SHA
    print("\n--- Step 16: Verify AgentMash main integrity ---")
    final_main_sha = run_cmd(["git", "rev-parse", "main"], cwd=Path.cwd())
    print(f"AgentMash main SHA after smoke: {final_main_sha}")
    assert final_main_sha == AGENTMASH_MAIN_SHA, f"Main SHA altered! {final_main_sha}"

    # Cleanup local temporary files
    await ctx.close()
    shutil.rmtree(ws_dir)
    print("Local workspace cleaned up.")

    print("\n========================================================")
    print("ALL 16 SMOKE TEST STEPS PASSED AGAINST GITHUB!")
    print(f"Target PR: {pr_url} (MERGED)")
    print(f"Revert PR: {revert_pr_url} (OPEN)")
    print(f"AgentMash main SHA intact: {final_main_sha}")
    print("========================================================")


if __name__ == "__main__":
    asyncio.run(main())
