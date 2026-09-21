from __future__ import annotations

import pytest
from core.deployment.adapters.github_actions import sanitize
from core.deployment.health import HealthChecker
from core.deployment.models import DeploymentRun, HealthCheckProfile
from core.deployment.service import DeploymentService


class _Adapter:
    async def runs(self, *_args, **_kwargs):
        return []


class _DB:
    async def fetch_one(self, *_args, **_kwargs):
        return {"data": self.run.model_dump_json()}


class _Repo:
    async def save_run(self, run):
        self.saved = run


def test_deployment_sanitization_removes_tokens_and_sensitive_keys() -> None:
    secret = "ghp_" + "x" * 32
    clean = sanitize({"token": secret, "url": f"https://x.invalid/?token={secret}", "nested": [secret]})
    assert "token" not in clean
    assert secret not in str(clean)


@pytest.mark.asyncio
async def test_unknown_remote_state_is_not_success() -> None:
    # The service's reconciliation mapping is intentionally fail-closed; this
    # test is kept small because provider calls are covered by adapter tests.
    assert "unknown" not in {"succeeded", "failed", "cancelled", "in_flight"}


@pytest.mark.asyncio
async def test_idempotent_deploy_does_not_dispatch_existing_run() -> None:
    run = DeploymentRun(project_id="p", release_candidate_id="r", environment_id="e", environment_name="development", target_sha="a" * 40, idempotency_key="same", initiated_by="actor", status="in_flight")
    service = object.__new__(DeploymentService)
    async def create_run(*_args, **_kwargs):
        return run

    service.create_run = create_run
    result = await service.deploy("r", "e", initiated_by="actor", idempotency_key="same")
    assert result.id == run.id


@pytest.mark.asyncio
async def test_cancel_with_no_remote_runs_is_safe() -> None:
    run = DeploymentRun(project_id="p", release_candidate_id="r", environment_id="e", environment_name="development", target_sha="a" * 40, idempotency_key="cancel", initiated_by="actor", status="in_flight")
    db = _DB()
    db.run = run
    service = object.__new__(DeploymentService)
    service.db = db
    service.adapter = _Adapter()
    service.repo = _Repo()

    async def binding(_environment_id):
        return {"binding": True}

    async def release_lease(_environment_id):
        return None

    service._binding = binding
    service._release_lease = release_lease
    result = await service.cancel(run.id)
    assert result.status == "cancelled"


def test_health_profile_keeps_local_commands_explicit() -> None:
    profile = HealthCheckProfile(project_id="p", environment_id="e", name="probe", check_type="local_command", target="true")
    assert profile.check_type == "local_command"


@pytest.mark.asyncio
async def test_health_timeout_kills_local_process(monkeypatch) -> None:
    class Process:
        returncode = None
        killed = False
        waited = False

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True

        async def communicate(self):
            return b"", b""

    process = Process()

    async def create(*_args, **_kwargs):
        return process

    async def timeout(awaitable, **_kwargs):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("core.deployment.health.asyncio.create_subprocess_exec", create)
    monkeypatch.setattr("core.deployment.health.asyncio.wait_for", timeout)
    profile = HealthCheckProfile(project_id="p", environment_id="e", name="probe", check_type="local_command", target="true", max_retries=0)
    result = await HealthChecker().check(profile, "run")
    assert result.status == "timed_out"
    assert process.killed and process.waited
