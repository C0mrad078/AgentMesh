from __future__ import annotations

import json

from core.database.connection import Database
from core.deployment.models import DeploymentRecoveryState
from core.utils.time import utc_now


async def reconcile_deployments(db: Database, project_id: str | None = None) -> DeploymentRecoveryState:
    now = utc_now().isoformat()
    await db.execute("UPDATE deployment_leases SET status='expired',released_at=? WHERE status='active' AND expires_at<=?", (now, now))
    query = "SELECT id FROM deployment_runs WHERE status IN ('leased','in_flight','verifying')"
    params: tuple[object, ...] = ()
    if project_id is not None:
        query += " AND project_id=?"
        params = (project_id,)
    rows = await db.fetch_all(query, params)
    for row in rows:
        row_data = await db.fetch_one("SELECT data FROM deployment_runs WHERE id=?", (row["id"],))
        data = json.loads(row_data["data"] or "{}") if row_data else {}
        data["status"] = "blocked"
        data["error_message"] = "Deployment state requires provider reconciliation"
        await db.execute("UPDATE deployment_runs SET status='blocked',data=?,updated_at=? WHERE id=? AND status IN ('leased','in_flight','verifying')", (json.dumps(data), now, row["id"]))
    leases = await db.fetch_all("SELECT environment_id,held_by_run_id,expires_at FROM deployment_leases WHERE status='active' AND expires_at>?", (now,))
    active = [dict(row) for row in leases]
    blocked = bool(rows)
    return DeploymentRecoveryState(is_blocked=blocked, recovery_reason="Remote provider reconciliation required" if blocked else None, suggested_action="Inspect provider status and reconcile each blocked run" if blocked else None, active_leases=active, reconciled_runs_count=len(rows))


async def mark_unknown_blocked(db: Database, run_id: str, reason: str = "Unknown provider state") -> bool:
    cursor = await db.execute("UPDATE deployment_runs SET status='blocked',error_message=?,updated_at=? WHERE id=? AND status NOT IN ('succeeded','failed','cancelled','blocked')", (reason, utc_now().isoformat(), run_id))
    return cursor.rowcount == 1
