"""Task lifecycle state machine.

Encodes every legal transition explicitly. A `completed` task can never go
back to `running` -- the only way to retry a finished unit of work is to
create a brand-new task/execution, which is itself an explicit, auditable
event rather than an implicit resurrection of old state.
"""

from __future__ import annotations

from core.tasks.models import TERMINAL_TASK_STATUSES, TaskStatus
from core.utils.errors import InvalidStateTransitionError

_ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {TaskStatus.WAITING, TaskStatus.REVIEWING, TaskStatus.COMPLETED, TaskStatus.PARTIAL,
         TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.WAITING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED}),
    TaskStatus.REVIEWING: frozenset(
        {TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.PARTIAL, TaskStatus.FAILED,
         TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.PARTIAL: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def is_terminal(status: TaskStatus) -> bool:
    return status in TERMINAL_TASK_STATUSES


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    if current == target:
        return False
    return target in _ALLOWED_TRANSITIONS.get(current, frozenset())


def assert_transition(current: TaskStatus, target: TaskStatus) -> None:
    if not can_transition(current, target):
        raise InvalidStateTransitionError(
            f"Cannot transition task from '{current.value}' to '{target.value}'.",
            details={"current": current.value, "target": target.value},
        )
