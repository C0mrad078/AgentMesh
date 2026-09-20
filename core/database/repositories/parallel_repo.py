from __future__ import annotations

import asyncio
from typing import Any

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.parallel.models import (
    ConcurrencyLease,
    ConflictForecast,
    HumanApproval,
    IntegrationAttempt,
    QualityGateRun,
    WorktreeLease,
)
from core.utils.errors import ValidationError
from core.utils.time import utc_now


class ParallelRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._lease_lock = asyncio.Lock()

    async def create_worktree(self, value: WorktreeLease) -> WorktreeLease:
        await self.db.execute(
            """INSERT INTO worktrees
            (id,project_id,branch_name,path,status,created_at,updated_at,mission_id,task_id,session_id,
             workspace_root,base_sha,head_sha,last_error)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (value.id, value.project_id, value.branch_name, value.path, value.status,
             value.created_at.isoformat(), value.updated_at.isoformat(), value.mission_id,
             value.task_id, value.session_id, value.workspace_root, value.base_sha,
             value.head_sha, value.last_error),
        )
        return value

    async def worktree_for_task(self, mission_id: str, task_id: str) -> WorktreeLease | None:
        row = await self.db.fetch_one(
            "SELECT * FROM worktrees WHERE mission_id=? AND task_id=?", (mission_id, task_id))
        if row is None:
            return None
        return WorktreeLease(
            id=row["id"], mission_id=row["mission_id"], task_id=row["task_id"],
            session_id=row["session_id"], project_id=row["project_id"],
            workspace_root=row["workspace_root"], path=row["path"],
            branch_name=row["branch_name"], base_sha=row["base_sha"],
            head_sha=row["head_sha"], status=row["status"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            last_error=row["last_error"],
        )

    async def list_worktrees(self, mission_id: str) -> list[WorktreeLease]:
        rows = await self.db.fetch_all(
            "SELECT * FROM worktrees WHERE mission_id=? ORDER BY task_id", (mission_id,))
        result = []
        for row in rows:
            value = await self.worktree_for_task(mission_id, row["task_id"])
            if value:
                result.append(value)
        return result

    async def update_worktree(self, worktree_id: str, **patch: Any) -> None:
        allowed = {"session_id", "status", "head_sha", "last_error"}
        if set(patch) - allowed:
            raise ValidationError("Campo de worktree não permitido")
        if not patch:
            return
        assignments = ", ".join(f"{key}=?" for key in patch)
        await self.db.execute(
            f"UPDATE worktrees SET {assignments}, updated_at=? WHERE id=?",
            (*patch.values(), utc_now().isoformat(), worktree_id),
        )

    async def replace_forecasts(self, mission_id: str, values: list[ConflictForecast]) -> None:
        await self.db.execute("DELETE FROM mission_conflict_forecasts WHERE mission_id=?", (mission_id,))
        for value in values:
            await self.db.execute(
                "INSERT INTO mission_conflict_forecasts(id,mission_id,task_id,other_task_id,data,created_at) VALUES(?,?,?,?,?,?)",
                (value.id, value.mission_id, value.task_id, value.other_task_id,
                 value.model_dump_json(), value.created_at.isoformat()),
            )

    async def forecasts(self, mission_id: str) -> list[ConflictForecast]:
        rows = await self.db.fetch_all(
            "SELECT data FROM mission_conflict_forecasts WHERE mission_id=? ORDER BY id", (mission_id,))
        return [ConflictForecast.model_validate_json(row["data"]) for row in rows]

    async def acquire(self, value: ConcurrencyLease, *, limits: dict[str, int]) -> bool:
        async with self._lease_lock:
            return await self._acquire(value, limits=limits)

    async def _acquire(self, value: ConcurrencyLease, *, limits: dict[str, int]) -> bool:
        now = utc_now().isoformat()
        await self.db.execute("DELETE FROM mission_concurrency_leases WHERE expires_at < ?", (now,))
        counts = {
            "global": "SELECT COUNT(*) AS n FROM mission_concurrency_leases",
            "provider": "SELECT COUNT(*) AS n FROM mission_concurrency_leases WHERE provider=?",
            "runtime_binding": "SELECT COUNT(*) AS n FROM mission_concurrency_leases WHERE runtime_binding_id=?",
            "project": "SELECT COUNT(*) AS n FROM mission_concurrency_leases WHERE project_id=?",
            "mission": "SELECT COUNT(*) AS n FROM mission_concurrency_leases WHERE mission_id=?",
        }
        params = {"global": (), "provider": (value.provider,), "runtime_binding": (value.runtime_binding_id,), "project": (value.project_id,),
                  "mission": (value.mission_id,)}
        scopes = {k: v for k, v in counts.items() if k != "runtime_binding" or value.runtime_binding_id is not None}
        for scope, sql in scopes.items():
            row = await self.db.fetch_one(sql, params[scope])
            if row and int(row["n"]) >= limits.get(scope, limits["provider"]):
                return False
        existing = await self.db.fetch_one("SELECT id FROM mission_concurrency_leases WHERE id=?", (value.id,))
        await self.db.execute(
            "INSERT OR IGNORE INTO mission_concurrency_leases(id,mission_id,task_id,session_id,project_id,provider,runtime_binding_id,account_id,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (value.id, value.mission_id, value.task_id, value.session_id, value.project_id,
             value.provider, value.runtime_binding_id, value.account_id, value.expires_at.isoformat(), value.created_at.isoformat()),
        )
        row = await self.db.fetch_one(
            "SELECT id FROM mission_concurrency_leases WHERE mission_id=? AND task_id IS ?",
            (value.mission_id, value.task_id))
        if existing is None and row and row["id"] == value.id and value.runtime_binding_id:
            await self.db.execute("UPDATE runtime_bindings SET reserved_slots=reserved_slots+1, updated_at=? WHERE id=?",
                                  (utc_now().isoformat(), value.runtime_binding_id))
        return bool(row and row["id"] == value.id)

    async def release(self, *, mission_id: str, task_id: str | None = None) -> None:
        async with self._lease_lock:
            await self._release(mission_id=mission_id, task_id=task_id)

    async def _release(self, *, mission_id: str, task_id: str | None = None) -> None:
        if task_id is None:
            await self.db.execute("DELETE FROM mission_concurrency_leases WHERE mission_id=?", (mission_id,))
        else:
            await self.db.execute("DELETE FROM mission_concurrency_leases WHERE mission_id=? AND task_id=?", (mission_id, task_id))
        await self.db.execute(
            "UPDATE runtime_bindings SET reserved_slots=(SELECT COUNT(*) FROM mission_concurrency_leases l WHERE l.runtime_binding_id=runtime_bindings.id), updated_at=?",
            (utc_now().isoformat(),),
        )

    async def add_integration(self, value: IntegrationAttempt) -> None:
        await self.db.execute(
            "INSERT INTO mission_integration_attempts(id,mission_id,task_id,integration_branch,source_branch,base_sha,result,commit_sha,message,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (value.id, value.mission_id, value.task_id, value.integration_branch, value.source_branch,
             value.base_sha, value.result, value.commit_sha, value.message, value.created_at.isoformat()),
        )

    async def integrations(self, mission_id: str) -> list[IntegrationAttempt]:
        rows = await self.db.fetch_all("SELECT * FROM mission_integration_attempts WHERE mission_id=? ORDER BY created_at", (mission_id,))
        return [IntegrationAttempt(id=r["id"], mission_id=r["mission_id"], task_id=r["task_id"],
            integration_branch=r["integration_branch"], source_branch=r["source_branch"], base_sha=r["base_sha"],
            result=r["result"], commit_sha=r["commit_sha"], message=r["message"], created_at=r["created_at"]) for r in rows]

    async def add_gate(self, value: QualityGateRun) -> None:
        await self.db.execute(
            "INSERT INTO mission_quality_gates(id,mission_id,task_id,name,command,exit_code,duration_ms,summary,passed,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (value.id, value.mission_id, value.task_id, value.name, dumps(value.command), value.exit_code,
             value.duration_ms, value.summary, int(value.passed), value.created_at.isoformat()),
        )

    async def gates(self, mission_id: str) -> list[QualityGateRun]:
        rows = await self.db.fetch_all("SELECT * FROM mission_quality_gates WHERE mission_id=? ORDER BY created_at", (mission_id,))
        return [QualityGateRun(id=r["id"], mission_id=r["mission_id"], task_id=r["task_id"], name=r["name"],
            command=loads(r["command"], []), exit_code=r["exit_code"], duration_ms=r["duration_ms"],
            summary=r["summary"], passed=bool(r["passed"]), created_at=r["created_at"]) for r in rows]

    async def add_approval(self, value: HumanApproval) -> None:
        await self.db.execute(
            "INSERT INTO mission_human_approvals(id,mission_id,decision,rationale,created_at) VALUES(?,?,?,?,?)",
            (value.id, value.mission_id, value.decision, value.rationale, value.created_at.isoformat()),
        )

    async def approvals(self, mission_id: str) -> list[HumanApproval]:
        rows = await self.db.fetch_all("SELECT * FROM mission_human_approvals WHERE mission_id=? ORDER BY created_at", (mission_id,))
        return [HumanApproval(id=r["id"], mission_id=r["mission_id"], decision=r["decision"], rationale=r["rationale"], created_at=r["created_at"]) for r in rows]
