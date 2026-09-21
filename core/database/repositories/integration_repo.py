from __future__ import annotations

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.integration.models import (
    ConflictFile,
    IntegrationConflict,
    QualityGateDefinition,
    QualityGateProfile,
    ResolutionAttempt,
    ResolutionDecision,
    ResolutionReview,
)
from core.utils.time import utc_now


class IntegrationRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def add_conflict(self, value: IntegrationConflict) -> None:
        await self.db.execute(
            """INSERT INTO integration_conflicts
            (id,mission_id,integration_attempt_id,status,classification,base_sha,ours_sha,theirs_sha,integration_head,resolution_worktree_id,integrator_session_id,reviewer_session_id,data,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (value.id,value.mission_id,value.integration_attempt_id,value.status,value.classification,value.base_sha,value.ours_sha,value.theirs_sha,value.integration_head,value.resolution_worktree_id,value.integrator_session_id,value.reviewer_session_id,dumps(value.data),value.created_at.isoformat(),value.updated_at.isoformat()))
        for file in value.files:
            await self.add_file(file)

    async def add_file(self, value: ConflictFile) -> None:
        await self.db.execute(
            "INSERT INTO integration_conflict_files(id,conflict_id,path,classification,base,ours,theirs,stages,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (value.id,value.conflict_id,value.path,value.classification,value.base,value.ours,value.theirs,dumps(value.stages),value.created_at.isoformat()))

    async def _conflict(self, row) -> IntegrationConflict:
        files = await self.db.fetch_all("SELECT * FROM integration_conflict_files WHERE conflict_id=? ORDER BY path", (row["id"],))
        return IntegrationConflict(
            id=row["id"], mission_id=row["mission_id"], integration_attempt_id=row["integration_attempt_id"], status=row["status"], classification=row["classification"], base_sha=row["base_sha"], ours_sha=row["ours_sha"], theirs_sha=row["theirs_sha"], integration_head=row["integration_head"], resolution_worktree_id=row["resolution_worktree_id"], integrator_session_id=row["integrator_session_id"], reviewer_session_id=row["reviewer_session_id"], data=loads(row["data"], {}), files=[ConflictFile(id=f["id"], conflict_id=f["conflict_id"], path=f["path"], classification=f["classification"], base=f["base"], ours=f["ours"], theirs=f["theirs"], stages=loads(f["stages"], {}), created_at=f["created_at"]) for f in files], created_at=row["created_at"], updated_at=row["updated_at"])

    async def list_conflicts(self, mission_id: str) -> list[IntegrationConflict]:
        rows = await self.db.fetch_all("SELECT * FROM integration_conflicts WHERE mission_id=? ORDER BY created_at", (mission_id,))
        return [await self._conflict(row) for row in rows]

    async def update_conflict(self, conflict_id: str, *, status: str, **patch: str | None) -> None:
        allowed = {"integrator_session_id", "reviewer_session_id", "resolution_worktree_id", "classification"}
        if set(patch) - allowed:
            raise ValueError("unsupported conflict patch")
        fields = ["status=?", "updated_at=?"]
        values: list[object] = [status, utc_now().isoformat()]
        for key, val in patch.items():
            fields.append(f"{key}=?")
            values.append(val)
        values.append(conflict_id)
        await self.db.execute(f"UPDATE integration_conflicts SET {', '.join(fields)} WHERE id=?", tuple(values))

    async def add_attempt(self, value: ResolutionAttempt) -> None:
        await self.db.execute("INSERT INTO resolution_attempts(id,conflict_id,attempt_no,status,worktree_id,integrator_session_id,proposal_artifact_id,commit_sha,strategy,data,created_at,updated_at,resolution_path,resolution_branch) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (value.id,value.conflict_id,value.attempt_no,value.status,value.worktree_id,value.integrator_session_id,value.proposal_artifact_id,value.commit_sha,value.strategy,dumps(value.data),value.created_at.isoformat(),value.updated_at.isoformat(),value.resolution_path,value.resolution_branch))

    async def attempts(self, conflict_id: str) -> list[ResolutionAttempt]:
        rows = await self.db.fetch_all("SELECT * FROM resolution_attempts WHERE conflict_id=? ORDER BY attempt_no", (conflict_id,))
        return [ResolutionAttempt(id=r["id"], conflict_id=r["conflict_id"], attempt_no=r["attempt_no"], status=r["status"], worktree_id=r["worktree_id"], integrator_session_id=r["integrator_session_id"], proposal_artifact_id=r["proposal_artifact_id"], commit_sha=r["commit_sha"], strategy=r["strategy"], data=loads(r["data"], {}), created_at=r["created_at"], updated_at=r["updated_at"], resolution_path=r["resolution_path"], resolution_branch=r["resolution_branch"]) for r in rows]

    async def update_attempt(self, attempt_id: str, **patch: object) -> None:
        allowed = {"status", "commit_sha", "strategy", "data"}
        if set(patch) - allowed:
            raise ValueError("unsupported resolution attempt patch")
        assignments = ["updated_at=?"]
        values: list[object] = [utc_now().isoformat()]
        for key, value in patch.items():
            assignments.append(f"{key}=?")
            values.append(dumps(value) if key == "data" else value)
        values.append(attempt_id)
        await self.db.execute(f"UPDATE resolution_attempts SET {', '.join(assignments)} WHERE id=?", tuple(values))

    async def add_review(self, value: ResolutionReview) -> None:
        await self.db.execute("INSERT INTO resolution_reviews(id,conflict_id,attempt_id,reviewer_session_id,verdict,findings,created_at) VALUES(?,?,?,?,?,?,?)", (value.id,value.conflict_id,value.attempt_id,value.reviewer_session_id,value.verdict,dumps(value.findings),value.created_at.isoformat()))

    async def add_decision(self, value: ResolutionDecision) -> None:
        await self.db.execute("INSERT INTO resolution_decisions(id,conflict_id,attempt_id,decision,rationale,actor_session_id,created_at) VALUES(?,?,?,?,?,?,?)", (value.id,value.conflict_id,value.attempt_id,value.decision,value.rationale,value.actor_session_id,value.created_at.isoformat()))

    async def list_profiles(self, project_id: str) -> list[QualityGateProfile]:
        rows = await self.db.fetch_all("SELECT * FROM quality_gate_profiles WHERE project_id=? ORDER BY name", (project_id,))
        return [self._profile(r) for r in rows]

    def _profile(self, row) -> QualityGateProfile:
        return QualityGateProfile(id=row["id"], project_id=row["project_id"], name=row["name"], is_default=bool(row["is_default"]), gates=[QualityGateDefinition.model_validate(g) for g in loads(row["gates"], [])], created_at=row["created_at"], updated_at=row["updated_at"])

    async def save_profile(self, profile: QualityGateProfile) -> QualityGateProfile:
        now = utc_now().isoformat()
        await self.db.execute("INSERT INTO quality_gate_profiles(id,project_id,name,is_default,gates,created_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,is_default=excluded.is_default,gates=excluded.gates,updated_at=excluded.updated_at", (profile.id,profile.project_id,profile.name,int(profile.is_default),dumps([g.model_dump(mode="json") for g in profile.gates]),profile.created_at.isoformat(),now))
        if profile.is_default:
            await self.db.execute("UPDATE quality_gate_profiles SET is_default=0 WHERE project_id=? AND id<>?", (profile.project_id, profile.id))
        row = await self.db.fetch_one("SELECT * FROM quality_gate_profiles WHERE id=?", (profile.id,))
        return self._profile(row)

    async def delete_profile(self, profile_id: str) -> None:
        await self.db.execute("DELETE FROM quality_gate_profiles WHERE id=?", (profile_id,))
