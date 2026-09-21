from __future__ import annotations

import asyncio
import json
from typing import Any

from core.database.connection import Database
from core.delivery.models import (
    DeliveryCandidate,
    DeliverySnapshot,
    Record,
    RemoteOperation,
    RemoteRepositoryBinding,
)
from core.delivery.security import clean_data
from core.utils.errors import NotFoundError, ValidationError


class DeliveryRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.lock = asyncio.Lock()

    async def create(
        self, candidate: DeliveryCandidate, snapshot: DeliverySnapshot, evidence: dict[str, Any]
    ) -> None:
        if (
            snapshot.candidate_id != candidate.id
            or snapshot.id != candidate.current_snapshot_id
            or snapshot.version != candidate.version
            or snapshot.mission_id != candidate.mission_id
            or snapshot.project_id != candidate.project_id
        ):
            raise ValidationError("Snapshot identity mismatch")
        # No awaits to other repositories inside this atomic transaction.
        async with self.db.transaction() as conn:
            await conn.execute(
                "INSERT INTO delivery_candidates VALUES(?,?,?,?,?,?,?,?)",
                (
                    candidate.id,
                    candidate.mission_id,
                    candidate.project_id,
                    candidate.version,
                    candidate.status,
                    snapshot.id,
                    candidate.target_remote_binding_id,
                    candidate.model_dump_json(),
                ),
            )
            await conn.execute(
                "INSERT INTO delivery_snapshots VALUES(?,?,?,?)",
                (
                    snapshot.id,
                    candidate.id,
                    json.dumps(clean_data(snapshot.model_dump(mode="json"))),
                    json.dumps(clean_data(evidence)),
                ),
            )

    async def candidate(self, candidate_id: str) -> DeliveryCandidate:
        row = await self.db.fetch_one(
            "SELECT data FROM delivery_candidates WHERE id=?", (candidate_id,)
        )
        if row is None:
            raise NotFoundError("Delivery candidate not found")
        return DeliveryCandidate.model_validate_json(row["data"])

    async def candidates(
        self, project_id: str | None = None, mission_id: str | None = None
    ) -> list[DeliveryCandidate]:
        rows = await self.db.fetch_all(
            "SELECT data FROM delivery_candidates WHERE (? IS NULL OR project_id=?) "
            "AND (? IS NULL OR mission_id=?) ORDER BY version DESC",
            (project_id, project_id, mission_id, mission_id),
        )
        return [DeliveryCandidate.model_validate_json(r["data"]) for r in rows]

    async def save_candidate(self, value: DeliveryCandidate) -> None:
        await self.db.execute(
            "UPDATE delivery_candidates SET status=?,data=? WHERE id=?",
            (value.status, value.model_dump_json(), value.id),
        )

    async def snapshot(self, candidate_id: str) -> tuple[DeliverySnapshot, dict[str, Any]]:
        row = await self.db.fetch_one(
            "SELECT data,evidence FROM delivery_snapshots WHERE candidate_id=?", (candidate_id,)
        )
        if row is None:
            raise NotFoundError("Delivery snapshot not found")
        return DeliverySnapshot.model_validate_json(row["data"]), json.loads(row["evidence"])

    async def save_binding(self, value: RemoteRepositoryBinding) -> None:
        # Binding configuration versions are append-only; observations alone may change.
        await self.db.execute(
            "INSERT INTO delivery_bindings VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (value.id, value.project_id, value.model_dump_json()),
        )

    async def binding(
        self, *, project_id: str | None = None, binding_id: str | None = None
    ) -> RemoteRepositoryBinding:
        row = await self.db.fetch_one(
            "SELECT data FROM delivery_bindings WHERE "
            "(? IS NOT NULL AND id=?) OR (? IS NOT NULL AND project_id=?) ORDER BY rowid DESC LIMIT 1",
            (binding_id, binding_id, project_id, project_id),
        )
        if row is None:
            raise NotFoundError("Configure a remote repository binding first")
        return RemoteRepositoryBinding.model_validate_json(row["data"])

    async def put(self, value: Record) -> None:
        if isinstance(value, RemoteOperation):
            await self.db.execute(
                "INSERT INTO delivery_operations VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data",
                (
                    value.id,
                    value.candidate_id,
                    value.operation_type,
                    value.idempotency_key,
                    value.status,
                    value.model_dump_json(),
                ),
            )
        else:
            await self.db.execute(
                "INSERT INTO delivery_records VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (
                    value.id,
                    value.model_dump()["candidate_id"],
                    type(value).__name__,
                    json.dumps(clean_data(value.model_dump(mode="json"))),
                ),
            )

    async def records[T: Record](self, cls: type[T], candidate_id: str) -> list[T]:
        if cls is RemoteOperation:
            rows = await self.db.fetch_all(
                "SELECT data FROM delivery_operations WHERE candidate_id=? ORDER BY rowid",
                (candidate_id,),
            )
        else:
            rows = await self.db.fetch_all(
                "SELECT data FROM delivery_records WHERE candidate_id=? AND kind=? ORDER BY rowid",
                (candidate_id, cls.__name__),
            )
        return [cls.model_validate_json(r["data"]) for r in rows]

    async def operation(self, candidate_id: str, action: str, key: str) -> RemoteOperation | None:
        rows = await self.db.fetch_all(
            "SELECT data FROM delivery_operations WHERE idempotency_key=? OR (candidate_id=? AND operation_type=?)",
            (key, candidate_id, action),
        )
        for row in rows:
            value = RemoteOperation.model_validate_json(row["data"])
            if value.candidate_id != candidate_id or value.operation_type != action:
                raise ValidationError("Idempotency key already belongs to another operation")
        return RemoteOperation.model_validate_json(rows[0]["data"]) if rows else None

    async def replace_checks(self, candidate_id: str, checks) -> None:
        async with self.db.transaction() as conn:
            await conn.execute(
                "DELETE FROM delivery_records WHERE candidate_id=? AND kind='CIWorkflowRun'",
                (candidate_id,),
            )
            for check in checks:
                await conn.execute(
                    "INSERT INTO delivery_records VALUES(?,?,?,?)",
                    (check.id, candidate_id, "CIWorkflowRun", check.model_dump_json()),
                )

    async def claim(self, operation: RemoteOperation, *, retry: bool) -> bool:
        """Atomic cross-process claim, including retries of terminated attempts."""
        if retry:
            cursor = await self.db.execute(
                "UPDATE delivery_operations SET status='running',data=? WHERE id=? AND status='failed'",
                (operation.model_dump_json(), operation.id),
            )
        else:
            cursor = await self.db.execute(
                "INSERT OR IGNORE INTO delivery_operations VALUES(?,?,?,?,?,?)",
                (
                    operation.id,
                    operation.candidate_id,
                    operation.operation_type,
                    operation.idempotency_key,
                    operation.status,
                    operation.model_dump_json(),
                ),
            )
        return cursor.rowcount == 1
