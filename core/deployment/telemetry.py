from __future__ import annotations

from datetime import datetime

from core.database.connection import Database
from core.deployment.models import DeploymentInternalStep, DeploymentPhaseTelemetry
from core.utils.time import utc_now


class DeploymentTelemetry:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def start_phase(self, deployment_run_id: str, phase_name: str, *, queue_wait_ms: int | None = None, human_wait_ms: int | None = None) -> DeploymentPhaseTelemetry:
        value = DeploymentPhaseTelemetry(deployment_run_id=deployment_run_id, phase_name=phase_name, queue_wait_ms=queue_wait_ms, human_wait_ms=human_wait_ms, status="in_progress")
        await self.db.execute("INSERT INTO deployment_phase_telemetry(id,deployment_run_id,phase_name,duration_ms,queue_wait_ms,human_wait_ms,started_at,ended_at,status) VALUES(?,?,?,?,?,?,?,?,?)", (value.id, value.deployment_run_id, value.phase_name, None, value.queue_wait_ms, value.human_wait_ms, value.started_at.isoformat(), None, value.status))
        return value

    async def finish_phase(self, telemetry_id: str, *, status: str, ended_at: datetime | None = None) -> DeploymentPhaseTelemetry:
        end = ended_at or utc_now()
        row = await self.db.fetch_one("SELECT started_at FROM deployment_phase_telemetry WHERE id=?", (telemetry_id,))
        if row is None:
            raise ValueError("telemetry phase not found")
        start = datetime.fromisoformat(row["started_at"])
        duration = max(0, int((end - start).total_seconds() * 1000))
        await self.db.execute("UPDATE deployment_phase_telemetry SET ended_at=?,duration_ms=?,status=? WHERE id=?", (end.isoformat(), duration, status, telemetry_id))
        updated = await self.db.fetch_one("SELECT * FROM deployment_phase_telemetry WHERE id=?", (telemetry_id,))
        if updated is None:
            raise ValueError("telemetry phase disappeared")
        return DeploymentPhaseTelemetry(**dict(updated))

    async def add_step(self, value: DeploymentInternalStep) -> DeploymentInternalStep:
        await self.db.execute("INSERT INTO deployment_internal_steps(id,deployment_run_id,step_name,status,started_at,completed_at,metadata) VALUES(?,?,?,?,?,?,?)", (value.id, value.deployment_run_id, value.step_name, value.status, value.started_at.isoformat(), value.completed_at.isoformat() if value.completed_at else None, value.model_dump_json()))
        return value

    async def list_phases(self, deployment_run_id: str) -> list[DeploymentPhaseTelemetry]:
        rows = await self.db.fetch_all("SELECT * FROM deployment_phase_telemetry WHERE deployment_run_id=? ORDER BY started_at", (deployment_run_id,))
        return [DeploymentPhaseTelemetry(**dict(row)) for row in rows]
