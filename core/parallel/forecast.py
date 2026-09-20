from __future__ import annotations

from core.missions.models import PlannedTask
from core.parallel.models import ConflictForecast, ForecastLevel
from core.utils.ids import new_id
from core.utils.time import utc_now


def forecast(mission_id: str, tasks: list[PlannedTask]) -> list[ConflictForecast]:
    result: list[ConflictForecast] = []
    for index, left in enumerate(tasks):
        for right in tasks[index + 1:]:
            paths_left = set(getattr(left, "expected_paths", []))
            paths_right = set(getattr(right, "expected_paths", []))
            overlap = sorted(paths_left & paths_right)
            if overlap:
                level = ForecastLevel.CONFIRMED
                reason = "As áreas declaradas pelo plano se sobrepõem."
            elif paths_left and paths_right and any(
                a.split("/", 1)[0] == b.split("/", 1)[0] for a in paths_left for b in paths_right
            ):
                level = ForecastLevel.LIKELY
                reason = "As tarefas compartilham uma área superior do repositório."
            elif paths_left or paths_right:
                level = ForecastLevel.POSSIBLE
                reason = "A sobreposição só poderá ser confirmada pelo diff real."
            else:
                level = ForecastLevel.POSSIBLE
                reason = "O plano não declarou áreas; o diff real será a fonte de confirmação."
            result.append(ConflictForecast(
                id=new_id("forecast"), mission_id=mission_id, task_id=left.key,
                other_task_id=right.key, level=level, paths=overlap, reason=reason,
                created_at=utc_now(),
            ))
    return result
