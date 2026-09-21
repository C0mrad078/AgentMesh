from __future__ import annotations

import aiosqlite

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.providers.runtime_bindings import RuntimeBinding, RuntimeBindingCreate
from core.utils.errors import NotFoundError
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row(row: aiosqlite.Row) -> RuntimeBinding:
    return RuntimeBinding(
        id=row["id"], provider_id=row["provider_id"], account_id=row["account_id"],
        label=row["label"], configured_capacity=row["configured_capacity"],
        observed_capacity=row["observed_capacity"], reserved_slots=row["reserved_slots"],
        health=row["health"], backoff_until=row["backoff_until"],
        metadata=loads(row["metadata"], {}), enabled=bool(row["enabled"]) if "enabled" in row.keys() else True,
        last_diagnostic=row["last_diagnostic"] if "last_diagnostic" in row.keys() else "",
        last_reconciled_at=row["last_reconciled_at"] if "last_reconciled_at" in row.keys() else None,
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


class RuntimeBindingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, binding_id: str) -> RuntimeBinding | None:
        row = await self._db.fetch_one("SELECT * FROM runtime_bindings WHERE id=?", (binding_id,))
        return _row(row) if row else None

    async def get_or_raise(self, binding_id: str) -> RuntimeBinding:
        value = await self.get(binding_id)
        if value is None:
            raise NotFoundError(f"Runtime binding '{binding_id}' not found.")
        return value

    async def list(self, provider_id: str | None = None) -> list[RuntimeBinding]:
        rows = await self._db.fetch_all(
            "SELECT * FROM runtime_bindings WHERE (? IS NULL OR provider_id=?) ORDER BY label",
            (provider_id, provider_id),
        )
        return [_row(row) for row in rows]

    async def create(self, data: RuntimeBindingCreate) -> RuntimeBinding:
        now = utc_now().isoformat()
        binding_id = new_id("runtime")
        await self._db.execute(
            "INSERT INTO runtime_bindings(id,provider_id,account_id,label,configured_capacity,observed_capacity,reserved_slots,health,metadata,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (binding_id, data.provider_id, data.account_id, data.label, data.configured_capacity,
             data.configured_capacity, 0, "unknown", dumps({}), now, now),
        )
        return await self.get_or_raise(binding_id)

    async def set_capacity(self, binding_id: str, configured: int, observed: int | None = None) -> RuntimeBinding:
        value = await self.get_or_raise(binding_id)
        now = utc_now().isoformat()
        await self._db.execute(
            "UPDATE runtime_bindings SET configured_capacity=?, observed_capacity=?, updated_at=? WHERE id=?",
            (configured, observed if observed is not None else min(configured, value.observed_capacity), now, binding_id),
        )
        return await self.get_or_raise(binding_id)

    async def set_enabled(self, binding_id: str, enabled: bool) -> RuntimeBinding:
        await self.get_or_raise(binding_id)
        await self._db.execute("UPDATE runtime_bindings SET enabled=?, updated_at=? WHERE id=?", (int(enabled), utc_now().isoformat(), binding_id))
        return await self.get_or_raise(binding_id)

    async def set_diagnostic(self, binding_id: str, diagnostic: str, *, health: str | None = None) -> RuntimeBinding:
        await self.get_or_raise(binding_id)
        if len(diagnostic) > 2000:
            diagnostic = diagnostic[:2000]
        await self._db.execute("UPDATE runtime_bindings SET last_diagnostic=?, health=COALESCE(?,health), last_reconciled_at=?, updated_at=? WHERE id=?", (diagnostic, health, utc_now().isoformat(), utc_now().isoformat(), binding_id))
        return await self.get_or_raise(binding_id)

    async def delete(self, binding_id: str) -> None:
        value = await self.get_or_raise(binding_id)
        active = await self._db.fetch_one("SELECT 1 FROM sessions WHERE runtime_binding_id=? AND status IN ('starting','working','waiting') LIMIT 1", (binding_id,))
        agents = await self._db.fetch_one("SELECT 1 FROM agents WHERE runtime_binding_id=? LIMIT 1", (binding_id,))
        if active or agents or value.reserved_slots:
            raise ValueError("Runtime binding has active sessions, agents, or reserved slots")
        await self._db.execute("DELETE FROM runtime_bindings WHERE id=?", (binding_id,))

    async def ensure_defaults(self) -> None:
        rows = await self._db.fetch_all("SELECT id,name,display_name FROM providers WHERE name IN ('openai','claude')")
        for row in rows:
            binding_id = f"runtime_{row['name']}_cli"
            now = utc_now().isoformat()
            await self._db.execute(
                "INSERT OR IGNORE INTO runtime_bindings(id,provider_id,label,configured_capacity,observed_capacity,reserved_slots,health,metadata,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (binding_id, row["id"], f"{row['display_name']} CLI", 4, 4, 0, "unknown", dumps({}), now, now),
            )

    async def reconcile_slots(self) -> None:
        await self._db.execute(
            "UPDATE runtime_bindings SET reserved_slots=(SELECT COUNT(*) FROM mission_concurrency_leases l WHERE l.runtime_binding_id=runtime_bindings.id AND l.expires_at >= datetime('now')), updated_at=?",
            (utc_now().isoformat(),),
        )
