from __future__ import annotations

import asyncio
import copy
import hashlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.database.repositories.delivery_repo import DeliveryRepository
from core.delivery.models import (
    CIFailureFinding,
    DeliveryApproval,
    DeliveryCandidate,
    DeliverySnapshot,
    InternalStep,
    RemoteOperation,
    RemoteRepositoryBindingInput,
)
from core.delivery.security import clean, ref, sanitize_url
from core.delivery.service import DeliveryService
from core.missions.models import Mission
from core.projects.models import ProjectCreate
from core.security.secret_store import InMemorySecretStore
from core.utils.errors import DatabaseError, ValidationError
from core.utils.time import utc_now

BASE = "a" * 40
HEAD = "b" * 40
MERGE = "c" * 40


class FakeGit:
    def __init__(self):
        self.current = HEAD
        self.target = BASE
        self.dirty = False
        self.heads = {}
        self.pushes = 0
        self.diff = '+print("delivery")\n'
        self.history = self.diff
        self.content = 'print("delivery")\n'
        self.binary = []
        self.size = len(self.content)
        self.valid_ancestry = True
        self.reverts = 0

    async def clean_tree(self, root):
        return not self.dirty

    async def head(self, root):
        return self.current

    async def ancestor(self, root, base, head):
        return self.valid_ancestry

    async def fetch(self, root, binding, branch):
        return self.target if branch == binding.target_branch else self.heads[branch]

    async def remote_sha(self, root, binding, branch):
        return self.heads.get(branch)

    async def push(self, root, binding, branch, head):
        self.pushes += 1
        self.heads[branch] = head
        return {"head_sha": head, "branch": branch}

    async def evidence(self, root, base, head):
        return {
            "diff": self.diff,
            "history": self.history,
            "diff_hash": hashlib.sha256(self.diff.encode()).hexdigest(),
            "commits": [
                {
                    "sha": head,
                    "message": "Delivery",
                    "author": "Test",
                    "timestamp": utc_now().isoformat(),
                }
            ],
            "files": [{"path": "app.py", "status": "added", "additions": 1, "deletions": 0}],
            "binary": self.binary,
        }

    async def blob(self, root, head, path):
        return self.size, self.content

    async def revert(self, root, binding, merge_sha, branch, path):
        self.reverts += 1
        return "d" * 40


