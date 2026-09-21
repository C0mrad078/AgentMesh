from __future__ import annotations

import pytest
from core.database.repositories.deployment_repo import DeploymentRepository
from core.deployment.leases import LeaseManager
from core.deployment.models import (
    ReleaseCandidate,
    ReleaseSnapshot,
)
from core.deployment.policies import validate_promotion_sha
from core.deployment.recovery import reconcile_deployments
from core.deployment.state_machine import RELEASE_STATES, assert_transition, can_transition
from core.deployment.telemetry import DeploymentTelemetry
from core.utils.errors import DatabaseError, InvalidStateTransitionError, ValidationError
from core.utils.time import utc_now


def test_contract_has_exactly_27_states_and_rejects_shortcuts() -> None:
    assert len(RELEASE_STATES) == 27
    assert len(set(RELEASE_STATES)) == 27
    assert can_transition("draft", "ready_for_predeploy")
    assert not can_transition("draft", "deploying_production")
    with pytest.raises(InvalidStateTransitionError):
        assert_transition("draft", "production_healthy")


async def test_release_snapshot_is_frozen_and_persisted(tmp_db) -> None:
    repo = DeploymentRepository(tmp_db)
    release = ReleaseCandidate(project_id="p", delivery_candidate_id="dc", delivery_snapshot_id="ds", target_sha="a" * 40, created_by="producer")
    snapshot = ReleaseSnapshot(release_candidate_id=release.id, version=release.version, target_sha=release.target_sha, artifacts_hash="b" * 64)
    await repo.save_release(release, snapshot)
    assert (await repo.release(release.id)).target_sha == "a" * 40
    with pytest.raises(DatabaseError):
        await tmp_db.execute("UPDATE release_snapshots SET data='{}' WHERE id=?", (snapshot.id,))


async def test_environment_lease_is_atomic_and_expirable(tmp_db) -> None:
    manager = LeaseManager(tmp_db)
    first = await manager.acquire("env", "run-1", ttl_seconds=30)
    assert first is not None
    assert await manager.acquire("env", "run-2", ttl_seconds=30) is None
    await manager.release(first.lease_token)
    assert await manager.acquire("env", "run-2", ttl_seconds=30) is not None


async def test_telemetry_keeps_unmeasured_values_null(tmp_db) -> None:
    telemetry = DeploymentTelemetry(tmp_db)
    phase = await telemetry.start_phase("run", "queue")
    assert phase.duration_ms is None
    stored = await telemetry.list_phases("run")
    assert stored[0].duration_ms is None
    finished = await telemetry.finish_phase(phase.id, status="completed")
    assert finished.duration_ms is not None


async def test_recovery_blocks_inflight_runs_and_reports_action(tmp_db) -> None:
    now = utc_now().isoformat()
    await tmp_db.execute("INSERT INTO deployment_runs(id,project_id,release_candidate_id,environment_id,target_sha,status,idempotency_key,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", ("run", "p", "rel", "env", "a" * 40, "in_flight", "key", "{}", now, now))
    state = await reconcile_deployments(tmp_db, "p")
    assert state.is_blocked
    assert state.reconciled_runs_count == 1
    assert state.suggested_action


def test_promotion_requires_identical_sha() -> None:
    release = ReleaseCandidate(project_id="p", delivery_candidate_id="dc", delivery_snapshot_id="ds", target_sha="a" * 40, created_by="producer")
    validate_promotion_sha(release, "a" * 40)
    with pytest.raises(ValidationError):
        validate_promotion_sha(release, "b" * 40)
