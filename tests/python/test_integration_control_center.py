from datetime import UTC, datetime

import pytest
from core.integration.models import QualityGateDefinition, QualityGateProfile, classify_conflict
from core.integration.quality_gates import detect_gates, validate_gate
from core.utils.errors import ValidationError
from core.utils.ids import new_id


def test_conflict_classification_is_conservative_and_deterministic():
    assert classify_conflict("src/shared_contract.py") == "api_contract"
    assert classify_conflict("package-lock.json") == "lockfile"
    assert classify_conflict("db/migrations/0017_schema.sql") == "migration_schema"
    assert classify_conflict("api/contract.yaml") == "api_contract"
    assert classify_conflict("assets/logo.png", binary=True) == "binary"
    assert classify_conflict("generated/client.generated.ts") == "generated"


def test_quality_gate_detection_and_path_policy(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest","build":"vite"}}')
    gates = detect_gates(tmp_path)
    assert [g.id for g in gates] == ["npm-test", "npm-build"]
    assert validate_gate(gates[0], tmp_path).argv == ["npm", "run", "test"]
    with pytest.raises(ValidationError):
        validate_gate(
            QualityGateDefinition(id="bad", name="bad", argv=["sh", "-c", "rm -rf ."], cwd="."),
            tmp_path,
        )


@pytest.mark.asyncio
async def test_quality_gate_profile_round_trip(tmp_db):
    from core.database.repositories.integration_repo import IntegrationRepository
    from core.database.repositories.projects_repo import ProjectsRepository
    from core.projects.models import ProjectCreate

    projects = ProjectsRepository(tmp_db)
    project = await projects.create(ProjectCreate(name="Integration test"))
    now = datetime.now(UTC)
    profile = QualityGateProfile(
        id=new_id("gate_profile"),
        project_id=project.id,
        name="quick",
        is_default=True,
        gates=[
            QualityGateDefinition(
                id="tests", name="Tests", argv=["pytest", "-q"], kind="test", source="user"
            )
        ],
        created_at=now,
        updated_at=now,
    )
    repo = IntegrationRepository(tmp_db)
    saved = await repo.save_profile(profile)
    assert saved.is_default and saved.gates[0].argv == ["pytest", "-q"]
    listed = await repo.list_profiles(project.id)
    assert [item.id for item in listed] == [profile.id]
    await repo.delete_profile(profile.id)
    assert await repo.list_profiles(project.id) == []
