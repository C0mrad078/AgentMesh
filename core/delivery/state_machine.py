from core.delivery.models import DeliveryStatus
from core.utils.errors import ValidationError

TRANSITIONS: dict[str, set[str]] = {
    "draft": {"preflight_running"},
    "preflight_running": {"preflight_failed", "awaiting_remote_approval"},
    "preflight_failed": {"preflight_running"},
    "awaiting_remote_approval": {"preflight_running", "pushing", "pr_open"},
    "pushing": {"pr_open", "awaiting_remote_approval"},
    "pr_open": {"ci_running", "ci_failed", "awaiting_merge_approval"},
    "ci_running": {"ci_running", "ci_failed", "awaiting_merge_approval"},
    "ci_failed": {"ci_running", "fixing", "awaiting_merge_approval"},
    "fixing": {"ci_failed"},
    "awaiting_merge_approval": {"ci_running", "ci_failed", "merging"},
    "merging": {"merged"},
    "merged": {"post_merge_failed", "rollback_proposed"},
    "post_merge_failed": {"rollback_proposed"},
    "rollback_proposed": {"rolled_back"},
    "blocked": {"preflight_running"},
}


def validate_transition(current: DeliveryStatus, target: DeliveryStatus) -> None:
    if current == target:
        return
    if target in {"blocked", "cancelled", "rejected"} and current not in {
        "rolled_back",
        "cancelled",
        "rejected",
    }:
        return
    if target not in TRANSITIONS.get(current, set()):
        raise ValidationError(f"Invalid delivery transition: {current} → {target}")
