from __future__ import annotations

import json

import httpx
from core.deployment.adapters.github_actions import GitHubActionsAdapter, sanitize
from core.deployment.models import (
    ApprovalPolicy,
    DeploymentApproval,
    DeploymentBinding,
    ReleaseCandidate,
)
from core.deployment.policies import approvals_satisfied
from core.utils.errors import ValidationError


def test_sanitize_redacts_bearer_and_private_github_tokens() -> None:
    token = "github_pat_" + "a" * 30
    value = sanitize(f"Authorization: Bearer {token}; token={token}")
    assert token not in value
    assert "[REDACTED]" in value


def test_production_approval_rejects_release_producer() -> None:
    release = ReleaseCandidate(project_id="p", delivery_candidate_id="dc", delivery_snapshot_id="ds", target_sha="a" * 40, created_by="producer")
    approval = DeploymentApproval(project_id="p", release_candidate_id=release.id, environment_id="prod", action="deploy_production", actor_id="producer", actor_role="release-manager", status="approved")
    assert not approvals_satisfied(release=release, environment="production", policy=ApprovalPolicy(min_approvals=1), approvals=[approval])


async def test_dispatch_uses_branch_ref_and_passes_release_sha() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = request.read()
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.github.com")
    adapter = GitHubActionsAdapter("ghp_test", client=client)
    binding = DeploymentBinding(project_id="p", environment_id="e", remote_url="https://github.com/acme/app", repo_name="acme/app", workflow_file="deploy.yml", target_branch="main", environment_name="staging")
    sha = "a" * 40
    await adapter.dispatch(binding, sha, inputs={"environment": "staging", "ref": "release-branch"})
    await client.aclose()
    assert json.loads(seen["json"]) == {"ref": "release-branch", "inputs": {"release_sha": sha, "environment": "staging"}}


async def test_dispatch_rejects_invalid_sha_before_http() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(204)), base_url="https://api.github.com")
    adapter = GitHubActionsAdapter("ghp_test", client=client)
    binding = DeploymentBinding(project_id="p", environment_id="e", remote_url="https://github.com/acme/app", repo_name="acme/app", workflow_file="deploy.yml", environment_name="staging")
    try:
        await adapter.dispatch(binding, "not-a-sha")
    except ValidationError:
        pass
    else:
        raise AssertionError("invalid SHA should be rejected")
    await client.aclose()
