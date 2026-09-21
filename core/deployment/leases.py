from __future__ import annotations

from datetime import timedelta

from core.database.connection import Database
from core.deployment.models import EnvironmentLease
from core.utils.time import utc_now


class LeaseManager:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def acquire(self, environment_id: str, run_id: str, *, ttl_seconds: int = 3600) -> EnvironmentLease | None:
        now = utc_now()
        expires = now + timedelta(seconds=ttl_seconds)
        lease = EnvironmentLease(environment_id=environment_id, held_by_run_id=run_id, expires_at=expires)
        async with self.db.transaction() as conn:
            await conn.execute("UPDATE deployment_leases SET status='expired',released_at=? WHERE environment_id=? AND status='active' AND expires_at<=?", (now.isoformat(), environment_id, now.isoformat()))
            cursor = await conn.execute("INSERT OR IGNORE INTO deployment_leases(id,environment_id,lease_token,held_by_run_id,status,expires_at,acquired_at,released_at) VALUES(?,?,?,?,?,?,?,?)", (lease.id, lease.environment_id, lease.lease_token, lease.held_by_run_id, lease.status, lease.expires_at.isoformat(), lease.acquired_at.isoformat(), None))
            if cursor.rowcount != 1:
                return None
        return lease

    async def renew(self, lease_token: str, *, ttl_seconds: int = 3600) -> bool:
        now = utc_now()
        cursor = await self.db.execute("UPDATE deployment_leases SET expires_at=? WHERE lease_token=? AND status='active' AND expires_at>?", ((now + timedelta(seconds=ttl_seconds)).isoformat(), lease_token, now.isoformat()))
        return cursor.rowcount == 1

    async def release(self, lease_token: str) -> bool:
        cursor = await self.db.execute("UPDATE deployment_leases SET status='released',released_at=? WHERE lease_token=? AND status='active'", (utc_now().isoformat(), lease_token))
        return cursor.rowcount == 1

    async def reclaim_expired(self) -> int:
        cursor = await self.db.execute("UPDATE deployment_leases SET status='expired',released_at=? WHERE status='active' AND expires_at<=?", (utc_now().isoformat(), utc_now().isoformat()))
        return cursor.rowcount

    async def active(self, environment_id: str) -> EnvironmentLease | None:
        row = await self.db.fetch_one("SELECT * FROM deployment_leases WHERE environment_id=? AND status='active' AND expires_at>? ORDER BY acquired_at DESC LIMIT 1", (environment_id, utc_now().isoformat()))
        return EnvironmentLease(**dict(row)) if row else None
