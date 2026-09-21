from __future__ import annotations

from collections.abc import Iterable

from core.deployment.models import (
    ApprovalPolicy,
    DeploymentApproval,
    EnvironmentName,
    ReleaseCandidate,
)
from core.utils.errors import UnauthorizedError, ValidationError


def requires_approval(environment: EnvironmentName, policy: ApprovalPolicy) -> bool:
    return environment in {"staging", "production"} or policy.min_approvals > 0


def validate_release_origin(*, delivery_candidate_id: str, delivery_snapshot_id: str, target_sha: str, merged: bool) -> None:
    if not merged or not delivery_candidate_id or not delivery_snapshot_id:
        raise ValidationError("Release must originate from a merged delivery candidate and snapshot")
    if len(target_sha) != 40:
        raise ValidationError("Release target SHA must be a verified 40-character commit")


def validate_promotion_sha(release: ReleaseCandidate, promoted_sha: str) -> None:
    if promoted_sha.lower() != release.target_sha.lower():
        raise ValidationError("Promotion must use the exact release SHA")


def validate_approval(*, release: ReleaseCandidate, approval: DeploymentApproval, policy: ApprovalPolicy, existing: Iterable[DeploymentApproval] = ()) -> None:
    if approval.status != "approved":
        return
    if approval.actor_id == release.created_by and not policy.allow_same_author:
        raise UnauthorizedError("Release producer cannot approve this deployment")
    if policy.required_roles and approval.actor_role not in policy.required_roles:
        raise UnauthorizedError("Approval role is not authorized for this environment")
    prior = [item for item in existing if item.status == "approved" and item.actor_id == approval.actor_id]
    if prior and approval.action == "deploy_production" and policy.reinforced_production:
        raise UnauthorizedError("Reinforced production approval requires independent actors")


def approvals_satisfied(*, release: ReleaseCandidate, environment: EnvironmentName, policy: ApprovalPolicy, approvals: Iterable[DeploymentApproval]) -> bool:
    approved = [a for a in approvals if a.status == "approved"]
    if environment == "production" and release.created_by in {a.actor_id for a in approved}:
        return False
    if policy.required_roles and not all(any(a.actor_role == role for a in approved) for role in policy.required_roles):
        return False
    return len({a.actor_id for a in approved}) >= policy.min_approvals
