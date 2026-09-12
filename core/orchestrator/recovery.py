"""Startup crash recovery.

If the previous process was killed (force-quit, crash, OS shutdown) while a
task/execution was in flight, no `ExecutionEngine` is around any more to
ever move it out of `running`. Left alone, that task would sit in an
impossible state forever and the desktop UI would show a spinner that can
never resolve. On every startup we scan for exactly that condition and
deterministically fail those rows with an explanatory result, before the
bridge starts accepting new requests.

Recovery never *resumes* an interrupted execution automatically -- doing so
could re-run partially-applied file/git operations a second time, which is
exactly the kind of silent double-action Stage 4's safety model forbids.
Every recovered row is marked `failed_interrupted` (a `RecoveryState`, not a
guess) and left for the user to review and re-submit if they still want the
work done; the previous step's had already-successful side effects (files
written, commits made) are not undone either, since we cannot know which of
them are safe to roll back without a `ChangeSet` for that specific run.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.database.repositories.executions_repo import ExecutionsRepository
from core.orchestrator.models import ExecutionStatus
from core.tasks.service import TaskService
from core.utils.logging import get_logger

logger = get_logger("orchestrator.recovery")


class RecoveryState(str, Enum):
    """Why a row was recovered -- surfaced in the error payload so the UI
    (and a human debugging a bug report) can tell "the app crashed mid-task"
    apart from "the user cancelled it", even though both ultimately land on
    a terminal, non-`running` status."""

    FAILED_INTERRUPTED = "failed_interrupted"


@dataclass(frozen=True)
class RecoveryReport:
    recovered_task_ids: list[str]
    recovered_execution_ids: list[str]


async def recover_interrupted_work(
    task_service: TaskService, executions_repo: ExecutionsRepository
) -> RecoveryReport:
    recovered_tasks = await task_service.recover_stale_tasks()

    stale_executions = await executions_repo.find_stale_running()
    recovered_execution_ids: list[str] = []
    for execution in stale_executions:
        await executions_repo.update_status(
            execution.id,
            ExecutionStatus.FAILED,
            completed=True,
            error={
                "reason": "Interrupted by application restart.",
                "recovery_state": RecoveryState.FAILED_INTERRUPTED.value,
            },
        )
        recovered_execution_ids.append(execution.id)

    if recovered_tasks or recovered_execution_ids:
        logger.warning(
            "recovered_interrupted_work",
            extra={
                "context": {
                    "task_ids": [t.id for t in recovered_tasks],
                    "execution_ids": recovered_execution_ids,
                }
            },
        )

    return RecoveryReport(
        recovered_task_ids=[t.id for t in recovered_tasks],
        recovered_execution_ids=recovered_execution_ids,
    )
