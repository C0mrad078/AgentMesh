from __future__ import annotations

from core.deployment.adapters.github_actions import sanitize
from core.deployment.models import ApprovalPolicy, DeploymentApproval, ReleaseCandidate
from core.deployment.policies import approvals_satisfied


def test_sanitize_redacts_bearer_and_private_github_tokens() -> None:
    token = "github_pat_" + "a" * 30
    value = sanitize(f"Authorization: Bearer {token}; token={token}")
    assert token not in value
    assert "[REDACTED]" in value


def test_production_approval_rejects_release_producer() -> None:
    release = ReleaseCandidate(project_id="p", delivery_candidate_id="dc", delivery_snapshot_id="ds", target_sha="a" * 40, created_by="producer")
    approval = DeploymentApproval(project_id="p", release_candidate_id=release.id, environment_id="prod", action="deploy_production", actor_id="producer", actor_role="release-manager", status="approved")
    assert not approvals_satisfied(release=release, environment="production", policy=ApprovalPolicy(min_approvals=1), approvals=[approval])
