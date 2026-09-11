"""Task service: enforces the lifecycle state machine around the repository."""

from __future__ import annotations

from core.database.repositories.tasks_repo import TasksRepository
from core.tasks.models import Task, TaskCreate, TaskStatus
from core.tasks.state_machine import assert_transition
from core.utils.errors import ValidationError
from core.utils.time import utc_now


class TaskService:
    def __init__(self, repository: TasksRepository) -> None:
        self._repository = repository

    async def create_task(self, data: TaskCreate) -> Task:
        return await self._repository.create(data)

    async def get_task(self, task_id: str) -> Task:
        return await self._repository.get_or_raise(task_id)

    async def list_tasks(self, project_id: str) -> list[Task]:
        return await self._repository.list_for_project(project_id)

    async def transition(
        self, task_id: str, target: TaskStatus, *, result: dict | None = None
    ) -> Task:
        current = await self._repository.get_or_raise(task_id)
        assert_transition(current.status, target)

        now_iso = utc_now().isoformat()
        started_at = now_iso if target == TaskStatus.RUNNING and current.started_at is None else None
        completed_at = (
            now_iso
            if target in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            else None
        )
        return await self._repository.update_status(
            task_id, target, result=result, started_at=started_at, completed_at=completed_at
        )

    async def cancel_task(self, task_id: str) -> Task:
        """Cancel a task that has not started running yet.

        Once a task is `running` (or `waiting`/`reviewing`), there is a live
        `ExecutionEngine` actually doing work for it; force-flipping the
        task row to `cancelled` here would race with that engine's own
        terminal transition and would not actually stop anything in
        flight -- it would just make the status lie. Real cancellation of
        in-flight work is `execution.cancel` (`ExecutionEngine.request_cancel`),
        which the engine itself observes cooperatively and reflects back onto
        the task once it has actually stopped. This method only covers the
        case where there is nothing running yet to interrupt.
        """
        task = await self._repository.get_or_raise(task_id)
        if task.status != TaskStatus.QUEUED:
            raise ValidationError(
                f"Task '{task_id}' is '{task.status.value}', not 'queued'. "
                "Cancel the running execution instead via execution.cancel.",
            )
        return await self.transition(task_id, TaskStatus.CANCELLED)

    async def recover_stale_tasks(self) -> list[Task]:
        """Startup recovery: any task left `running`/`waiting`/`reviewing` from a
        previous process (crash, force-quit) has no execution loop still
        driving it, so it can never legitimately finish on its own. It is
        deterministically marked `failed` with an explanatory result rather
        than left inconsistent or silently resumed with stale state.
        """
        stale = await self._repository.find_stale_running()
        recovered: list[Task] = []
        for task in stale:
            updated = await self.transition(
                task.id,
                TaskStatus.FAILED,
                result={"recovered": True, "reason": "Interrupted by application restart."},
            )
            recovered.append(updated)
        return recovered
