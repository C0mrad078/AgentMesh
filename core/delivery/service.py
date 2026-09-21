from __future__ import annotations

import asyncio
import builtins
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from core.database.repositories.delivery_repo import DeliveryRepository
from core.delivery import ci_monitor, preflight
from core.delivery.git_remote import GitRemote
from core.delivery.github_adapter import GitHubAdapter
from core.delivery.models import (
    Action,
    CIFailureFinding,
    CIWorkflowRun,
    DeliveryApproval,
    DeliveryCandidate,
    DeliverySnapshot,
    DeliveryStatus,
    InternalStep,
    Phase,
    PhaseTelemetry,
    PostMergeVerification,
    PreflightReport,
    PullRequestRecord,
    RemoteOperation,
    RemoteRepositoryBinding,
    RemoteRepositoryBindingInput,
    RollbackPlan,
)
from core.delivery.security import clean, clean_data, ref, sanitize_url
from core.delivery.state_machine import validate_transition
from core.integration.quality_gates import validate_gate
from core.missions.models import Mission
from core.orchestrator.event_bus import EventType, OrchestrationEvent
from core.utils.errors import ValidationError
from core.utils.time import utc_now

if TYPE_CHECKING:
    from core.bridge.context import BridgeContext


class DeliveryService:
    def __init__(
        self,
        ctx: BridgeContext,
        *,
        git: GitRemote | None = None,
        github: GitHubAdapter | None = None,
    ) -> None:
        self.ctx = ctx
        self.repo = DeliveryRepository(ctx.db)
        self.git = git or GitRemote()
        self.github = github or GitHubAdapter()
        self.lock = asyncio.Lock()
        self.max_fix_cycles = 3
        self.poll_seconds = 15
        self._polled: dict[str, float] = {}

    @property
    def missions(self):
        if self.ctx.mission_service is None:
            raise ValidationError("Mission service unavailable")
        return self.ctx.mission_service

    async def emit(self, event: EventType, **payload: Any) -> None:
        await self.ctx.event_bus.publish(
            OrchestrationEvent(type=event, execution_id="", payload=clean_data(payload))
        )

    async def state(self, candidate_id: str, status: DeliveryStatus) -> DeliveryCandidate:
        candidate = await self.repo.candidate(candidate_id)
        validate_transition(candidate.status, status)
        updated = candidate.model_copy(update={"status": status, "updated_at": utc_now()})
        await self.repo.save_candidate(updated)
        await self.emit(
            EventType.DELIVERY_CANDIDATE_UPDATED,
            candidate_id=updated.id,
            status=status,
            version=updated.version,
        )
        return updated

    @asynccontextmanager
    async def phase(self, candidate: DeliveryCandidate, name: Phase, **metrics: Any):
        started = utc_now()
        step = InternalStep(
            candidate_id=candidate.id, name=name, status="in_progress", metadata=metrics
        )
        await self.repo.put(step)
        error = None
        cancelled = False
        try:
            yield metrics
        except BaseException as exc:
            cancelled = isinstance(exc, asyncio.CancelledError)
            error = (
                "Operation cancelled"
                if isinstance(exc, asyncio.CancelledError)
                else clean(str(exc))
            )
            raise
        finally:
            if error is not None and name == "preflight":
                current = await self.repo.candidate(candidate.id)
                if current.status == "preflight_running":
                    await self.state(candidate.id, "preflight_failed")
            if error is None:
                current = await self.repo.candidate(candidate.id)
                if (
                    name == "preflight"
                    and current.status == "preflight_failed"
                    or name == "post_merge"
                    and current.status == "post_merge_failed"
                    or name == "ci_monitoring"
                    and current.status == "ci_failed"
                ):
                    error = f"{name} reported failure"
            finished = utc_now()
            await self.repo.put(
                step.model_copy(
                    update={
                        "status": "failed" if error else "completed",
                        "updated_at": finished,
                        "metadata": {**metrics, "error": error},
                    }
                )
            )
            if error is None:
                for previous in await self.repo.records(InternalStep, candidate.id):
                    if (
                        previous.id != step.id
                        and previous.name == name
                        and previous.status == "in_progress"
                    ):
                        await self.repo.put(
                            previous.model_copy(
                                update={
                                    "status": "failed",
                                    "updated_at": finished,
                                    "metadata": {
                                        **previous.metadata,
                                        "recovered_by": step.id,
                                        "error": "Previous phase interrupted; repeated safely",
                                    },
                                }
                            )
                        )
            await self.repo.put(
                PhaseTelemetry(
                    mission_id=candidate.mission_id,
                    candidate_id=candidate.id,
                    phase=name,
                    started_at=started,
                    finished_at=finished,
                    duration_ms=int((finished - started).total_seconds() * 1000),
                    outcome="cancelled" if cancelled else "failure" if error else "success",
                    error_sanitized=error,
                    **{k: v for k, v in metrics.items() if k in PhaseTelemetry.model_fields},
                )
            )

    async def binding_save(self, data: RemoteRepositoryBindingInput) -> RemoteRepositoryBinding:
        await self.ctx.project_service.get_project(data.project_id)
        url = sanitize_url(data.remote_url)
        owner = repository = None
        if data.provider == "github":
            parsed = urlsplit(url)
            parts = parsed.path.strip("/").removesuffix(".git").split("/")
            if parsed.hostname != "github.com" or len(parts) != 2:
                raise ValidationError("GitHub binding must identify github.com/owner/repository")
            owner, repository = parts
            if (
                data.owner
                and data.owner != owner
                or data.repository
                and data.repository != repository
            ):
                raise ValidationError("Owner/repository do not match remote URL")
        binding = RemoteRepositoryBinding(
            project_id=data.project_id,
            provider=data.provider,
            remote_name=ref(data.remote_name),
            remote_url_sanitized=url,
            owner=owner,
            repository=repository,
            target_branch=ref(data.target_branch),
            default_merge_method=data.default_merge_method,
        )
        await self.repo.save_binding(binding)
        return binding

    async def create(self, mission_id: str, project_id: str) -> dict[str, Any]:
        mission = await self.missions.repo.get(Mission, mission_id)
        if mission.project_id != project_id or mission.status != "completed":
            raise ValidationError("An approved completed integration mission is required")
        source = await self.missions.repo.snapshot(mission_id)
        if not source.approvals or source.approvals[-1].decision != "approved":
            raise ValidationError("Human integration approval required")
        if not source.integrations or any(i.result != "integrated" for i in source.integrations):
            raise ValidationError("Successful integration evidence required")
        if any(c.status != "resolved" for c in source.conflicts):
            raise ValidationError("Unresolved integration conflicts")
        root = Path(await self.missions.workspace(mission))
        integration = self.missions.worktrees.root_for(root) / "integration"
        if not await self.git.clean_tree(integration):
            raise ValidationError("Integration worktree must be clean")
        head = await self.git.head(integration)
        base = source.integrations[0].base_sha
        if head != source.integrations[-1].commit_sha:
            raise ValidationError(
                "Integration HEAD changed after integration evidence; review again"
            )
        if any(t.status.value != "completed" for t in source.tasks):
            raise ValidationError("Only completed reviewed tasks may be delivered")
        if not source.quality_gates or not source.quality_gates[-1].passed:
            raise ValidationError("Approved integration quality gate evidence required")
        if source.approvals[-1].created_at < source.quality_gates[-1].created_at:
            raise ValidationError("Integration approval predates final quality gates")
        if not await self.git.ancestor(integration, base, head):
            raise ValidationError("Integration ancestry is invalid")
        existing = await self.repo.candidates(mission_id=mission_id)
        if existing:
            previous, _ = await self.repo.snapshot(existing[0].id)
            if previous.integration_sha == head:
                return await self.detail(existing[0].id)
            raise ValidationError(
                "Existing delivery must advance through the reviewed CI correction cycle"
            )
        binding = await self.repo.binding(project_id=project_id)
        candidate = await self._freeze(mission, binding, integration, base, head, 1)
        return await self.detail(candidate.id)

    async def _freeze(
        self,
        mission: Mission,
        binding: RemoteRepositoryBinding,
        root: Path,
        base: str,
        head: str,
        version: int,
        *,
        parent_id: str | None = None,
    ) -> DeliveryCandidate:
        from uuid import uuid4

        source = await self.missions.repo.snapshot(mission.id)
        evidence = await self.git.evidence(root, base, head)
        candidate = DeliveryCandidate(
            mission_id=mission.id,
            project_id=mission.project_id,
            version=version,
            current_snapshot_id=str(uuid4()),
            target_remote_binding_id=binding.id,
        )
        tasks = [
            {
                "key": t.input.get("plan_key", t.id),
                "title": t.title,
                "agent_id": t.assigned_agent_id,
                "status": t.status.value,
            }
            for t in source.tasks
        ]
        snapshot = DeliverySnapshot(
            id=candidate.current_snapshot_id,
            candidate_id=candidate.id,
            version=version,
            mission_id=mission.id,
            project_id=mission.project_id,
            base_sha=base,
            integration_sha=head,
            diff_hash=evidence["diff_hash"],
            commits=clean_data(evidence["commits"]),
            diff_sanitized=clean(evidence["diff"]),
            diff_stat={
                "files_changed": len(evidence["files"]),
                "insertions": sum(f["additions"] for f in evidence["files"]),
                "deletions": sum(f["deletions"] for f in evidence["files"]),
            },
            tasks_summary=clean_data(tasks),
            reviews_summary=[
                {
                    "reviewer_agent": next(
                        (s.agent_id for s in source.sessions if s.id == r.reviewer_session_id),
                        "unknown",
                    ),
                    "decision": r.verdict,
                    "timestamp": r.created_at.isoformat(),
                }
                for r in source.reviews
            ],
            resolved_conflicts_summary=[
                {
                    "file_path": f.path,
                    "resolution_strategy": next(
                        (
                            a.strategy
                            for a in reversed(source.resolution_attempts)
                            if a.conflict_id == c.id
                        ),
                        "unknown",
                    ),
                    "resolver": c.integrator_session_id,
                }
                for c in source.conflicts
                for f in c.files
            ],
            quality_gates_summary=[
                {
                    "profile_id": g.id,
                    "command": clean(" ".join(g.command)),
                    "exit_code": g.exit_code,
                    "status": "passed" if g.passed else "failed",
                }
                for g in source.quality_gates
            ],
            agents_summary=clean_data([a.model_dump(mode="json") for a in source.assignments]),
            sessions_summary=[{"id": s.id, "agent_id": s.agent_id} for s in source.sessions],
            acceptance_summary=clean_data(
                [{"key": t.key, "acceptance": t.acceptance} for p in source.plans for t in p.tasks]
            ),
            known_risks=["Binary changes require review"] if evidence["binary"] else [],
            integration_path=str(root),
        )
        await self.repo.create(
            candidate,
            snapshot,
            {
                "integration_path": str(root),
                "diff_files": evidence["files"],
                "parent_id": parent_id,
                "delivery_branch": f"agentmash/delivery-{mission.id}",
                "agents": snapshot.agents_summary,
                "sessions": snapshot.sessions_summary,
                "acceptance": snapshot.acceptance_summary,
            },
        )
        await self.emit(
            EventType.DELIVERY_CANDIDATE_UPDATED,
            candidate_id=candidate.id,
            status=candidate.status,
            version=version,
        )
        return candidate

    async def context(self, candidate_id: str):
        candidate = await self.repo.candidate(candidate_id)
        snapshot, evidence = await self.repo.snapshot(candidate_id)
        binding = await self.repo.binding(binding_id=candidate.target_remote_binding_id)
        return candidate, snapshot, evidence, binding, Path(evidence["integration_path"])

    async def latest(self, cls, candidate_id: str):
        values = await self.repo.records(cls, candidate_id)
        return values[-1] if values else None

    async def final_gates(self, candidate: DeliveryCandidate, root: Path) -> bool:
        profiles = await self.ctx.integration_repo.list_profiles(candidate.project_id)
        profile = next((p for p in profiles if p.is_default), None)
        if profile is None or not any(g.enabled and g.required for g in profile.gates):
            raise ValidationError("Configure a final quality gate profile with required gates")
        for gate in sorted((g for g in profile.gates if g.enabled), key=lambda g: g.order):
            validate_gate(gate, root)
            if gate.approval_required:
                raise ValidationError("Quality gate requires separate command approval")
        mission = await self.missions.repo.get(Mission, candidate.mission_id)
        result = await self.missions.run_quality_gate(mission, root, None, "delivery final gates")
        return result.passed

    async def run_preflight(self, candidate_id: str) -> PreflightReport:
        candidate, snapshot, evidence, binding, root = await self.context(candidate_id)
        await self.state(candidate_id, "preflight_running")
        async with self.phase(candidate, "preflight"):
            errors: list[str] = []
            remote = base = tree = gates = False
            findings: list[dict] = []
            large: list[dict] = []
            special: list[str] = []
            try:
                await self.emit(
                    EventType.DELIVERY_PREFLIGHT_PROGRESS,
                    candidate_id=candidate_id,
                    step="remote",
                    status="running",
                )
                target = await self.git.fetch(root, binding, binding.target_branch)
                observations = (
                    await self.github.observe(root, binding)
                    if binding.provider == "github"
                    else {
                        "auth_detected": binding.remote_url_sanitized.startswith("ssh:"),
                        "auth_type": "ssh"
                        if binding.remote_url_sanitized.startswith("ssh:")
                        else "none",
                        "permissions": ["pull"],
                    }
                )
                binding = binding.model_copy(update={**observations, "last_verified_at": utc_now()})
                await self.repo.save_binding(binding)
                remote = binding.auth_detected and (
                    binding.provider != "github" or "push" in binding.permissions
                )
                base = target == snapshot.base_sha and await self.git.ancestor(
                    root, target, snapshot.integration_sha
                )
                tree = (
                    await self.git.clean_tree(root)
                    and await self.git.head(root) == snapshot.integration_sha
                )
                raw = await self.git.evidence(root, snapshot.base_sha, snapshot.integration_sha)
                if raw["diff_hash"] != snapshot.diff_hash:
                    raise ValidationError("Frozen diff does not match local objects")
                findings, large, special = await preflight.scan_evidence(
                    self.git, root, snapshot, raw
                )
                if tree and not findings and not large:
                    gates = await self.final_gates(candidate, root)
                    tree = (
                        await self.git.clean_tree(root)
                        and await self.git.head(root) == snapshot.integration_sha
                    )
            except Exception as exc:
                errors.append(clean(str(exc)))
            result = preflight.report(
                candidate,
                remote=remote,
                base=base,
                clean=tree,
                gates=gates,
                findings=findings,
                large=large,
                special=special,
                errors=errors,
            )
            await self.repo.put(result)
            await self.state(
                candidate_id,
                "awaiting_remote_approval" if result.status == "passed" else "preflight_failed",
            )
            await self.emit(
                EventType.DELIVERY_PREFLIGHT_PROGRESS,
                candidate_id=candidate_id,
                step="complete",
                status=result.status,
            )
            return result

    async def approve(
        self, candidate_id: str, action: Action, decision: str, actor: str, reason: str = ""
    ) -> DeliveryApproval:
        candidate, snapshot, evidence, binding, root = await self.context(candidate_id)
        if not actor.strip():
            raise ValidationError("Explicit human actor is required")
        if decision not in ("approved", "rejected"):
            raise ValidationError("Invalid approval decision")
        allowed = {
            "push": {"awaiting_remote_approval"},
            "pr_create": {"awaiting_remote_approval", "pr_open"},
            "pr_update": {"awaiting_remote_approval", "pr_open"},
            "merge": {"awaiting_merge_approval"},
            "rollback": {"rollback_proposed"},
        }
        if action not in allowed or candidate.status not in allowed[action]:
            raise ValidationError("Approval action is not available in current state")
        if action != "rollback":
            await self.require_preflight(candidate_id)
            if (
                not await self.git.clean_tree(root)
                or await self.git.head(root) != snapshot.integration_sha
            ):
                raise ValidationError("HEAD/tree changed; create a new candidate")
        if action == "merge":
            pr = await self.require_pr(candidate_id)
            observed = await self.github.view(root, binding, cast(int, pr.pr_number))
            await self.validate_head(candidate_id, snapshot, observed)
        approval = DeliveryApproval(
            candidate_id=candidate_id,
            version=candidate.version,
            action=action,
            decision=cast(Any, decision),
            actor=clean(actor.strip()),
            target_sha=snapshot.integration_sha,
            reason=clean(reason),
        )
        await self.repo.put(approval)
        if decision == "rejected":
            await self.state(candidate_id, "rejected")
        return approval

    async def require_preflight(self, candidate_id: str) -> PreflightReport:
        report = await self.latest(PreflightReport, candidate_id)
        if report is None or report.status != "passed":
            raise ValidationError("A passed preflight is mandatory")
        return report

    async def require_approval(
        self, candidate: DeliveryCandidate, snapshot: DeliverySnapshot, action: Action
    ) -> DeliveryApproval:
        approvals = await self.repo.records(DeliveryApproval, candidate.id)
        matches = [a for a in approvals if a.action == action and a.version == candidate.version]
        if (
            not matches
            or matches[-1].decision != "approved"
            or matches[-1].target_sha != snapshot.integration_sha
        ):
            raise ValidationError(f"Explicit human approval required for {action}")
        if action != "rollback":
            report = await self.require_preflight(candidate.id)
            if matches[-1].created_at < report.executed_at:
                raise ValidationError("Preflight changed; renew approval")
        return matches[-1]

    async def require_pr(self, candidate_id: str) -> PullRequestRecord:
        pr = await self.latest(PullRequestRecord, candidate_id)
        if not pr or not pr.pr_number:
            raise ValidationError("A persisted pull request is required")
        return pr

    async def validate_head(
        self, candidate_id: str, snapshot: DeliverySnapshot, observed: dict
    ) -> None:
        if observed.get("headRefOid") != snapshot.integration_sha:
            await self.state(candidate_id, "blocked")
            raise ValidationError(
                "PR head changed: approval invalidated; human intervention required"
            )
        if observed.get("isCrossRepository"):
            raise ValidationError("Fork PRs require manual delivery")

    async def detail(self, candidate_id: str) -> dict[str, Any]:
        candidate, snapshot, evidence, binding, _ = await self.context(candidate_id)
        pr = await self.latest(PullRequestRecord, candidate_id)
        report = await self.latest(PreflightReport, candidate_id)
        approvals = await self.repo.records(DeliveryApproval, candidate_id)
        operations = await self.repo.records(RemoteOperation, candidate_id)
        pending: list[str] = []
        if candidate.status in ("awaiting_remote_approval", "pr_open"):
            completed = {o.operation_type for o in operations if o.status == "completed"}
            pending = [
                a
                for a in ("push", "pr_update" if evidence.get("parent_id") else "pr_create")
                if a not in completed
            ]
        elif candidate.status == "awaiting_merge_approval":
            pending = ["merge"]
        elif candidate.status == "rollback_proposed":
            pending = ["rollback"]
        for a in approvals:
            if (
                a.action in pending
                and a.decision == "approved"
                and a.target_sha == snapshot.integration_sha
                and (a.action == "rollback" or report and a.created_at >= report.executed_at)
            ):
                pending.remove(a.action)
        steps = await self.repo.records(InternalStep, candidate_id)
        interrupted = any(s.status == "in_progress" for s in steps) or any(
            o.status == "running" and o.error_sanitized for o in operations
        )
        blocked = (
            candidate.status in ("blocked", "preflight_failed", "post_merge_failed") or interrupted
        )
        suggestion = {
            "preflight_failed": "retry_preflight",
            "ci_failed": "assign_ci_fix",
            "post_merge_failed": "revert_merge",
        }.get(candidate.status)
        if interrupted or candidate.status == "blocked":
            suggestion = "human_intervention"
        elif pending:
            suggestion = "request_approval"
        rollback = await self.latest(RollbackPlan, candidate_id)

        def dump(value):
            return value.model_dump(mode="json") if value else None

        result = {
            "candidate": dump(candidate),
            "snapshot": dump(snapshot),
            "remote_binding": dump(binding),
            "preflight": dump(report),
            "pull_request": dump(pr),
            "approvals": [dump(a) for a in approvals],
            "pending_approvals": pending,
            "remote_operations": [dump(o) for o in operations],
            "operations": [dump(o) for o in operations],
            "post_merge": dump(await self.latest(PostMergeVerification, candidate_id)),
            "rollback_plan": dump(rollback),
            "rollback": dump(rollback),
            "ci_runs": [dump(r) for r in await self.repo.records(CIWorkflowRun, candidate_id)],
            "ci_findings": [
                dump(r) for r in await self.repo.records(CIFailureFinding, candidate_id)
            ],
            "telemetry": [dump(r) for r in await self.repo.records(PhaseTelemetry, candidate_id)],
            "internal_steps": [dump(s) for s in steps],
            "diff_files": evidence["diff_files"],
            "remote_sha": pr.head_sha
            if pr
            else next(
                (
                    o.result.get("head_sha")
                    for o in operations
                    if o.operation_type == "push" and o.result
                ),
                None,
            ),
            "recovery": {
                "is_blocked": blocked,
                "recovery_reason": "Interrupted operation requires reconciliation"
                if interrupted
                else ("Delivery requires remediation" if blocked else None),
                "suggested_action": suggestion,
            },
        }
        return result

    async def list(
        self, project_id: str | None = None, mission_id: str | None = None
    ) -> list[dict]:
        result = []
        for c in await self.repo.candidates(project_id, mission_id):
            detail = await self.detail(c.id)
            pr, report = detail["pull_request"], detail["preflight"]
            result.append(
                {
                    **c.model_dump(mode="json"),
                    "base_sha": detail["snapshot"]["base_sha"],
                    "integration_sha": detail["snapshot"]["integration_sha"],
                    "remote_sha": detail["remote_sha"],
                    "pr_number": pr["pr_number"] if pr else None,
                    "pr_url": pr["pr_url"] if pr else None,
                    "risk_level": report["risk_level"] if report else "high",
                    "has_pending_approvals": bool(detail["pending_approvals"]),
                }
            )
        return result

    async def telemetry(self, candidate_id: str | None = None, mission_id: str | None = None):
        candidates = (
            [await self.repo.candidate(candidate_id)]
            if candidate_id
            else await self.repo.candidates(mission_id=mission_id)
        )
        return [
            r
            for c in candidates
            if not mission_id or c.mission_id == mission_id
            for r in await self.repo.records(PhaseTelemetry, c.id)
        ]

    async def execute(
        self, candidate_id: str, action: Action, key: str, merge_method: str | None = None
    ) -> RemoteOperation:
        candidate, snapshot, evidence, binding, root = await self.context(candidate_id)
        if not key or len(key) > 200:
            raise ValidationError("Invalid idempotency key")
        existing = await self.repo.operation(candidate_id, action, key)
        method = merge_method or binding.default_merge_method
        if existing and existing.payload_sanitized.get("merge_method") != method:
            raise ValidationError("Idempotency payload mismatch")
        if existing and existing.status == "completed":
            if action == "rollback" and candidate.status == "rollback_proposed":
                result = await self.observe_rollback(candidate, binding, root)
                if result:
                    return await self.complete(existing, result)
            return existing
        if existing and existing.status in ("running", "failed"):
            reconciled = await self.reconcile(existing, snapshot, evidence, binding, root)
            if reconciled is not None:
                return await self.complete(existing, reconciled)
            if existing.status == "running":
                raise ValidationError(
                    "Operation in progress or outcome uncertain; human intervention required"
                )
        allowed = {
            "push": {"awaiting_remote_approval", "pushing"},
            "pr_create": {"pr_open"},
            "pr_update": {"pr_open"},
            "merge": {"awaiting_merge_approval", "merging"},
            "rollback": {"rollback_proposed"},
        }
        if candidate.status not in allowed[action]:
            raise ValidationError(f"{action} unavailable in current delivery state")
        approval = await self.require_approval(candidate, snapshot, action)
        operation = existing or RemoteOperation(
            candidate_id=candidate_id,
            operation_type=action,
            idempotency_key=key,
            payload_sanitized={
                "head_sha": snapshot.integration_sha,
                "binding_id": binding.id,
                "branch": evidence["delivery_branch"],
                "merge_method": method,
            },
            approved_by=approval.actor,
        )
        operation = operation.model_copy(
            update={
                "status": "running",
                "approved_by": approval.actor,
                "attempts": operation.attempts + 1,
                "updated_at": utc_now(),
            }
        )
        if not await self.repo.claim(operation, retry=existing is not None):
            raise ValidationError(
                "Operation already claimed by another process; retry to reconcile"
            )
        phase = {
            "push": "remote_push",
            "pr_create": "pr_cycle",
            "pr_update": "pr_cycle",
            "merge": "merge",
            "rollback": "rollback",
        }[action]
        async with self.phase(
            candidate, cast(Phase, phase), retries=operation.attempts - 1, human_touch_count=1
        ):
            await self.emit(
                EventType.DELIVERY_OPERATION_PROGRESS,
                candidate_id=candidate_id,
                operation_id=operation.id,
                status="running",
            )
            try:
                if action == "rollback":
                    result = await self.perform_rollback(candidate, binding, root)
                elif action == "merge":
                    result = await self.perform_merge(candidate, snapshot, binding, root, method)
                else:
                    await self.freshness(candidate, snapshot, binding, root)
                    if action == "push":
                        await self.state(candidate_id, "pushing")
                        result = await self.git.push(
                            root, binding, evidence["delivery_branch"], snapshot.integration_sha
                        )
                        await self.state(candidate_id, "pr_open")
                    else:
                        pushes = await self.repo.records(RemoteOperation, candidate_id)
                        if not any(
                            p.operation_type == "push" and p.status == "completed" for p in pushes
                        ):
                            raise ValidationError("Push must complete before PR mutation")
                        observed_sha = await self.git.remote_sha(
                            root, binding, evidence["delivery_branch"]
                        )
                        if observed_sha != snapshot.integration_sha:
                            raise ValidationError("Remote delivery head differs from snapshot")
                        title, body = self.pr_text(candidate, snapshot)
                        if action == "pr_update":
                            if not evidence.get("parent_id"):
                                raise ValidationError(
                                    "PR update requires reviewed correction version"
                                )
                            old_pr = await self.require_pr(evidence["parent_id"])
                            observation = await self.github.view(
                                root, binding, cast(int, old_pr.pr_number)
                            )
                            await self.validate_head(candidate_id, snapshot, observation)
                            if observation.get("state") != "OPEN":
                                raise ValidationError("Closed/merged PR cannot be updated")
                            observation = await self.github.update(
                                root,
                                binding,
                                cast(int, old_pr.pr_number),
                                f"<!-- agentmash:{candidate.id}:{snapshot.diff_hash} -->",
                                body,
                            )
                        else:
                            if evidence.get("parent_id"):
                                raise ValidationError("Correction must update the existing PR")
                            observation = await self.github.create(
                                root, binding, evidence["delivery_branch"], title, body
                            )
                        pr = await self.save_pr(
                            candidate, snapshot, binding, evidence["delivery_branch"], observation
                        )
                        result = pr.model_dump(mode="json")
                return await self.complete(operation, result)
            except BaseException as exc:
                # A cancelled/crashed request remains uncertain. A terminated attempt
                # may retry under an atomic claim, reconciling remote state first.
                await self.repo.put(
                    operation.model_copy(
                        update={
                            "status": "failed" if isinstance(exc, Exception) else "running",
                            "error_sanitized": clean(str(exc))
                            if isinstance(exc, Exception)
                            else "Operation cancelled; reconcile remote outcome",
                            "updated_at": utc_now(),
                        }
                    )
                )
                raise

    async def complete(self, operation: RemoteOperation, result: dict) -> RemoteOperation:
        operation = operation.model_copy(
            update={
                "status": "completed",
                "result": clean_data(result),
                "error_sanitized": None,
                "updated_at": utc_now(),
            }
        )
        await self.repo.put(operation)
        phase = {
            "push": "remote_push",
            "pr_create": "pr_cycle",
            "pr_update": "pr_cycle",
            "merge": "merge",
            "rollback": "rollback",
        }[operation.operation_type]
        for step in await self.repo.records(InternalStep, operation.candidate_id):
            if step.name == phase and step.status == "in_progress":
                await self.repo.put(
                    step.model_copy(
                        update={
                            "status": "completed",
                            "updated_at": utc_now(),
                            "metadata": {**step.metadata, "reconciled_operation_id": operation.id},
                        }
                    )
                )
        await self.emit(
            EventType.DELIVERY_OPERATION_PROGRESS,
            candidate_id=operation.candidate_id,
            operation_id=operation.id,
            status="completed",
        )
        return operation

    async def freshness(
        self,
        candidate: DeliveryCandidate,
        snapshot: DeliverySnapshot,
        binding: RemoteRepositoryBinding,
        root: Path,
    ) -> None:
        await self.require_preflight(candidate.id)
        if (
            not await self.git.clean_tree(root)
            or await self.git.head(root) != snapshot.integration_sha
        ):
            raise ValidationError("Integration HEAD/tree changed after approval")
        target = await self.git.fetch(root, binding, binding.target_branch)
        if target != snapshot.base_sha or not await self.git.ancestor(
            root, target, snapshot.integration_sha
        ):
            raise ValidationError("Target advanced after preflight; rebase/review a new candidate")
        evidence = await self.git.evidence(root, snapshot.base_sha, snapshot.integration_sha)
        if evidence["diff_hash"] != snapshot.diff_hash:
            raise ValidationError("Approved diff mismatch")

    def pr_text(self, candidate: DeliveryCandidate, snapshot: DeliverySnapshot) -> tuple[str, str]:
        title = f"AgentMash delivery v{candidate.version}: {candidate.mission_id}"
        body = (
            f"<!-- agentmash:{candidate.mission_id} -->\n"
            f"Delivery candidate: {candidate.id} (v{candidate.version})\n"
            f"Base: {snapshot.base_sha}\nHead: {snapshot.integration_sha}\nDiff SHA256: {snapshot.diff_hash}\n\n"
            "Tasks:\n"
            + "\n".join(f"- {t['key']}: {t['title']}" for t in snapshot.tasks_summary)
            + "\n\nTests:\n"
            + "\n".join(f"- {g['command']}: {g['status']}" for g in snapshot.quality_gates_summary)
            + "\n\nResolved conflicts:\n"
            + "\n".join(
                f"- {c['file_path']}: {c['resolution_strategy']}"
                for c in snapshot.resolved_conflicts_summary
            )
            + "\n\nRisks:\n"
            + "\n".join(f"- {r}" for r in snapshot.known_risks)
            + "\n\n- [x] Frozen snapshot\n- [x] Preflight passed\n- [x] Human remote approval\n- [ ] CI and final merge approval\n"
        )
        return clean(title), clean(body)

    async def save_pr(
        self,
        candidate: DeliveryCandidate,
        snapshot: DeliverySnapshot,
        binding: RemoteRepositoryBinding,
        branch: str,
        observed: dict,
    ) -> PullRequestRecord:
        await self.validate_head(candidate.id, snapshot, observed)
        if (
            observed.get("baseRefName") != binding.target_branch
            or observed.get("headRefName") != branch
        ):
            raise ValidationError("PR branch identity mismatch")
        if observed.get("state") != "OPEN":
            raise ValidationError("Existing PR is closed or merged; human intervention required")
        old = await self.latest(PullRequestRecord, candidate.id)
        pr = PullRequestRecord(
            candidate_id=candidate.id,
            remote_binding_id=binding.id,
            pr_number=observed["number"],
            pr_id=observed.get("id"),
            pr_url=observed.get("url"),
            title=clean(observed["title"]),
            body=clean(observed["body"]),
            delivery_branch=branch,
            target_branch=binding.target_branch,
            head_sha=snapshot.integration_sha,
            base_sha=observed["baseRefOid"],
        )
        if old:
            pr = pr.model_copy(update={"id": old.id, "created_at": old.created_at})
        await self.repo.put(pr)
        return pr

    async def reconcile(
        self,
        operation: RemoteOperation,
        snapshot: DeliverySnapshot,
        evidence: dict,
        binding: RemoteRepositoryBinding,
        root: Path,
    ) -> dict | None:
        candidate = await self.repo.candidate(operation.candidate_id)
        if operation.operation_type == "push":
            head = await self.git.remote_sha(root, binding, evidence["delivery_branch"])
            if head == snapshot.integration_sha:
                if candidate.status in ("awaiting_remote_approval", "pushing"):
                    await self.state(candidate.id, "pr_open")
                return {"head_sha": head, "branch": evidence["delivery_branch"], "reconciled": True}
        elif operation.operation_type in ("pr_create", "pr_update"):
            observed = await self.github.find(root, binding, evidence["delivery_branch"])
            if observed:
                # Updating comments has its own idempotent marker, but uncertain writes
                # remain blocked until the report is observed; do not silently claim success.
                if operation.operation_type == "pr_update":
                    marker = f"<!-- agentmash:{candidate.id}:{snapshot.diff_hash} -->"
                    pages = await self.github.run(
                        root,
                        [
                            "api",
                            f"repos/{self.github.repo(binding)}/issues/{observed['number']}/comments",
                            "--paginate",
                            "--slurp",
                        ],
                    )
                    if not any(marker in c.get("body", "") for page in pages for c in page):
                        return None
                pr = await self.save_pr(
                    candidate, snapshot, binding, evidence["delivery_branch"], observed
                )
                return pr.model_dump(mode="json")
        elif operation.operation_type == "merge":
            pr = await self.require_pr(candidate.id)
            observed = await self.github.view(root, binding, cast(int, pr.pr_number))
            await self.validate_head(candidate.id, snapshot, observed)
            if observed.get("state") == "MERGED":
                return await self.record_merge(candidate, pr, binding, root, observed)
        elif operation.operation_type == "rollback":
            plan = await self.latest(RollbackPlan, candidate.id)
            if plan:
                observed = await self.github.find(root, binding, plan.revert_branch)
                if observed and plan.merge_commit_sha in observed.get("body", ""):
                    await self.repo.put(
                        plan.model_copy(
                            update={"status": "completed", "revert_pr_url": observed["url"]}
                        )
                    )
                    return {"revert_pr_url": observed["url"], "status": "revert_pr_open"}
        return None

    async def ci_status(
        self, candidate_id: str, *, force: bool = False
    ) -> builtins.list[CIWorkflowRun]:
        candidate, snapshot, _, binding, root = await self.context(candidate_id)
        if candidate.status == "rollback_proposed":
            await self.observe_rollback(candidate, binding, root)
        if candidate.status not in {
            "pr_open",
            "ci_running",
            "ci_failed",
            "awaiting_merge_approval",
        }:
            return await self.repo.records(CIWorkflowRun, candidate_id)
        now = asyncio.get_running_loop().time()
        if (
            not force
            and now - self._polled.get(candidate_id, -self.poll_seconds) < self.poll_seconds
        ):
            return await self.repo.records(CIWorkflowRun, candidate_id)
        pr = await self.require_pr(candidate_id)
        async with self.phase(candidate, "ci_monitoring"):
            observed = await self.github.view(root, binding, cast(int, pr.pr_number))
            await self.validate_head(candidate_id, snapshot, observed)
            if observed.get("state") != "OPEN":
                await self.state(candidate_id, "blocked")
                raise ValidationError(
                    "PR closed or merged outside the controlled operation; reconcile manually"
                )
            observed = await self.github.failure_logs(root, binding, observed)
            runs = ci_monitor.checks(pr, observed)
            await self.repo.replace_checks(candidate_id, runs)
            failed = [
                r
                for r in runs
                if r.status == "completed" and r.conclusion in ("failure", "cancelled", "timed_out")
            ]
            existing = {f.check_id for f in await self.repo.records(CIFailureFinding, candidate_id)}
            for check in failed:
                if check.id not in existing:
                    await self.repo.put(ci_monitor.finding(candidate_id, check, candidate.version))
            observations = await self.github.observe(root, binding)
            binding = binding.model_copy(update={**observations, "last_verified_at": utc_now()})
            await self.repo.save_binding(binding)
            required = binding.branch_protections.get("required_status_checks", [])
            status: DeliveryStatus = (
                "ci_failed"
                if failed
                else "awaiting_merge_approval"
                if ci_monitor.green(runs, required)
                else "ci_running"
            )
            await self.state(candidate_id, status)
            self._polled[candidate_id] = now
            await self.emit(
                EventType.DELIVERY_CI_UPDATED,
                candidate_id=candidate_id,
                pr_number=pr.pr_number,
                checks_summary={"status": status, "total": len(runs), "failed": len(failed)},
            )
            return runs

    async def perform_merge(
        self,
        candidate: DeliveryCandidate,
        snapshot: DeliverySnapshot,
        binding: RemoteRepositoryBinding,
        root: Path,
        method: str,
    ) -> dict:
        pr = await self.require_pr(candidate.id)
        observed = await self.github.view(root, binding, cast(int, pr.pr_number))
        await self.validate_head(candidate.id, snapshot, observed)
        if observed.get("state") != "OPEN" or observed.get("isDraft"):
            raise ValidationError("Only open, non-draft PRs may merge")
        observations = await self.github.observe(root, binding)
        protections = observations["branch_protections"]
        if method not in protections.get("merge_methods", []):
            raise ValidationError("Merge method is not allowed by repository")
        if method == "rebase":
            raise ValidationError(
                "Rebase merge cannot provide a single safe rollback commit; use squash or merge"
            )
        runs = ci_monitor.checks(pr, observed)
        if not ci_monitor.green(runs, protections.get("required_status_checks", [])):
            raise ValidationError("All required status checks must pass at approved head")
        if observed.get("reviewDecision") in ("CHANGES_REQUESTED", "REVIEW_REQUIRED"):
            raise ValidationError("Required PR reviews are not approved")
        if (
            protections.get("required_reviews", 0) > 0
            and observed.get("reviewDecision") != "APPROVED"
        ):
            raise ValidationError("Required reviews could not be verified")
        if observed.get("mergeStateStatus") != "CLEAN":
            raise ValidationError("Repository branch protections or mergeability block merge")
        await self.freshness(candidate, snapshot, binding, root)
        await self.state(candidate.id, "merging")
        observed = await self.github.merge(
            root, binding, cast(int, pr.pr_number), snapshot.integration_sha, method
        )
        if observed.get("state") != "MERGED":
            raise ValidationError("Merge queued or uncertain; reconcile before proceeding")
        await self.validate_head(candidate.id, snapshot, observed)
        return await self.record_merge(candidate, pr, binding, root, observed)

    async def record_merge(
        self,
        candidate: DeliveryCandidate,
        pr: PullRequestRecord,
        binding: RemoteRepositoryBinding,
        root: Path,
        observed: dict,
    ) -> dict:
        merge_sha = (observed.get("mergeCommit") or {}).get("oid")
        if not merge_sha:
            raise ValidationError("Merged PR has no observed merge SHA")
        await self.repo.put(pr.model_copy(update={"state": "merged", "updated_at": utc_now()}))
        current = await self.repo.candidate(candidate.id)
        if current.status == "merging":
            await self.state(candidate.id, "merged")
        async with self.phase(candidate, "post_merge"):
            target = await self.git.fetch(root, binding, binding.target_branch)
            passed = await self.git.ancestor(root, merge_sha, target)
            verification = PostMergeVerification(
                candidate_id=candidate.id,
                target_sha_observed=target,
                checks_run=[
                    {"name": "target_contains_merge", "passed": passed, "detail": merge_sha},
                    {
                        "name": "PR_merged",
                        "passed": observed.get("state") == "MERGED",
                        "detail": str(pr.pr_number),
                    },
                ],
                status="passed" if passed else "failed",
            )
            await self.repo.put(verification)
            if not passed:
                await self.state(candidate.id, "post_merge_failed")
            await self.missions.status(
                candidate.mission_id,
                "completed" if passed else "blocked",
                "Remote merge verified" if passed else "Post-merge verification failed",
                result=f"PR {pr.pr_number}; merge SHA {merge_sha}",
            )
        return {
            "merge_commit_sha": merge_sha,
            "target_sha": target,
            "post_merge": verification.status,
        }

    async def propose_rollback(self, candidate_id: str, reason: str) -> RollbackPlan:
        candidate, _, _, _, _ = await self.context(candidate_id)
        old = await self.latest(RollbackPlan, candidate_id)
        if old:
            return old
        if candidate.status not in ("merged", "post_merge_failed") or not reason.strip():
            raise ValidationError("Rollback requires a merged delivery and explicit reason")
        operations = await self.repo.records(RemoteOperation, candidate_id)
        merge = next(
            (o for o in operations if o.operation_type == "merge" and o.status == "completed"), None
        )
        if not merge or not merge.result:
            raise ValidationError("Verified merge record required")
        plan = RollbackPlan(
            candidate_id=candidate_id,
            merge_commit_sha=merge.result["merge_commit_sha"],
            revert_branch=f"agentmash/delivery-{candidate.id}-revert",
            status="awaiting_approval",
        )
        await self.repo.put(plan)
        await self.repo.put(
            InternalStep(
                candidate_id=candidate_id,
                name="rollback_proposal",
                status="completed",
                metadata={"reason": clean(reason)},
            )
        )
        await self.state(candidate_id, "rollback_proposed")
        return plan

    async def perform_rollback(
        self, candidate: DeliveryCandidate, binding: RemoteRepositoryBinding, root: Path
    ) -> dict:
        plan = await self.latest(RollbackPlan, candidate.id)
        if not plan:
            raise ValidationError("Rollback plan required")
        existing = await self.github.find(root, binding, plan.revert_branch)
        if existing:
            if plan.merge_commit_sha not in existing.get("body", ""):
                raise ValidationError("Revert branch PR is not owned by this rollback plan")
            if existing.get("state") == "MERGED":
                target = await self.git.fetch(root, binding, binding.target_branch)
                revert_merge = (existing.get("mergeCommit") or {}).get("oid")
                if not revert_merge or not await self.git.ancestor(root, revert_merge, target):
                    raise ValidationError("Revert merge not observed in target")
                await self.state(candidate.id, "rolled_back")
            await self.repo.put(
                plan.model_copy(update={"status": "completed", "revert_pr_url": existing["url"]})
            )
            return {
                "revert_pr_url": existing["url"],
                "status": "rolled_back" if existing.get("state") == "MERGED" else "revert_pr_open",
            }
        await self.repo.put(plan.model_copy(update={"status": "executing"}))
        path = root.parent / f"revert-{candidate.id}"
        head = await self.git.revert(root, binding, plan.merge_commit_sha, plan.revert_branch, path)
        await self.repo.put(
            InternalStep(
                candidate_id=candidate.id,
                name="revert_commit",
                status="completed",
                metadata={
                    "plan_id": plan.id,
                    "head_sha": head,
                    "merge_commit_sha": plan.merge_commit_sha,
                },
            )
        )
        if not await self.final_gates(candidate, path) or not await self.git.clean_tree(path):
            raise ValidationError("Revert quality gates failed")
        # Revert is itself scanned before its explicitly approved branch/PR is sent.
        target = await self.git.fetch(path, binding, binding.target_branch)
        raw = await self.git.evidence(path, target, head)
        snapshot, _ = await self.repo.snapshot(candidate.id)
        scan_snapshot = snapshot.model_copy(update={"base_sha": target, "integration_sha": head})
        findings, large, _ = await preflight.scan_evidence(self.git, path, scan_snapshot, raw)
        if findings or large:
            raise ValidationError("Revert secret/binary preflight failed")
        await self.git.push(path, binding, plan.revert_branch, head)
        observed = await self.github.create(
            path,
            binding,
            plan.revert_branch,
            f"Revert AgentMash delivery {candidate.id}",
            f"Revert merge {plan.merge_commit_sha}\nRollback plan {plan.id}\nHuman approval recorded. Requires protected PR merge.",
        )
        await self.repo.put(
            plan.model_copy(update={"status": "completed", "revert_pr_url": observed["url"]})
        )
        # Opening a revert PR does not mean target has been rolled back.
        return {
            "revert_pr_url": observed["url"],
            "revert_head_sha": head,
            "status": "revert_pr_open",
        }

    async def assign_fix(
        self, candidate_id: str, finding_id: str, agent_id: str | None = None
    ) -> CIFailureFinding:
        from core.missions.models import Choice, MissionPlan, PlannedTask
        from core.tasks.models import TaskStatus

        candidate, snapshot, evidence, binding, root = await self.context(candidate_id)
        findings = await self.repo.records(CIFailureFinding, candidate_id)
        failure = next((f for f in findings if f.id == finding_id), None)
        if failure is None:
            raise ValidationError("CI finding does not belong to candidate")
        if failure.status == "ready_for_push":
            return failure
        if failure.status != "analyzing" or candidate.status != "ci_failed":
            raise ValidationError("Correction already started; inspect recovery evidence")
        if candidate.version > self.max_fix_cycles:
            failure = failure.model_copy(update={"status": "exhausted"})
            await self.repo.put(failure)
            await self.state(candidate_id, "blocked")
            raise ValidationError("human_input_required: maximum CI correction cycles reached")
        mission = await self.missions.repo.get(Mission, candidate.mission_id)
        plans = await self.missions.repo.list(MissionPlan, mission.id)
        if not plans:
            raise ValidationError("Mission plan required for correction agent selection")
        pr = await self.require_pr(candidate_id)
        observation = await self.github.view(root, binding, cast(int, pr.pr_number))
        await self.validate_head(candidate_id, snapshot, observation)
        remote_head = await self.git.fetch(root, binding, evidence["delivery_branch"])
        if remote_head != snapshot.integration_sha:
            raise ValidationError("Correction must start at the approved PR head")
        worker = await self.missions.choose(mission, "worker")
        if agent_id:
            agent = await self.ctx.agents_repo.get(agent_id)
            if not agent:
                raise ValidationError("Requested correction agent not found")
            worker = Choice(
                agent_id=agent_id, role="worker", reason="Human CI correction assignment"
            )
        reviewer = await self.missions.choose(mission, "reviewer", {worker.agent_id})
        if worker.agent_id == reviewer.agent_id:
            raise ValidationError("Independent reviewer required")
        leader_choice = await self.missions.choose(mission, "leader")
        leader = await self.missions.new_session(mission, leader_choice)
        failure = failure.model_copy(
            update={"status": "fixing", "assigned_agent_id": worker.agent_id}
        )
        await self.repo.put(failure)
        await self.state(candidate_id, "fixing")
        checks = await self.repo.records(CIWorkflowRun, candidate_id)
        check = next(c for c in checks if c.id == failure.check_id)
        planned = PlannedTask(
            key=f"ci-{failure.id}",
            title=f"Fix CI: {check.name}"[:300],
            description=clean(
                f"Correct {failure.classification} in check {check.name} at {snapshot.integration_sha}.\n{check.logs_sanitized or 'Logs unavailable; reproduce the named failing check locally.'}"
            ),
            capabilities=["coding"],
            acceptance=[
                "Failing CI check passes",
                "Independent review approved",
                "Final quality gates pass",
            ],
        )
        project_root = Path(await self.missions.workspace(mission))
        async with self.phase(
            candidate,
            "ci_correction",
            agent_id=worker.agent_id,
            retries=candidate.version - 1,
            timeout_seconds=int(self.missions.session_timeout),
        ) as metrics:
            try:
                await self.missions.run_parallel_task(
                    mission,
                    plans[-1],
                    leader,
                    planned,
                    project_root,
                    snapshot.integration_sha,
                    worker,
                    reviewer,
                )
                source = await self.missions.repo.snapshot(mission.id)
                task = next(
                    t for t in reversed(source.tasks) if t.input.get("plan_key") == planned.key
                )
                wt = await self.ctx.parallel_repo.worktree_for_task(mission.id, task.id)
                if wt is None or task.status != TaskStatus.COMPLETED:
                    raise ValidationError("Correction task/review incomplete")
                failure = failure.model_copy(
                    update={
                        "assigned_task_id": task.id,
                        "worktree_path": wt.path,
                        "status": "reviewed",
                    }
                )
                await self.repo.put(failure)
                reviews = [r for r in source.reviews if r.task_id == task.id]
                if not reviews or reviews[-1].verdict != "approval":
                    raise ValidationError("Persisted independent correction review required")
                review = reviews[-1]
                sessions = {session.id: session for session in source.sessions}
                worker_session = sessions.get(review.worker_session_id)
                reviewer_session = sessions.get(review.reviewer_session_id)
                if (
                    not worker_session
                    or not reviewer_session
                    or worker_session.agent_id == reviewer_session.agent_id
                ):
                    raise ValidationError("Correction reviewer cannot approve own changes")
                metrics.update(
                    task_id=task.id,
                    session_id=worker_session.id,
                    provider_id=worker_session.provider_id,
                )
                correction_root = Path(wt.path)
                head = await self.git.head(correction_root)
                if not await self.git.ancestor(correction_root, snapshot.integration_sha, head):
                    raise ValidationError("Correction diverged from PR head")
                if not await self.final_gates(candidate, correction_root):
                    raise ValidationError("Correction quality gates failed")
                if (
                    not await self.git.clean_tree(correction_root)
                    or await self.git.head(correction_root) != head
                ):
                    raise ValidationError("Correction changed after review/gates")
                failure = failure.model_copy(update={"status": "gated"})
                await self.repo.put(failure)
                new = await self._freeze(
                    mission,
                    binding,
                    correction_root,
                    snapshot.base_sha,
                    head,
                    candidate.version + 1,
                    parent_id=candidate.id,
                )
                await self.repo.put(
                    InternalStep(
                        candidate_id=candidate.id,
                        name="correction_version",
                        status="completed",
                        metadata={"candidate_id": new.id, "task_id": task.id},
                    )
                )
                failure = failure.model_copy(update={"status": "ready_for_push"})
                await self.repo.put(failure)
                return failure
            except BaseException:
                source = await self.missions.repo.snapshot(mission.id)
                task = next(
                    (t for t in reversed(source.tasks) if t.input.get("plan_key") == planned.key),
                    None,
                )
                if task:
                    wt = await self.ctx.parallel_repo.worktree_for_task(mission.id, task.id)
                    failure = failure.model_copy(
                        update={
                            "assigned_task_id": task.id,
                            "worktree_path": wt.path if wt else None,
                        }
                    )
                    await self.repo.put(failure)
                    metrics["task_id"] = task.id
                    session = next(
                        (
                            s
                            for s in source.sessions
                            if s.task_id == task.id and s.agent_id == worker.agent_id
                        ),
                        None,
                    )
                    if session:
                        metrics.update(session_id=session.id, provider_id=session.provider_id)
                    if task.status != TaskStatus.COMPLETED:
                        await self.missions.repo.tasks.update_status(
                            task.id,
                            TaskStatus.WAITING,
                            waiting_reason="human_input_required: correction interrupted or failed; inspect delivery recovery",
                        )
                    await self.ctx.parallel_repo.release(mission_id=mission.id, task_id=task.id)
                await self.state(candidate_id, "blocked")
                raise

    async def observe_rollback(
        self, candidate: DeliveryCandidate, binding: RemoteRepositoryBinding, root: Path
    ) -> dict | None:
        plan = await self.latest(RollbackPlan, candidate.id)
        if not plan or not plan.revert_pr_url:
            return None
        observed = await self.github.find(root, binding, plan.revert_branch)
        if not observed or observed.get("state") != "MERGED":
            return None
        if plan.merge_commit_sha not in observed.get("body", ""):
            raise ValidationError("Rollback PR identity mismatch")
        evidence = [
            s
            for s in await self.repo.records(InternalStep, candidate.id)
            if s.name == "revert_commit" and s.metadata.get("plan_id") == plan.id
        ]
        if not evidence or observed.get("headRefOid") != evidence[-1].metadata.get("head_sha"):
            raise ValidationError("Revert PR head changed; human recovery required")
        head = (observed.get("mergeCommit") or {}).get("oid")
        target = await self.git.fetch(root, binding, binding.target_branch)
        if not head or not await self.git.ancestor(root, head, target):
            raise ValidationError("Revert merge not confirmed in target")
        await self.state(candidate.id, "rolled_back")
        return {
            "revert_pr_url": observed["url"],
            "revert_merge_sha": head,
            "target_sha": target,
            "status": "rolled_back",
        }
