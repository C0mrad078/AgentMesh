"""Optional scoped process observations; lifecycle remains in ShellRunner."""
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessObservation:
    kind: str
    pid: int | None = None
    line: str = ''


process_observer: ContextVar[Callable[[ProcessObservation], Awaitable[None]] | None] = ContextVar(
    'process_observer', default=None)


async def observe(value: ProcessObservation) -> None:
    callback = process_observer.get()
    if callback:
        await callback(value)
