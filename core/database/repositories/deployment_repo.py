from __future__ import annotations

from typing import Any, TypeVar, cast

from core.database.connection import Database
from core.deployment.models import (
    DeploymentApproval,
    DeploymentAttempt,
    DeploymentEnvironment,
    DeploymentOperation,
    DeploymentRun,
    ReleaseCandidate,
    ReleaseSnapshot,
)
from core.utils.errors import NotFoundError, ValidationError

T = TypeVar("T")


class DeploymentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save_environment(self, value: DeploymentEnvironment) -> DeploymentEnvironment:
        await self.db.execute("INSERT INTO deployment_environments(id,project_id,name,display_name,provider,remote_identifier,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,remote_identifier=excluded.remote_identifier,data=excluded.data,updated_at=excluded.updated_at", (value.id,value.project_id,value.name,value.display_name,value.provider,value.remote_identifier,value.model_dump_json(),value.created_at.isoformat(),value.updated_at.isoformat()))
        return value

    async def environments(self, project_id: str) -> list[DeploymentEnvironment]:
        rows = await self.db.fetch_all("SELECT data FROM deployment_environments WHERE project_id=? ORDER BY name", (project_id,))
        return [DeploymentEnvironment.model_validate_json(row["data"]) for row in rows]

    async def save_release(self, release: ReleaseCandidate, snapshot: ReleaseSnapshot) -> None:
        if snapshot.release_candidate_id != release.id or snapshot.target_sha.lower() != release.target_sha.lower() or snapshot.version != release.version:
            raise ValidationError("Release snapshot identity mismatch")
        async with self.db.transaction() as conn:
            await conn.execute("INSERT INTO release_candidates(id,project_id,delivery_candidate_id,snapshot_id,version,target_sha,status,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (release.id,release.project_id,release.delivery_candidate_id,release.delivery_snapshot_id,release.version,release.target_sha,release.status,release.model_dump_json(),release.created_at.isoformat(),release.updated_at.isoformat()))
            await conn.execute("INSERT INTO release_snapshots(id,release_candidate_id,version,target_sha,artifacts_hash,data,created_at) VALUES(?,?,?,?,?,?,?)", (snapshot.id,snapshot.release_candidate_id,snapshot.version,snapshot.target_sha,snapshot.artifacts_hash,snapshot.model_dump_json(),snapshot.created_at.isoformat()))

    async def release(self, release_id: str) -> ReleaseCandidate:
        row = await self.db.fetch_one("SELECT data FROM release_candidates WHERE id=?", (release_id,))
        if row is None:
            raise NotFoundError("Release candidate not found")
        return ReleaseCandidate.model_validate_json(row["data"])

    async def snapshot(self, release_id: str) -> ReleaseSnapshot:
        row = await self.db.fetch_one("SELECT data FROM release_snapshots WHERE release_candidate_id=?", (release_id,))
        if row is None:
            raise NotFoundError("Release snapshot not found")
        return ReleaseSnapshot.model_validate_json(row["data"])

    async def save_run(self, value: DeploymentRun) -> DeploymentRun:
        await self.db.execute("INSERT INTO deployment_runs(id,project_id,release_candidate_id,environment_id,target_sha,status,idempotency_key,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data,updated_at=excluded.updated_at", (value.id,value.project_id,value.release_candidate_id,value.environment_id,value.target_sha,value.status,value.idempotency_key,value.model_dump_json(),value.created_at.isoformat(),value.updated_at.isoformat()))
        return value

    async def run_by_idempotency(self, key: str) -> DeploymentRun | None:
        row = await self.db.fetch_one("SELECT data FROM deployment_runs WHERE idempotency_key=?", (key,))
        return DeploymentRun.model_validate_json(row["data"]) if row else None

    async def put(self, value: Any) -> None:
        table = {DeploymentAttempt: "deployment_attempts", DeploymentOperation: "deployment_operations", DeploymentApproval: "deployment_approvals"}.get(cast(Any, type(value)))
        if table is None:
            raise TypeError(f"unsupported deployment record: {type(value).__name__}")
        data = value.model_dump_json()
        if isinstance(value, DeploymentAttempt):
            await self.db.execute("INSERT INTO deployment_attempts(id,deployment_run_id,attempt_number,data) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (value.id,value.deployment_run_id,value.attempt_number,data))
        elif isinstance(value, DeploymentOperation):
            await self.db.execute("INSERT INTO deployment_operations(id,deployment_run_id,idempotency_key,operation_type,status,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data,updated_at=excluded.updated_at", (value.id,value.deployment_run_id,value.idempotency_key,value.operation_type,value.status,data,value.created_at.isoformat(),value.updated_at.isoformat()))
        else:
            await self.db.execute("INSERT INTO deployment_approvals(id,project_id,release_candidate_id,environment_id,action,status,actor_id,data,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (value.id,value.project_id,value.release_candidate_id,value.environment_id,value.action,value.status,value.actor_id,data,value.created_at.isoformat()))

    async def records(self, cls: type[T], run_id: str) -> list[T]:
        table = {DeploymentAttempt: "deployment_attempts", DeploymentOperation: "deployment_operations"}.get(cast(Any, cls))
        if table is None:
            raise TypeError("unsupported deployment record")
        rows = await self.db.fetch_all(f"SELECT data FROM {table} WHERE deployment_run_id=? ORDER BY rowid", (run_id,))
        return [cast(Any, cls).model_validate_json(row["data"]) for row in rows]
