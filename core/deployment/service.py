from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.deployment_repo import DeploymentRepository
from core.deployment.adapters.github_actions import GitHubActionsAdapter, sanitize
from core.deployment.health import HealthChecker
from core.deployment.leases import LeaseManager
from core.deployment.models import (
    DeploymentApproval,
    DeploymentAttempt,
    DeploymentEnvironment,
    DeploymentOperation,
    DeploymentRollbackExecution,
    DeploymentRollbackPlan,
    DeploymentRun,
    HealthCheckProfile,
    ReleaseCandidate,
)
from core.deployment.policies import approvals_satisfied, requires_approval, validate_promotion_sha
from core.deployment.recovery import reconcile_deployments
from core.deployment.state_machine import assert_transition
from core.utils.errors import NotFoundError, ValidationError
from core.utils.time import utc_now


class DeploymentService:
    def __init__(self, db: Database, adapter: GitHubActionsAdapter, *, health_checker: HealthChecker | None = None) -> None:
        self.db = db
        self.repo = DeploymentRepository(db)
        self.adapter = adapter
        self.health_checker = health_checker or HealthChecker()
        self.leases = LeaseManager(db)

    async def _environment(self, environment_id: str) -> DeploymentEnvironment:
        row = await self.db.fetch_one("SELECT data FROM deployment_environments WHERE id=?", (environment_id,))
        if row is None:
            raise NotFoundError("Deployment environment not found")
        return DeploymentEnvironment.model_validate_json(row["data"])

    async def _binding(self, environment_id: str):
        row = await self.db.fetch_one("SELECT data FROM deployment_bindings WHERE environment_id=? AND project_id IN (SELECT project_id FROM deployment_environments WHERE id=?) ORDER BY rowid DESC LIMIT 1", (environment_id, environment_id))
        if row is None:
            raise NotFoundError("Deployment binding not found")
        from core.deployment.models import DeploymentBinding
        return DeploymentBinding.model_validate_json(row["data"])

    async def _release(self, release_id: str) -> ReleaseCandidate:
        return await self.repo.release(release_id)

    async def _approvals(self, release_id: str, environment_id: str) -> list[DeploymentApproval]:
        rows = await self.db.fetch_all("SELECT data FROM deployment_approvals WHERE release_candidate_id=? AND environment_id=?", (release_id, environment_id))
        return [DeploymentApproval.model_validate_json(row["data"]) for row in rows]

    async def _release_lease(self, environment_id: str) -> None:
        lease = await self.leases.active(environment_id)
        if lease is not None:
            await self.leases.release(lease.lease_token)

    async def _mark_environment_healthy(self, environment: DeploymentEnvironment, run: DeploymentRun) -> None:
        updated = environment.model_copy(update={"current_release_id": run.release_candidate_id, "current_release_sha": run.target_sha, "last_healthy_release_id": run.release_candidate_id, "last_healthy_release_sha": run.target_sha, "observed_state": "healthy", "updated_at": utc_now()})
        await self.repo.save_environment(updated)

    async def create_run(self, release_id: str, environment_id: str, *, initiated_by: str, idempotency_key: str) -> DeploymentRun:
        existing = await self.repo.run_by_idempotency(idempotency_key)
        if existing:
            return existing
        release = await self._release(release_id)
        environment = await self._environment(environment_id)
        if release.project_id != environment.project_id:
            raise ValidationError("Release and environment belong to different projects")
        run = DeploymentRun(project_id=release.project_id, release_candidate_id=release.id, environment_id=environment.id, environment_name=environment.name, target_sha=release.target_sha, initiated_by=initiated_by, idempotency_key=idempotency_key)
        await self.repo.save_run(run)
        return run

    async def deploy(self, release_id: str, environment_id: str, *, initiated_by: str, idempotency_key: str, inputs: dict[str, str] | None = None) -> DeploymentRun:
        run = await self.create_run(release_id, environment_id, initiated_by=initiated_by, idempotency_key=idempotency_key)
        if run.status != "pending":
            return run
        environment = await self._environment(environment_id)
        binding = await self._binding(environment_id)
        release = await self._release(release_id)
        policy = environment.approval_policy
        approvals = await self._approvals(release_id, environment_id)
        if requires_approval(environment.name, policy) and not approvals_satisfied(release=release, environment=environment.name, policy=policy, approvals=approvals):
            raise ValidationError("Required deployment approval is not satisfied")
        target_status = {"development": "deploying_development", "staging": "deploying_staging", "production": "deploying_production"}[environment.name]
        assert_transition(release.status, target_status)  # type: ignore[arg-type]
        lease = await self.leases.acquire(environment_id, run.id, ttl_seconds=environment.timeout_seconds)
        if lease is None:
            blocked = run.model_copy(update={"status": "blocked", "error_message": "Environment is already leased", "updated_at": utc_now()})
            await self.repo.save_run(blocked)
            return blocked
        try:
            now = utc_now()
            run = run.model_copy(update={"status": "leased", "started_at": now, "updated_at": now})
            await self.repo.save_run(run)
            attempt = DeploymentAttempt(deployment_run_id=run.id, attempt_number=run.current_attempt_number)
            await self.repo.put(attempt)
            operation = DeploymentOperation(deployment_run_id=run.id, idempotency_key=f"{run.id}:dispatch", operation_type="dispatch_workflow", provider="github_actions", status="in_flight", request_payload_sanitized={"sha": run.target_sha, "workflow": binding.workflow_file})
            await self.repo.put(operation)
            result = await self.adapter.dispatch(binding, run.target_sha, inputs=inputs)
            operation = operation.model_copy(update={"status": "succeeded", "response_payload_sanitized": sanitize(result), "updated_at": utc_now()})
            await self.repo.put(operation)
            run = run.model_copy(update={"status": "in_flight", "updated_at": utc_now()})
            await self.repo.save_run(run)
            return run
        except Exception as exc:
            safe = sanitize(str(exc))[:500]
            failed = run.model_copy(update={"status": "blocked", "error_message": safe, "updated_at": utc_now()})
            await self.repo.save_run(failed)
            await self.leases.release(lease.lease_token)
            raise

    async def poll(self, run_id: str) -> DeploymentRun:
        row = await self.db.fetch_one("SELECT data FROM deployment_runs WHERE id=?", (run_id,))
        if row is None:
            raise NotFoundError("Deployment run not found")
        run = DeploymentRun.model_validate_json(row["data"])
        binding = await self._binding(run.environment_id)
        remote = await self.adapter.reconcile(binding, run.target_sha)
        state = remote.get("state")
        if state == "succeeded" and str(remote.get("sha", "")).lower() == run.target_sha.lower():
            status = "succeeded"
        elif state in {"failed", "cancelled"}:
            status = state
        elif state == "in_progress":
            status = "in_flight"
        else:
            status = "blocked"
        result = run.model_copy(update={"status": status, "error_message": None if status in {"succeeded", "in_flight"} else "Remote provider state is unknown or did not verify the target SHA", "completed_at": utc_now() if status in {"succeeded", "failed", "cancelled", "blocked"} else None, "updated_at": utc_now()})
        await self.repo.save_run(result)
        if status == "succeeded":
            await self._mark_environment_healthy(await self._environment(run.environment_id), result)
        if status in {"succeeded", "failed", "cancelled", "blocked"}:
            await self._release_lease(run.environment_id)
        return result

    async def cancel(self, run_id: str) -> DeploymentRun:
        row = await self.db.fetch_one("SELECT data FROM deployment_runs WHERE id=?", (run_id,))
        if row is None:
            raise NotFoundError("Deployment run not found")
        run = DeploymentRun.model_validate_json(row["data"])
        binding = await self._binding(run.environment_id)
        if run.status in {"in_flight", "leased"}:
            runs = await self.adapter.runs(binding, run.target_sha)
            if runs:
                await self.adapter.cancel(binding, str(runs[0]["id"]))
        result = run.model_copy(update={"status": "cancelled", "completed_at": utc_now(), "updated_at": utc_now()})
        await self.repo.save_run(result)
        await self._release_lease(run.environment_id)
        return result

    async def reconcile_after_restart(self, project_id: str | None = None):
        return await reconcile_deployments(self.db, project_id)

    async def promote(self, release_id: str, from_environment_id: str, to_environment_id: str, *, initiated_by: str, idempotency_key: str) -> DeploymentRun:
        release = await self._release(release_id)
        source = await self._environment(from_environment_id)
        target = await self._environment(to_environment_id)
        if source.project_id != target.project_id or release.project_id != target.project_id:
            raise ValidationError("Promotion resources belong to different projects")
        if not source.current_release_sha or source.current_release_sha.lower() != release.target_sha.lower():
            raise ValidationError("Source environment does not contain the release SHA")
        validate_promotion_sha(release, release.target_sha)
        return await self.deploy(release_id, to_environment_id, initiated_by=initiated_by, idempotency_key=idempotency_key)

    async def verify_health(self, run_id: str, profile: HealthCheckProfile):
        result = await self.health_checker.check(profile, run_id)
        await self.db.execute("INSERT INTO health_check_results(id,deployment_run_id,profile_id,status,data,checked_at) VALUES(?,?,?,?,?,?)", (result.id, result.deployment_run_id, result.profile_id, result.status, result.model_dump_json(), result.checked_at.isoformat()))
        return result

    async def rollback(self, run_id: str, *, initiated_by: str, target_release_id: str | None = None, approved: bool = False) -> DeploymentRollbackExecution:
        """Execute a rollback only to a known healthy release.

        Production rollback approval is deliberately explicit at this boundary;
        callers cannot accidentally infer approval from a deployment approval.
        """
        row = await self.db.fetch_one("SELECT data FROM deployment_runs WHERE id=?", (run_id,))
        if row is None:
            raise NotFoundError("Deployment run not found")
        run = DeploymentRun.model_validate_json(row["data"])
        environment = await self._environment(run.environment_id)
        if environment.name == "production" and not approved:
            raise ValidationError("Production rollback requires dedicated approval")
        target_id = target_release_id or environment.last_healthy_release_id
        if not target_id:
            raise ValidationError("No previously healthy release is available for rollback")
        target = await self._release(target_id)
        if target.project_id != run.project_id:
            raise ValidationError("Rollback release belongs to a different project")
        plan = DeploymentRollbackPlan(project_id=run.project_id, deployment_run_id=run.id, environment_id=run.environment_id, current_release_id=run.release_candidate_id, target_release_id=target.id, target_sha=target.target_sha, rollback_strategy="specific_release" if target_release_id else "previous_healthy", impact_summary=f"Restore release {target.id}", risk_assessment="Revert to a known healthy release", status="approved")
        await self.db.execute("INSERT INTO deployment_rollback_plans(id,project_id,deployment_run_id,environment_id,current_release_id,target_release_id,target_sha,status,data,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (plan.id, plan.project_id, plan.deployment_run_id, plan.environment_id, plan.current_release_id, plan.target_release_id, plan.target_sha, plan.status, plan.model_dump_json(), plan.created_at.isoformat()))
        execution = DeploymentRollbackExecution(rollback_plan_id=plan.id, initiated_by=initiated_by)
        binding = await self._binding(run.environment_id)
        try:
            result = await self.adapter.dispatch(binding, target.target_sha, inputs={"rollback": "true", "rollback_from": run.target_sha})
            execution = execution.model_copy(update={"status": "succeeded", "post_verification_status": "pending", "provider_run_id": str(result.get("run_id")) if result.get("run_id") else None, "provider_run_url": result.get("url"), "completed_at": utc_now()})
        except Exception as exc:
            execution = execution.model_copy(update={"status": "failed", "error_message": sanitize(str(exc))[:500], "completed_at": utc_now()})
            raise
        finally:
            await self.db.execute("INSERT INTO deployment_rollback_executions(id,rollback_plan_id,status,initiated_by,data,executed_at) VALUES(?,?,?,?,?,?)", (execution.id, execution.rollback_plan_id, execution.status, execution.initiated_by, execution.model_dump_json(), execution.executed_at.isoformat()))
        return execution
