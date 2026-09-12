"""Learning Policy: central, user-editable configuration the Learning
Engine consults before promoting, activating, or auto-applying anything.

Also implements the Learning Rate Limit ("não permita que o Orquestrador
modifique dezenas de regras depois de cada tarefa"): `LearningRateLimiter`
counts how many rule/prompt/playbook *activations* happened in the last 24h
(via `learning_events`) and refuses more once `max_changes_per_day` is hit
-- candidates can still be created and gain confidence, only the state
transition into something that changes live behavior is throttled.
"""

from __future__ import annotations

from datetime import timedelta

from core.database.repositories.learning_events_repo import LearningEventsRepository
from core.database.repositories.learning_policy_repo import LearningPolicyRepository
from core.learning.models import LearningMode, LearningPolicySettings
from core.utils.time import utc_now


def _settings_from_row(row: dict) -> LearningPolicySettings:
    return LearningPolicySettings(
        mode=LearningMode(row["mode"]),
        minimum_observations_for_activation=row["minimum_observations_for_activation"],
        minimum_confidence=row["minimum_confidence"],
        auto_apply_categories=tuple(row["auto_apply_categories"]),
        requires_approval_categories=tuple(row["requires_approval_categories"]),
        max_changes_per_day=row["max_changes_per_day"],
        rollback_threshold=row["rollback_threshold"],
    )


class LearningPolicyManager:
    def __init__(self, repository: LearningPolicyRepository) -> None:
        self._repository = repository

    async def get(self) -> LearningPolicySettings:
        return _settings_from_row(await self._repository.get())

    async def update(self, **kwargs: object) -> LearningPolicySettings:
        row = await self._repository.update(**kwargs)  # type: ignore[arg-type]
        return _settings_from_row(row)


class LearningRateLimiter:
    def __init__(self, events_repo: LearningEventsRepository) -> None:
        self._events = events_repo

    async def has_budget(self, policy: LearningPolicySettings) -> bool:
        since = (utc_now() - timedelta(days=1)).isoformat()
        count = await self._events.count_activations_since(since)
        return count < policy.max_changes_per_day
