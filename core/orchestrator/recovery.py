"""Startup crash recovery.

If the previous process was killed (force-quit, crash, OS shutdown) while a
task/execution was in flight, no `ExecutionEngine` is around any more to
ever move it out of `running`. Left alone, that task would sit in an
impossible state forever and the desktop UI would show a spinner that can
never resolve. On every startup we scan for exactly that condition and
deterministically fail those rows with an explanatory result, before the
bridge starts accepting new requests.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.database.repositories.executions_repo import ExecutionsRepository
from core.orchestrator.models import ExecutionStatus
from core.tasks.service import TaskService
from core.utils.logging import get_logger

logger = get_logger("orchestrator.recovery")


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
            error={"reason": "Interrupted by application restart."},
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
