from __future__ import annotations

from pathlib import Path

import pytest
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.bridge.server import _LONG_DEPLOYMENT_COMMANDS, request_timeout_seconds
from core.database.repositories.delivery_repo import DeliveryRepository
from core.delivery.models import DeliveryCandidate, DeliverySnapshot, RemoteRepositoryBinding
from core.projects.models import ProjectCreate
from core.security.allowlist import ALL_COMMANDS, BridgeCommand
from core.security.secret_store import InMemorySecretStore

VALID_SHA = "a" * 40
DIFF_HASH = "b" * 64


@pytest.fixture
async def ctx(tmp_path: Path):
    context = await build_context(tmp_path / "deployment-bridge-test.db", secret_store=InMemorySecretStore())
    try:
        yield context
    finally:
        await context.db.close()


async def _create_test_project(ctx, project_id: str = "proj-1") -> str:
    proj = await ctx.project_service.create_project(ProjectCreate(name="Lifecycle Project", workspace_path="/tmp"))
    return proj.id


async def _create_merged_delivery_candidate(ctx, project_id: str | None = None, mission_id: str = "m-1") -> tuple[str, str]:
    from core.missions.models import Mission
    from core.utils.time import utc_now

    pid = project_id or await _create_test_project(ctx)
    mission = Mission(
        id=mission_id,
        project_id=pid,
        request="Ship feature",
        status="completed",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    await ctx.mission_service.repo.put(mission, command_id=f"cmd-{mission_id}")

    delivery_repo = DeliveryRepository(ctx.db)
    cand_id = "dc-test-1"
    snap_id = "ds-test-1"
    bind_id = "bind-1"
    binding = RemoteRepositoryBinding(
        id=bind_id,
        project_id=pid,
        provider="git",
        remote_url_sanitized="https://github.com/org/repo",
    )
    await delivery_repo.save_binding(binding)
    snapshot = DeliverySnapshot(
        id=snap_id,
        candidate_id=cand_id,
        version=1,
        mission_id=mission_id,
        project_id=pid,
        base_sha=VALID_SHA,
        integration_sha=VALID_SHA,
        diff_hash=DIFF_HASH,
        commits=[{"sha": VALID_SHA, "message": "feat: ready"}],
        diff_stat={"insertions": 10, "deletions": 2, "files": 1},
        tasks_summary=[],
        reviews_summary=[],
        resolved_conflicts_summary=[],
        quality_gates_summary=[],
        known_risks=[],
    )
    candidate = DeliveryCandidate(
        id=cand_id,
        mission_id=mission_id,
        project_id=pid,
        version=1,
        status="merged",
        current_snapshot_id=snap_id,
        target_remote_binding_id=bind_id,
    )
    await delivery_repo.create(candidate, snapshot, {"diff_files": ["main.py"], "integration_path": "/tmp"})
    return pid, cand_id


@pytest.mark.asyncio
async def test_context_wires_deployment_subsystems(ctx) -> None:
    assert ctx.deployment_repo is not None
    assert ctx.deployment_service is not None
    assert ctx.deployment_orchestrator is not None


def test_allowlist_contains_all_16_deployment_commands() -> None:
    expected_commands = [
        "deployment.environment.list",
        "deployment.environment.get",
        "deployment.environment.bind",
        "deployment.release.create",
        "deployment.release.get",
        "deployment.release.list",
        "deployment.predeploy.run",
        "deployment.approval.submit",
        "deployment.run.execute",
        "deployment.run.get",
        "deployment.health.check",
        "deployment.promote.request",
        "deployment.promote.execute",
        "deployment.rollback.propose",
        "deployment.rollback.execute",
        "deployment.recovery.reconcile",
    ]
    for cmd in expected_commands:
        assert cmd in ALL_COMMANDS
        assert BridgeCommand(cmd) in BridgeCommand


def test_long_deployment_commands_timeouts() -> None:
    expected_long = {
        "deployment.predeploy.run",
        "deployment.run.execute",
        "deployment.promote.execute",
        "deployment.rollback.execute",
    }
    assert _LONG_DEPLOYMENT_COMMANDS == expected_long

    for cmd in expected_long:
        assert request_timeout_seconds(cmd) == 10800
    assert request_timeout_seconds("deployment.environment.list") == 30
    assert request_timeout_seconds("deployment.release.create") == 30


@pytest.mark.asyncio
async def test_deployment_environments_autoseed_and_bind(ctx) -> None:
    project_id = "proj-env-test"
    envs = await dispatch("deployment.environment.list", {"project_id": project_id}, ctx)
    assert isinstance(envs, list)
    assert len(envs) == 3
    env_names = {e["name"] for e in envs}
    assert env_names == {"development", "staging", "production"}

    dev_env = next(e for e in envs if e["name"] == "development")
    fetched = await dispatch("deployment.environment.get", {"project_id": project_id, "environment_id": dev_env["id"]}, ctx)
    assert fetched["environment"]["name"] == "development"

    # Bind environment
    bind_result = await dispatch(
        "deployment.environment.bind",
        {
            "project_id": project_id,
            "environment_id": dev_env["id"],
            "remote_url": "https://github.com/org/repo.git",
            "repo_name": "org/repo",
            "workflow_file": "deploy.yml",
            "environment_name": "development",
        },
        ctx,
    )
    assert bind_result["repo_name"] == "org/repo"


@pytest.mark.asyncio
async def test_deployment_health_check(ctx) -> None:
    project_id = "proj-hp-test"
    envs = await dispatch("deployment.environment.list", {"project_id": project_id}, ctx)
    dev_env = next(e for e in envs if e["name"] == "development")

    check_result = await dispatch(
        "deployment.health.check",
        {"project_id": project_id, "environment_id": dev_env["id"]},
        ctx,
    )
    assert "status" in check_result
    assert check_result["status"] in {"passed", "healthy", "failed", "unhealthy"}


@pytest.mark.asyncio
async def test_deployment_release_lifecycle(ctx) -> None:
    project_id, del_cand_id = await _create_merged_delivery_candidate(ctx)

    # 1. Create release
    created = await dispatch(
        "deployment.release.create",
        {"project_id": project_id, "delivery_candidate_id": del_cand_id},
        ctx,
    )
    release_obj = created["release_candidate"]
    release_id = release_obj["id"]
    assert release_id is not None
    assert release_obj["status"] == "draft"
    assert release_obj["version"] == 1
    assert release_obj["target_sha"] == VALID_SHA

    # 2. List releases
    release_list = await dispatch("deployment.release.list", {"project_id": project_id}, ctx)
    assert isinstance(release_list, list)
    assert len(release_list) >= 1

    # 3. Get release detail
    detail = await dispatch("deployment.release.get", {"project_id": project_id, "release_candidate_id": release_id}, ctx)
    assert detail["release_candidate"]["id"] == release_id
    assert len(detail["environments_status"]) == 3

    # 4. Predeploy run
    predeploy = await dispatch(
        "deployment.predeploy.run",
        {"project_id": project_id, "release_candidate_id": release_id},
        ctx,
    )
    assert predeploy["status"] == "passed"

    # Verify release status transitioned
    refreshed = await dispatch("deployment.release.get", {"project_id": project_id, "release_candidate_id": release_id}, ctx)
    assert refreshed["release_candidate"]["status"] == "awaiting_development_approval"

    # 5. Submit approval
    envs = await dispatch("deployment.environment.list", {"project_id": project_id}, ctx)
    dev_env = next(e for e in envs if e["name"] == "development")

    approval = await dispatch(
        "deployment.approval.submit",
        {
            "project_id": project_id,
            "release_candidate_id": release_id,
            "environment_id": dev_env["id"],
            "action": "deploy_development",
            "decision": "approved",
            "actor_id": "reviewer-alice",
            "actor_role": "lead",
            "comment": "Predeploy checks passed",
        },
        ctx,
    )
    assert approval["status"] == "approved"

    # 6. Promotion request
    envs = await dispatch("deployment.environment.list", {"project_id": project_id}, ctx)
    staging_env = next(e for e in envs if e["name"] == "staging")
    promo = await dispatch(
        "deployment.promote.request",
        {
            "project_id": project_id,
            "release_candidate_id": release_id,
            "from_environment_id": dev_env["id"],
            "to_environment_id": staging_env["id"],
            "actor_id": "lead-alice",
        },
        ctx,
    )
    assert promo["status"] == "pending"
    assert promo["from_environment_id"] == dev_env["id"]
    assert promo["to_environment_id"] == staging_env["id"]

    # 7. Recovery reconcile
    recovery = await dispatch(
        "deployment.recovery.reconcile",
        {"project_id": project_id},
        ctx,
    )
    assert "is_blocked" in recovery
    assert recovery["is_blocked"] is False


@pytest.mark.asyncio
async def test_deployment_release_create_rejects_unmerged_candidate(ctx) -> None:
    from core.missions.models import Mission
    from core.utils.errors import ValidationError
    from core.utils.time import utc_now

    pid = await _create_test_project(ctx)
    mission = Mission(
        id="m-unmerged",
        project_id=pid,
        request="Unmerged candidate",
        status="completed",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    await ctx.mission_service.repo.put(mission, command_id="cmd-m-unmerged")

    delivery_repo = DeliveryRepository(ctx.db)
    cand_id = "dc-unmerged"
    snap_id = "ds-unmerged"
    bind_id = "bind-unmerged"
    binding = RemoteRepositoryBinding(
        id=bind_id,
        project_id=pid,
        provider="git",
        remote_url_sanitized="https://github.com/org/repo",
    )
    await delivery_repo.save_binding(binding)
    snapshot = DeliverySnapshot(
        id=snap_id,
        candidate_id=cand_id,
        version=1,
        mission_id="m-unmerged",
        project_id=pid,
        base_sha=VALID_SHA,
        integration_sha=VALID_SHA,
        diff_hash=DIFF_HASH,
        commits=[{"sha": VALID_SHA, "message": "feat: test"}],
        diff_stat={"insertions": 1, "deletions": 0, "files": 1},
        tasks_summary=[],
        reviews_summary=[],
        resolved_conflicts_summary=[],
        quality_gates_summary=[],
        known_risks=[],
    )
    candidate = DeliveryCandidate(
        id=cand_id,
        mission_id="m-unmerged",
        project_id=pid,
        version=1,
        status="draft",
        current_snapshot_id=snap_id,
        target_remote_binding_id=bind_id,
    )
    await delivery_repo.create(candidate, snapshot, {"diff_files": ["main.py"], "integration_path": "/tmp"})

    with pytest.raises(ValidationError, match="must originate from a merged delivery candidate"):
        await dispatch("deployment.release.create", {"project_id": pid, "delivery_candidate_id": cand_id}, ctx)


@pytest.mark.asyncio
async def test_deployment_full_run_and_rollback_bridge(ctx) -> None:
    from core.deployment.models import (
        DeploymentRollbackExecution,
        DeploymentRun,
        ReleaseCandidate,
        ReleaseSnapshot,
    )

    project_id, del_cand_id = await _create_merged_delivery_candidate(ctx, mission_id="m-run-test")
    envs = await dispatch("deployment.environment.list", {"project_id": project_id}, ctx)
    dev_env = next(e for e in envs if e["name"] == "development")
    staging_env = next(e for e in envs if e["name"] == "staging")

    rel_res = await dispatch("deployment.release.create", {"project_id": project_id, "delivery_candidate_id": del_cand_id}, ctx)
    rc_id = rel_res["release_candidate"]["id"]

    await dispatch("deployment.predeploy.run", {"project_id": project_id, "release_candidate_id": rc_id}, ctx)
    await dispatch("deployment.approval.submit", {
        "project_id": project_id,
        "release_candidate_id": rc_id,
        "environment_id": dev_env["id"],
        "action": "deploy_development",
        "decision": "approved",
        "actor_id": "lead-1",
        "actor_role": "lead",
    }, ctx)

    # Mock deploy
    async def fake_deploy(release_candidate_id, environment_id, initiated_by=None, idempotency_key=None, inputs=None, **kwargs):
        run = DeploymentRun(
            project_id=project_id,
            release_candidate_id=release_candidate_id,
            environment_id=environment_id,
            environment_name="development",
            target_sha=VALID_SHA,
            idempotency_key=idempotency_key or "test-run-bridge",
            initiated_by=initiated_by or "lead-1",
            status="in_flight",
        )
        await ctx.deployment_service.repo.save_run(run)
        return run
    ctx.deployment_service.deploy = fake_deploy

    # 1. deployment.run.execute
    run_res = await dispatch("deployment.run.execute", {
        "project_id": project_id,
        "release_candidate_id": rc_id,
        "environment_id": dev_env["id"],
        "idempotency_key": "exec-bridge-1",
        "initiated_by": "lead-1",
    }, ctx)
    assert run_res["run"]["status"] == "in_flight"
    run_id = run_res["run"]["id"]

    # 2. deployment.run.get
    run_get = await dispatch("deployment.run.get", {"project_id": project_id, "deployment_run_id": run_id}, ctx)
    assert run_get["run"]["id"] == run_id

    # Mark as succeeded and update environment for promotion
    run_row = await ctx.db.fetch_one("SELECT data FROM deployment_runs WHERE id=?", (run_id,))
    run_obj = DeploymentRun.model_validate_json(run_row["data"])
    run_obj = run_obj.model_copy(update={"status": "succeeded"})
    await ctx.deployment_service.repo.save_run(run_obj)

    env = await ctx.deployment_service._environment(dev_env["id"])
    updated_env = env.model_copy(update={
        "current_release_id": rc_id,
        "current_release_sha": VALID_SHA,
        "last_healthy_release_id": rc_id,
        "last_healthy_release_sha": VALID_SHA,
        "observed_state": "healthy",
    })
    await ctx.deployment_service.repo.save_environment(updated_env)

    # 3. deployment.promote.request & execute
    promo_res = await dispatch("deployment.promote.request", {
        "project_id": project_id,
        "release_candidate_id": rc_id,
        "from_environment_id": dev_env["id"],
        "to_environment_id": staging_env["id"],
        "actor_id": "lead-1",
    }, ctx)
    promo_id = promo_res["id"]

    await dispatch("deployment.approval.submit", {
        "project_id": project_id,
        "release_candidate_id": rc_id,
        "environment_id": staging_env["id"],
        "action": "deploy_staging",
        "decision": "approved",
        "actor_id": "qa-1",
        "actor_role": "qa",
    }, ctx)

    promo_exec = await dispatch("deployment.promote.execute", {
        "project_id": project_id,
        "promotion_request_id": promo_id,
        "actor_id": "lead-1",
    }, ctx)
    assert promo_exec["run"]["status"] == "in_flight"

    # 4. deployment.rollback.propose & execute
    rc_old = ReleaseCandidate(
        id="rc-old-bridge",
        project_id=project_id,
        delivery_candidate_id=del_cand_id,
        delivery_snapshot_id="ds-old-bridge",
        version=99,
        target_sha="9" * 40,
        status="development_ready",
        created_by="lead-1",
    )
    snap_old = ReleaseSnapshot(
        id="snap-old-bridge",
        release_candidate_id=rc_old.id,
        version=99,
        target_sha="9" * 40,
        artifacts_hash="9" * 64,
    )
    await ctx.deployment_service.repo.save_release(rc_old, snap_old)

    rollback_prop = await dispatch("deployment.rollback.propose", {
        "project_id": project_id,
        "deployment_run_id": run_id,
        "environment_id": dev_env["id"],
        "target_release_id": rc_old.id,
        "reason": "Test regression",
        "actor_id": "lead-1",
    }, ctx)
    assert rollback_prop["status"] in {"proposed", "pending"}
    plan_id = rollback_prop["id"]

    async def fake_rollback(run_id, *, initiated_by, target_release_id=None, approved=False):
        return DeploymentRollbackExecution(
            rollback_plan_id=plan_id,
            status="succeeded",
            initiated_by=initiated_by,
        )
    ctx.deployment_service.rollback = fake_rollback

    rollback_exec = await dispatch("deployment.rollback.execute", {
        "project_id": project_id,
        "rollback_plan_id": plan_id,
        "actor_id": "lead-1",
    }, ctx)
    assert rollback_exec["status"] == "succeeded"
