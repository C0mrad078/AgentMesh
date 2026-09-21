from __future__ import annotations

from typing import Final

from core.deployment.models import ReleaseStatus
from core.utils.errors import InvalidStateTransitionError

RELEASE_STATES: Final[tuple[ReleaseStatus, ...]] = (
    "draft", "ready_for_predeploy", "predeploy_running", "predeploy_failed",
    "awaiting_development_approval", "deploying_development", "development_verification",
    "development_failed", "development_ready", "awaiting_staging_approval", "deploying_staging",
    "staging_verification", "staging_failed", "staging_ready", "awaiting_production_approval",
    "deploying_production", "production_verification", "production_failed", "production_healthy",
    "rollback_proposed", "awaiting_rollback_approval", "rolling_back", "rollback_verification",
    "rolled_back", "rollback_failed", "blocked", "cancelled",
)

TRANSITIONS: Final[dict[ReleaseStatus, frozenset[ReleaseStatus]]] = {
    "draft": frozenset({"ready_for_predeploy", "cancelled", "blocked"}),
    "ready_for_predeploy": frozenset({"predeploy_running", "cancelled", "blocked"}),
    "predeploy_running": frozenset({"predeploy_failed", "awaiting_development_approval", "blocked"}),
    "predeploy_failed": frozenset({"ready_for_predeploy", "cancelled", "blocked"}),
    "awaiting_development_approval": frozenset({"deploying_development", "cancelled", "blocked"}),
    "deploying_development": frozenset({"development_verification", "development_failed", "blocked"}),
    "development_verification": frozenset({"development_failed", "development_ready", "blocked"}),
    "development_failed": frozenset({"awaiting_development_approval", "cancelled", "blocked"}),
    "development_ready": frozenset({"awaiting_staging_approval", "blocked"}),
    "awaiting_staging_approval": frozenset({"deploying_staging", "cancelled", "blocked"}),
    "deploying_staging": frozenset({"staging_verification", "staging_failed", "blocked"}),
    "staging_verification": frozenset({"staging_failed", "staging_ready", "blocked"}),
    "staging_failed": frozenset({"awaiting_staging_approval", "cancelled", "blocked"}),
    "staging_ready": frozenset({"awaiting_production_approval", "blocked"}),
    "awaiting_production_approval": frozenset({"deploying_production", "cancelled", "blocked"}),
    "deploying_production": frozenset({"production_verification", "production_failed", "blocked"}),
    "production_verification": frozenset({"production_failed", "production_healthy", "blocked"}),
    "production_failed": frozenset({"rollback_proposed", "awaiting_production_approval", "cancelled", "blocked"}),
    "production_healthy": frozenset({"rollback_proposed", "blocked"}),
    "rollback_proposed": frozenset({"awaiting_rollback_approval", "cancelled", "blocked"}),
    "awaiting_rollback_approval": frozenset({"rolling_back", "cancelled", "blocked"}),
    "rolling_back": frozenset({"rollback_verification", "rollback_failed", "blocked"}),
    "rollback_verification": frozenset({"rollback_failed", "rolled_back", "blocked"}),
    "rolled_back": frozenset({"rollback_proposed", "blocked"}),
    "rollback_failed": frozenset({"rollback_proposed", "awaiting_rollback_approval", "blocked"}),
    "blocked": frozenset({"ready_for_predeploy", "awaiting_development_approval", "awaiting_staging_approval", "awaiting_production_approval", "awaiting_rollback_approval", "cancelled"}),
    "cancelled": frozenset(),
}


def can_transition(current: ReleaseStatus, target: ReleaseStatus) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def assert_transition(current: ReleaseStatus, target: ReleaseStatus) -> None:
    if current not in RELEASE_STATES or target not in RELEASE_STATES or not can_transition(current, target):
        raise InvalidStateTransitionError(f"Invalid deployment transition: {current} -> {target}")