class FakeGitHub:
    def __init__(self, git):
        self.git = git
        self.prs = {}
        self.creates = self.merges = self.updates = self.views = 0
        self.protections = {
            "required_status_checks": ["tests"],
            "merge_methods": ["squash", "merge"],
            "required_reviews": 1,
        }
        self.fail_observe = False

    async def failure_logs(self, root, binding, observed):
        return observed

    async def observe(self, root, binding):
        if self.fail_observe:
            raise ValidationError("Authentication unavailable")
        return {
            "auth_detected": True,
            "auth_type": "gh_cli",
            "permissions": ["pull", "push"],
            "branch_protections": self.protections,
        }

    async def find(self, root, binding, branch):
        return copy.deepcopy(self.prs.get(branch))

    async def create(self, root, binding, branch, title, body):
        if branch not in self.prs:
            self.creates += 1
            self.prs[branch] = dict(
                number=len(self.prs) + 1,
                id="PR_test",
                url="https://github.com/team/repo/pull/1",
                title=title,
                body=body,
                headRefOid=self.git.heads[branch],
                baseRefOid=self.git.target,
                headRefName=branch,
                baseRefName=binding.target_branch,
                state="OPEN",
                isCrossRepository=False,
                isDraft=False,
                mergeStateStatus="CLEAN",
                reviewDecision="APPROVED",
                statusCheckRollup=[
                    {"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}
                ],
                mergeCommit=None,
            )
        return copy.deepcopy(self.prs[branch])

    async def view(self, root, binding, number):
        self.views += 1
        pr = next(v for v in self.prs.values() if v["number"] == number)
        pr["headRefOid"] = self.git.heads[pr["headRefName"]]
        return copy.deepcopy(pr)

    async def merge(self, root, binding, number, head, method):
        self.merges += 1
        pr = next(v for v in self.prs.values() if v["number"] == number)
        assert pr["headRefOid"] == head
        pr.update(state="MERGED", mergeCommit={"oid": MERGE})
        self.git.target = MERGE
        return copy.deepcopy(pr)

    async def update(self, root, binding, number, marker, body):
        self.updates += 1
        return await self.view(root, binding, number)


@pytest_asyncio.fixture
async def delivery(tmp_path):
    ctx = await build_context(tmp_path / "delivery.db", secret_store=InMemorySecretStore())
    project = await ctx.project_service.create_project(ProjectCreate(name="Delivery"))
    mission = Mission(
        id="mission-delivery",
        project_id=project.id,
        request="Ship",
        status="completed",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    await ctx.mission_service.repo.put(mission, command_id="mission-test")
    git = FakeGit()
    github = FakeGitHub(git)
    service = DeliveryService(ctx, git=git, github=github)
    ctx.delivery_service = service
    binding = await service.binding_save(
        RemoteRepositoryBindingInput(
            project_id=project.id, provider="github", remote_url="https://github.com/team/repo.git"
        )
    )
    candidate = DeliveryCandidate(
        mission_id=mission.id,
        project_id=project.id,
        version=1,
        current_snapshot_id="snapshot-1",
        target_remote_binding_id=binding.id,
    )
    snapshot = DeliverySnapshot(
        id="snapshot-1",
        candidate_id=candidate.id,
        version=1,
        mission_id=mission.id,
        project_id=project.id,
        base_sha=BASE,
        integration_sha=HEAD,
        diff_hash=hashlib.sha256(git.diff.encode()).hexdigest(),
        commits=[],
        diff_stat={"files_changed": 1, "insertions": 1, "deletions": 0},
        tasks_summary=[],
        reviews_summary=[],
        resolved_conflicts_summary=[],
        quality_gates_summary=[],
        known_risks=[],
    )
    evidence = {
        "integration_path": str(tmp_path),
        "delivery_branch": "agentmash/delivery-mission-delivery",
        "diff_files": [],
        "parent_id": None,
    }
    await service.repo.create(candidate, snapshot, evidence)
    service.final_gates = AsyncMock(return_value=True)
    try:
        yield SimpleNamespace(
            ctx=ctx,
            service=service,
            git=git,
            github=github,
            candidate=candidate,
            snapshot=snapshot,
            binding=binding,
            evidence=evidence,
            mission=mission,
            root=tmp_path,
        )
    finally:
        await ctx.close()


async def approved_push(d):
    s, cid = d.service, d.candidate.id
    assert (await s.run_preflight(cid)).status == "passed"
    await s.approve(cid, "push", "approved", "human")
    return await s.execute(cid, "push", "push-1")


async def open_pr(d):
    await approved_push(d)
    await d.service.approve(d.candidate.id, "pr_create", "approved", "human")
    return await d.service.execute(d.candidate.id, "pr_create", "pr-1")


async def merge_pr(d):
    await open_pr(d)
    await d.service.ci_status(d.candidate.id)
    await d.service.approve(d.candidate.id, "merge", "approved", "human")
    return await d.service.execute(d.candidate.id, "merge", "merge-1")


def test_identifiers_urls_and_redaction():
    secret = "ghp_" + "x" * 30
    assert (
        sanitize_url(f"https://user:{secret}@github.com/team/repo.git?token={secret}")
        == "https://github.com/team/repo.git"
    )
    assert sanitize_url("git@github.com:team/repo.git") == "ssh://git@github.com/team/repo.git"
    assert secret not in clean(
        f"Error https://user:{secret}@github.com/team/repo?token={secret} Bearer {secret}"
    )
    for unsafe in ("--mirror", "foo..bar", "a//b", "a/.git", "a.lock", "x;touch /tmp/x"):
        with pytest.raises(ValidationError):
            ref(unsafe)
    for unsafe in (
        "file:///tmp/repo",
        "ext::sh x",
        "http://github.com/x/y",
        "https://github.com/../x",
        "https://github.com/x\ny",
    ):
        with pytest.raises(ValidationError):
            sanitize_url(unsafe)


async def test_snapshot_and_candidate_identity_immutable(delivery):
    d = delivery
    with pytest.raises(DatabaseError, match="immutable"):
        await d.ctx.db.execute(
            "UPDATE delivery_snapshots SET data=? WHERE id=?", ("{}", d.snapshot.id)
        )
    await d.ctx.db.connection.rollback()
    with pytest.raises(DatabaseError, match="immutable"):
        await d.ctx.db.execute("DELETE FROM delivery_snapshots WHERE id=?", (d.snapshot.id,))
    await d.ctx.db.connection.rollback()
    with pytest.raises(DatabaseError, match="immutable"):
        await d.service.repo.save_candidate(d.candidate.model_copy(update={"version": 2}))
    await d.ctx.db.connection.rollback()
    assert (await d.service.repo.snapshot(d.candidate.id))[0] == d.snapshot


@pytest.mark.parametrize(
    "failure",
    [
        "dirty",
        "head",
        "base",
        "ancestry",
        "gates",
        "auth",
        "secret",
        "history_secret",
        "binary",
        "large",
    ],
)
async def test_preflight_blocks_unsafe_delivery(delivery, failure):
    d = delivery
    secret = "ghp_" + "q" * 30
    if failure == "dirty":
        d.git.dirty = True
    if failure == "head":
        d.git.current = "e" * 40
    if failure == "base":
        d.git.target = "e" * 40
    if failure == "ancestry":
        d.git.valid_ancestry = False
    if failure == "gates":
        d.service.final_gates.return_value = False
    if failure == "auth":
        d.github.fail_observe = True
    if failure == "secret":
        d.git.content = secret
    if failure == "history_secret":
        d.git.history += secret
    if failure == "binary":
        d.git.binary = ["app.py"]
    if failure == "large":
        d.git.size = 2 * 1024 * 1024
    report = await d.service.run_preflight(d.candidate.id)
    assert report.status == "failed"
    assert secret not in report.model_dump_json()
    assert report.blocking_reasons
    with pytest.raises(ValidationError):
        await d.service.execute(d.candidate.id, "push", "unsafe")
    assert d.git.pushes == 0


async def test_approval_gates_idempotency_and_payload_collision(delivery):
    d = delivery
    await d.service.run_preflight(d.candidate.id)
    with pytest.raises(ValidationError, match="approval"):
        await d.service.execute(d.candidate.id, "push", "push-1")
    await d.service.approve(d.candidate.id, "push", "approved", "human")
    first = await d.service.execute(d.candidate.id, "push", "push-1")
    assert await d.service.execute(d.candidate.id, "push", "another-key") == first
    assert d.git.pushes == 1
    with pytest.raises(ValidationError, match="approval"):
        await d.service.execute(d.candidate.id, "pr_create", "pr-1")
    await d.service.approve(d.candidate.id, "pr_create", "approved", "human")
    with pytest.raises(ValidationError, match="Idempotency"):
        await d.service.execute(d.candidate.id, "pr_create", "push-1")
    first_pr = await d.service.execute(d.candidate.id, "pr_create", "pr-1")
    assert (await d.service.execute(d.candidate.id, "pr_create", "pr-1")).id == first_pr.id
    assert d.github.creates == 1


async def test_refreshed_preflight_invalidates_old_approval(delivery):
    d = delivery
    await d.service.run_preflight(d.candidate.id)
    await d.service.approve(d.candidate.id, "push", "approved", "human")
    await d.service.run_preflight(d.candidate.id)
    with pytest.raises(ValidationError, match="renew approval"):
        await d.service.execute(d.candidate.id, "push", "p")


async def test_approval_immutable_and_rejection_terminal(delivery):
    d = delivery
    await d.service.run_preflight(d.candidate.id)
    approval = await d.service.approve(d.candidate.id, "push", "rejected", "human", "not yet")
    assert (await d.service.repo.candidate(d.candidate.id)).status == "rejected"
    with pytest.raises(DatabaseError, match="immutable"):
        await d.service.repo.put(approval.model_copy(update={"decision": "approved"}))
    await d.ctx.db.connection.rollback()
    with pytest.raises(ValidationError):
        await d.service.execute(d.candidate.id, "push", "p")


@pytest.mark.parametrize(
    ("conclusion", "status", "classification"),
    [
        ("SUCCESS", "awaiting_merge_approval", None),
        ("FAILURE", "ci_failed", "test_failure"),
        ("CANCELLED", "ci_failed", "infra_error"),
        ("TIMED_OUT", "ci_failed", "timeout"),
        ("NEUTRAL", "ci_running", None),
        ("", "ci_running", None),
    ],
)
async def test_ci_state_classification_and_poll_throttle(
    delivery, conclusion, status, classification
):
    d = delivery
    await open_pr(d)
    pr = next(iter(d.github.prs.values()))
    pr["statusCheckRollup"][0]["conclusion"] = conclusion
    await d.service.ci_status(d.candidate.id)
    assert (await d.service.repo.candidate(d.candidate.id)).status == status
    findings = await d.service.repo.records(CIFailureFinding, d.candidate.id)
    assert (findings[0].classification if findings else None) == classification
    calls = d.github.views
    await d.service.ci_status(d.candidate.id)
    assert d.github.views == calls


async def test_missing_required_checks_cannot_pass(delivery):
    d = delivery
    await open_pr(d)
    d.github.protections["required_status_checks"] = ["tests", "security"]
    await d.service.ci_status(d.candidate.id)
    assert (await d.service.repo.candidate(d.candidate.id)).status == "ci_running"


@pytest.mark.parametrize("change", ["head", "checks", "review", "protection", "base", "method"])
async def test_merge_revalidates_remote_state(delivery, change):
    d = delivery
    await open_pr(d)
    await d.service.ci_status(d.candidate.id)
    await d.service.approve(d.candidate.id, "merge", "approved", "human")
    pr = next(iter(d.github.prs.values()))
    if change == "head":
        d.git.heads[pr["headRefName"]] = "e" * 40
    if change == "checks":
        pr["statusCheckRollup"][0]["conclusion"] = "FAILURE"
    if change == "review":
        pr["reviewDecision"] = "REVIEW_REQUIRED"
    if change == "protection":
        pr["mergeStateStatus"] = "BLOCKED"
    if change == "base":
        d.git.target = "e" * 40
    if change == "method":
        d.github.protections["merge_methods"] = ["merge"]
    with pytest.raises(ValidationError):
        await d.service.execute(d.candidate.id, "merge", "merge-1")
    assert d.github.merges == 0
    if change == "head":
        assert (await d.service.repo.candidate(d.candidate.id)).status == "blocked"


async def test_merge_post_merge_rollback_approval_and_idempotency(delivery):
    d = delivery
    merged = await merge_pr(d)
    assert merged.result["merge_commit_sha"] == MERGE
    assert (await d.service.detail(d.candidate.id))["post_merge"]["status"] == "passed"
    assert await d.service.execute(d.candidate.id, "merge", "merge-1") == merged
    assert d.github.merges == 1
    plan = await d.service.propose_rollback(d.candidate.id, "Regression")
    assert plan.strategy == "revert_pr"
    with pytest.raises(ValidationError, match="approval"):
        await d.service.execute(d.candidate.id, "rollback", "r")
    await d.service.approve(d.candidate.id, "rollback", "approved", "human")
    reverted = await d.service.execute(d.candidate.id, "rollback", "r")
    assert reverted.result["status"] == "revert_pr_open"
    assert (await d.service.repo.candidate(d.candidate.id)).status == "rollback_proposed"
    assert await d.service.execute(d.candidate.id, "rollback", "r") == reverted
    assert d.git.reverts == 1


async def test_restart_reconciles_push_without_repeat(delivery):
    d = delivery
    await d.service.run_preflight(d.candidate.id)
    await d.service.approve(d.candidate.id, "push", "approved", "human")
    operation = RemoteOperation(
        candidate_id=d.candidate.id,
        operation_type="push",
        idempotency_key="crash",
        payload_sanitized={"merge_method": "squash"},
        approved_by="human",
        status="running",
        attempts=1,
    )
    await d.service.repo.put(operation)
    await d.service.state(d.candidate.id, "pushing")
    await d.service.repo.put(
        InternalStep(candidate_id=d.candidate.id, name="remote_push", status="in_progress")
    )
    d.git.heads[d.evidence["delivery_branch"]] = HEAD
    restarted = DeliveryService(d.ctx, git=d.git, github=d.github)
    result = await restarted.execute(d.candidate.id, "push", "crash")
    assert result.status == "completed" and result.result["reconciled"]
    assert d.git.pushes == 0


async def test_uncertain_restart_fails_closed(delivery):
    d = delivery
    await d.service.run_preflight(d.candidate.id)
    await d.service.approve(d.candidate.id, "push", "approved", "human")
    await d.service.repo.put(
        RemoteOperation(
            candidate_id=d.candidate.id,
            operation_type="push",
            idempotency_key="crash",
            payload_sanitized={"merge_method": "squash"},
            approved_by="human",
            status="running",
            attempts=1,
        )
    )
    with pytest.raises(ValidationError, match="uncertain"):
        await d.service.execute(d.candidate.id, "push", "crash")
    assert d.git.pushes == 0


async def test_bridge_contract_unknown_telemetry_and_events(delivery):
    d = delivery
    events = []
    d.ctx.event_bus.subscribe(events.append)
    await approved_push(d)
    detail = await dispatch("delivery.candidate.get", {"candidate_id": d.candidate.id}, d.ctx)
    expected = {
        "candidate",
        "snapshot",
        "remote_binding",
        "preflight",
        "pull_request",
        "ci_runs",
        "ci_findings",
        "approvals",
        "pending_approvals",
        "remote_operations",
        "post_merge",
        "rollback_plan",
        "telemetry",
        "internal_steps",
        "recovery",
        "diff_files",
        "remote_sha",
    }
    assert expected <= detail.keys()
    assert detail["remote_operations"] == detail["operations"]
    assert detail["rollback"] == detail["rollback_plan"]
    telemetry = await dispatch("delivery.telemetry.list", {"candidate_id": d.candidate.id}, d.ctx)
    assert all(t["cost_usd"] == t["token_usage"] == "unknown" for t in telemetry)
    assert all(t["duration_ms"] >= 0 for t in telemetry)
    assert any(e.type.value == "delivery.operation_progress" for e in events)
    assert (
        await dispatch("delivery.candidate.list", {"project_id": d.candidate.project_id}, d.ctx)
    )[0]["remote_sha"] == HEAD


async def test_remote_binding_does_not_trust_auth_or_persist_credentials(delivery):
    d = delivery
    secret = "ghp_" + "u" * 30
    saved = await d.service.binding_save(
        RemoteRepositoryBindingInput(
            project_id=d.candidate.project_id,
            remote_url=f"https://name:{secret}@github.com/team/repo.git",
        )
    )
    assert not saved.auth_detected
    assert secret not in saved.model_dump_json()
    original = await d.service.repo.binding(binding_id=d.binding.id)
    assert original.id != saved.id


async def test_repository_foreign_keys_and_atomic_freeze(delivery):
    d = delivery
    repo = DeliveryRepository(d.ctx.db)
    bad_candidate = d.candidate.model_copy(
        update={"id": "bad", "version": 2, "current_snapshot_id": d.snapshot.id}
    )
    bad_snapshot = d.snapshot.model_copy(update={"candidate_id": "bad", "version": 2})
    with pytest.raises(sqlite3.IntegrityError):
        await repo.create(bad_candidate, bad_snapshot, {})
    assert len(await repo.candidates()) == 1


async def test_fix_iteration_limit(delivery):
    d = delivery
    # A fourth version is immutable; use a fresh row rather than mutating version.
    c = d.candidate.model_copy(
        update={"id": "fourth", "version": 4, "current_snapshot_id": "s4", "status": "ci_failed"}
    )
    s = d.snapshot.model_copy(update={"id": "s4", "candidate_id": c.id, "version": 4})
    await d.service.repo.create(c, s, d.evidence)
    f = CIFailureFinding(
        candidate_id=c.id, check_id="check", classification="test_failure", iteration=4
    )
    await d.service.repo.put(f)
    with pytest.raises(ValidationError, match="human_input_required"):
        await d.service.assign_fix(c.id, f.id)
    assert (await d.service.repo.records(CIFailureFinding, c.id))[0].status == "exhausted"
    assert (await d.service.repo.candidate(c.id)).status == "blocked"


async def test_no_required_gate_profile_is_not_success(delivery):
    with pytest.raises(ValidationError, match="profile"):
        await DeliveryService.final_gates(delivery.service, delivery.candidate, delivery.root)


async def test_real_worktree_correction_review_gates_and_new_snapshot(delivery, monkeypatch):
    """Real SQLite, Git/worktrees and mission worker/reviewer orchestration; fake remote/provider only."""
    import subprocess
    import sys

    from core.agents.models import Agent
    from core.delivery.git_remote import GitRemote
    from core.integration.models import QualityGateDefinition, QualityGateProfile
    from core.missions.models import Choice, MissionPlan, PlannedTask, ReviewOutput, WorkerOutput
    from core.parallel.models import HumanApproval, IntegrationAttempt, QualityGateRun
    from core.tasks.models import TaskCreate, TaskStatus

    d = delivery
    root = d.root / "project"
    root.mkdir()

    def git(path, *args):
        return subprocess.check_output(["git", *args], cwd=path, text=True).strip()

    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Delivery Test")
    git(root, "config", "user.email", "delivery@example.invalid")
    (root / "app.py").write_text("VALUE = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")
    base = git(root, "rev-parse", "HEAD")
    integration = d.service.missions.worktrees.root_for(root) / "integration"
    integration.parent.mkdir(parents=True)
    git(root, "worktree", "add", "-b", "agentmash/integration-test", str(integration), base)
    (integration / "app.py").write_text("VALUE = 2\n")
    git(integration, "add", ".")
    git(integration, "commit", "-m", "approved integration")
    head = git(integration, "rev-parse", "HEAD")

    class HybridGit(FakeGit):
        def __init__(self):
            super().__init__()
            self.local = GitRemote()
            self.target = base

        async def head(self, root):
            return await self.local.head(root)

        async def clean_tree(self, root):
            return await self.local.clean_tree(root)

        async def ancestor(self, root, base, head):
            return await self.local.ancestor(root, base, head)

        async def evidence(self, root, base, head):
            return await self.local.evidence(root, base, head)

        async def blob(self, root, head, path):
            return await self.local.blob(root, head, path)

    hybrid = HybridGit()
    github = FakeGitHub(hybrid)
    service = DeliveryService(d.ctx, git=hybrid, github=github)
    d.ctx.delivery_service = service
    ms = service.missions
    monkeypatch.setattr(ms, "workspace", AsyncMock(return_value=str(root)))
    mission = d.mission.model_copy(update={"id": "real-correction"})
    await ms.repo.put(mission, command_id="real-correction")
    task = await ms.repo.tasks.create(
        TaskCreate(project_id=mission.project_id, title="Initial integration")
    )
    await ms.repo.link("task", mission.id, task.id)
    await ms.repo.tasks.update_status(task.id, TaskStatus.COMPLETED)
    await d.ctx.parallel_repo.add_integration(
        IntegrationAttempt(
            id="integration-live",
            mission_id=mission.id,
            task_id=task.id,
            integration_branch="agentmash/integration-test",
            source_branch="source",
            base_sha=base,
            result="integrated",
            commit_sha=head,
            message="",
            created_at=utc_now(),
        )
    )
    await d.ctx.parallel_repo.add_gate(
        QualityGateRun(
            id="gate-live",
            mission_id=mission.id,
            name="initial tests",
            command=["python"],
            exit_code=0,
            duration_ms=1,
            summary="passed",
            passed=True,
            created_at=utc_now(),
        )
    )
    await d.ctx.parallel_repo.add_approval(
        HumanApproval(
            id="approved-live",
            mission_id=mission.id,
            decision="approved",
            rationale="Human integration approval",
            created_at=utc_now(),
        )
    )
    await d.ctx.integration_repo.save_profile(
        QualityGateProfile(
            id="profile-live",
            project_id=mission.project_id,
            name="Final tests",
            is_default=True,
            gates=[
                QualityGateDefinition(
                    id="compile",
                    name="Parse Python",
                    argv=[
                        sys.executable,
                        "-c",
                        "import ast,pathlib; ast.parse(pathlib.Path('app.py').read_text())",
                    ],
                )
            ],
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    for role in ("worker", "reviewer", "leader"):
        await d.ctx.agents_repo.upsert(
            Agent(id="delivery-" + role, name=role, provider="codex_cli")
        )
    choices = {
        role: Choice(agent_id="delivery-" + role, role=role, reason="test selection")
        for role in ("worker", "reviewer", "leader")
    }
    leader = await ms.new_session(mission, choices["leader"])
    plan = MissionPlan(
        id="plan-live",
        mission_id=mission.id,
        version=1,
        summary="Deliver",
        tasks=[
            PlannedTask(
                key="initial",
                title="Initial",
                description="Deliver",
                capabilities=["coding"],
                acceptance=["passes"],
            )
        ],
        leader_session_id=leader.id,
        choices=list(choices.values()),
        created_at=utc_now(),
    )
    await ms.repo.put(plan)
    monkeypatch.setattr(
        ms, "choose", AsyncMock(side_effect=lambda mission, role, *args, **kwargs: choices[role])
    )
    roles_called = []

    async def turn(mid, session, prompt, model, **kwargs):
        roles_called.append(session.agent_id)
        if model is WorkerOutput:
            current = await ms.repo.sessions.get_or_raise(session.id)
            await asyncio.to_thread(
                Path(current.metadata["workspace"], "app.py").write_text, "VALUE = 3\n"
            )
            return WorkerOutput(summary="CI corrected", files=["app.py"])
        assert model is ReviewOutput
        return ReviewOutput(verdict="approval", justification="Independent review passed")

    monkeypatch.setattr(ms, "turn", turn)
    detail = await service.create(mission.id, mission.project_id)
    cid = detail["candidate"]["id"]
    assert detail["snapshot"]["integration_sha"] == head
    assert (await service.create(mission.id, mission.project_id))["candidate"]["id"] == cid
    assert (await service.run_preflight(cid)).status == "passed"
    await service.approve(cid, "push", "approved", "human")
    await service.execute(cid, "push", "real-push")
    await service.approve(cid, "pr_create", "approved", "human")
    await service.execute(cid, "pr_create", "real-pr")
    pr = next(iter(github.prs.values()))
    pr["statusCheckRollup"][0]["conclusion"] = "FAILURE"
    await service.ci_status(cid)
    failure = (await service.repo.records(CIFailureFinding, cid))[0]
    fixed = await service.assign_fix(cid, failure.id)
    assert fixed.status == "ready_for_push"
    assert fixed.assigned_task_id and fixed.worktree_path
    assert roles_called == ["delivery-worker", "delivery-reviewer"]
    candidates = await service.repo.candidates(mission_id=mission.id)
    assert [c.version for c in candidates] == [2, 1]
    new = candidates[0]
    new_snapshot, _ = await service.repo.snapshot(new.id)
    old_snapshot, _ = await service.repo.snapshot(cid)
    assert new_snapshot.integration_sha != old_snapshot.integration_sha
    assert old_snapshot.integration_sha == head
    assert not await service.repo.records(DeliveryApproval, new.id)
    assert git(root, "rev-parse", "main") == base
    assert git(integration, "rev-parse", "HEAD") == head
    assert (await service.run_preflight(new.id)).status == "passed"
    await service.approve(new.id, "push", "approved", "human")
    await service.execute(new.id, "push", "fixed-push")
    await service.approve(new.id, "pr_update", "approved", "human")
    await service.execute(new.id, "pr_update", "fixed-pr")
    assert github.creates == 1 and github.updates == 1
    pr["statusCheckRollup"][0]["conclusion"] = "SUCCESS"
    await service.ci_status(new.id)
    assert (await service.repo.candidate(new.id)).status == "awaiting_merge_approval"
    assert await service.assign_fix(cid, failure.id) == fixed


async def test_failed_preflight_telemetry_is_failure(delivery):
    d = delivery
    d.git.dirty = True
    await d.service.run_preflight(d.candidate.id)
    telemetry = await d.service.telemetry(candidate_id=d.candidate.id)
    assert telemetry[-1].outcome == "failure"


async def test_rollback_only_finishes_when_revert_merge_observed(delivery):
    d = delivery
    await merge_pr(d)
    plan = await d.service.propose_rollback(d.candidate.id, "Regression")
    await d.service.approve(d.candidate.id, "rollback", "approved", "human")
    await d.service.execute(d.candidate.id, "rollback", "rollback")
    pr = d.github.prs[plan.revert_branch]
    pr.update(state="MERGED", mergeCommit={"oid": "e" * 40})
    result = await d.service.execute(d.candidate.id, "rollback", "rollback")
    assert result.result["status"] == "rolled_back"
    assert (await d.service.repo.candidate(d.candidate.id)).status == "rolled_back"
    assert d.git.reverts == 1


@pytest.mark.parametrize(
    ("command", "params"),
    [
        (
            "delivery.approval.submit",
            {"candidate_id": "c", "action": "merge", "decision": "approved", "actor": ""},
        ),
        ("delivery.remote.push", {"candidate_id": "c", "idempotency_key": "k", "force": True}),
        (
            "delivery.merge.execute",
            {"candidate_id": "c", "idempotency_key": "k", "merge_method": "admin"},
        ),
        ("delivery.candidate.list", {"project_id": ["bad"]}),
        (
            "delivery.binding.save",
            {
                "project_id": "p",
                "remote_url": "https://github.com/team/repo",
                "auth_detected": True,
            },
        ),
    ],
)
async def test_bridge_rejects_untrusted_evidence_and_bad_types(delivery, command, params):
    with pytest.raises(ValidationError, match="parameters"):
        await dispatch(command, params, delivery.ctx)


async def test_binding_configuration_cannot_mutate_under_approval(delivery):
    d = delivery
    with pytest.raises(DatabaseError, match="immutable"):
        await d.service.repo.save_binding(d.binding.model_copy(update={"target_branch": "other"}))
    await d.ctx.db.connection.rollback()
    assert (await d.service.repo.binding(binding_id=d.binding.id)).target_branch == "main"


async def test_pr_crash_reconciliation_without_duplicate(delivery):
    d = delivery
    await approved_push(d)
    await d.service.approve(d.candidate.id, "pr_create", "approved", "human")
    observed = await d.github.create(
        d.root, d.binding, d.evidence["delivery_branch"], "Delivery", "Report"
    )
    operation = RemoteOperation(
        candidate_id=d.candidate.id,
        operation_type="pr_create",
        idempotency_key="pr-crash",
        payload_sanitized={"merge_method": "squash"},
        approved_by="human",
        status="running",
        attempts=1,
    )
    await d.service.repo.put(operation)
    result = await DeliveryService(d.ctx, git=d.git, github=d.github).execute(
        d.candidate.id, "pr_create", "pr-crash"
    )
    assert result.result["pr_number"] == observed["number"]
    assert d.github.creates == 1


async def test_merge_crash_reconciliation_without_duplicate(delivery):
    d = delivery
    await open_pr(d)
    await d.service.ci_status(d.candidate.id)
    await d.service.approve(d.candidate.id, "merge", "approved", "human")
    await d.service.state(d.candidate.id, "merging")
    operation = RemoteOperation(
        candidate_id=d.candidate.id,
        operation_type="merge",
        idempotency_key="merge-crash",
        payload_sanitized={"merge_method": "squash"},
        approved_by="human",
        status="running",
        attempts=1,
    )
    await d.service.repo.put(operation)
    await d.github.merge(d.root, d.binding, 1, HEAD, "squash")
    result = await DeliveryService(d.ctx, git=d.git, github=d.github).execute(
        d.candidate.id, "merge", "merge-crash"
    )
    assert result.result["merge_commit_sha"] == MERGE
    assert (await d.service.repo.candidate(d.candidate.id)).status == "merged"
    assert d.github.merges == 1


async def test_concurrent_bridge_push_has_one_side_effect(delivery):
    d = delivery
    await d.service.run_preflight(d.candidate.id)
    await d.service.approve(d.candidate.id, "push", "approved", "human")
    params = {"candidate_id": d.candidate.id, "idempotency_key": "concurrent"}
    results = await asyncio.gather(
        *(dispatch("delivery.remote.push", params, d.ctx) for _ in range(5))
    )
    assert len({r["id"] for r in results}) == 1
    assert d.git.pushes == 1


async def test_no_merge_without_human_approval(delivery):
    d = delivery
    await open_pr(d)
    await d.service.ci_status(d.candidate.id)
    with pytest.raises(ValidationError, match="approval"):
        await d.service.execute(d.candidate.id, "merge", "merge-no-approval")
    assert d.github.merges == 0


async def test_terminated_push_retry_records_attempts_without_duplicate(delivery):
    d = delivery
    await d.service.run_preflight(d.candidate.id)
    await d.service.approve(d.candidate.id, "push", "approved", "human")
    original = d.git.push
    d.git.push = AsyncMock(side_effect=ValidationError("network unavailable"))
    with pytest.raises(ValidationError, match="network"):
        await d.service.execute(d.candidate.id, "push", "retry-push")
    operation = (await d.service.repo.records(RemoteOperation, d.candidate.id))[0]
    assert operation.status == "failed" and operation.attempts == 1
    d.git.push = original
    result = await d.service.execute(d.candidate.id, "push", "retry-push")
    assert result.status == "completed" and result.attempts == 2
    assert d.git.pushes == 1
    metrics = await d.service.telemetry(candidate_id=d.candidate.id)
    assert metrics[-1].retries == 1


async def test_failed_pr_response_is_reconciled_before_retry(delivery):
    d = delivery
    await approved_push(d)
    await d.service.approve(d.candidate.id, "pr_create", "approved", "human")
    original = d.github.create

    async def lost_response(*args):
        await original(*args)
        raise ValidationError("connection lost after response")

    d.github.create = lost_response
    with pytest.raises(ValidationError, match="connection"):
        await d.service.execute(d.candidate.id, "pr_create", "retry-pr")
    result = await d.service.execute(d.candidate.id, "pr_create", "retry-pr")
    assert result.status == "completed" and result.result["pr_number"] == 1
    assert d.github.creates == 1


async def test_cancelled_remote_mutation_stays_uncertain_and_recoverable(delivery):
    d = delivery
    await d.service.run_preflight(d.candidate.id)
    await d.service.approve(d.candidate.id, "push", "approved", "human")
    d.git.push = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await d.service.execute(d.candidate.id, "push", "cancelled")
    operation = (await d.service.repo.records(RemoteOperation, d.candidate.id))[0]
    assert operation.status == "running"
    assert "cancelled" in operation.error_sanitized
    assert (await d.service.detail(d.candidate.id))["recovery"]["is_blocked"]
    assert (await d.service.telemetry(candidate_id=d.candidate.id))[-1].outcome == "cancelled"
    with pytest.raises(ValidationError, match="uncertain"):
        await d.service.execute(d.candidate.id, "push", "cancelled")
    assert d.git.push.await_count == 1


async def test_cancelled_preflight_can_be_repeated(delivery):
    d = delivery
    d.service.final_gates.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await d.service.run_preflight(d.candidate.id)
    assert (await d.service.repo.candidate(d.candidate.id)).status == "preflight_failed"
    d.service.final_gates.side_effect = None
    assert (await d.service.run_preflight(d.candidate.id)).status == "passed"


@pytest.mark.parametrize(
    "command",
    [
        "delivery.preflight.run",
        "delivery.ci.assign_fix",
        "delivery.remote.push",
        "delivery.pr.create",
        "delivery.pr.update",
        "delivery.merge.execute",
        "delivery.rollback.execute",
    ],
)
def test_long_delivery_requests_have_bounded_extended_timeout(command):
    from core.bridge.server import request_timeout_seconds

    assert request_timeout_seconds(command) == 10800
    assert request_timeout_seconds("health.check") == 30
    assert request_timeout_seconds("delivery.candidate.get") == 30
    assert request_timeout_seconds("delivery.not_allowlisted") == 30


async def test_server_uses_extended_timeout_only_for_long_delivery(delivery, monkeypatch):
    import json

    from core.bridge import server
    from core.bridge.transport import StdioTransport

    lines = []
    transport = StdioTransport(write_line_fn=lines.append)
    bridge = server.BridgeServer(transport, "test-session", delivery.ctx)
    monkeypatch.setattr(server, "_REQUEST_TIMEOUT_SECONDS", 0.005)
    monkeypatch.setattr(server, "_DELIVERY_REQUEST_TIMEOUT_SECONDS", 1.0)

    async def slow_dispatch(*args):
        await asyncio.sleep(0.03)
        return {"status": "passed"}

    monkeypatch.setattr(server, "dispatch", slow_dispatch)
    for command in ("health.check", "delivery.preflight.run"):
        await bridge._handle_line(
            json.dumps(
                {
                    "id": command,
                    "type": "request",
                    "session": "test-session",
                    "command": command,
                    "params": {},
                }
            )
        )
    responses = [json.loads(line) for line in lines]
    assert responses[0]["error"]["code"] == "TIMEOUT"
    assert "0.005" in responses[0]["error"]["message"]
    assert responses[1]["ok"] is True
