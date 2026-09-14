"""Migration risk register item (docs/refactor-v2-plan.md §5): the
`project_memories` table rebuild in migration 0012 relaxes `project_id` to
nullable so it can add scope/agent_id/session_id, using the standard SQLite
create-copy-drop-rename recipe (SQLite cannot drop a `NOT NULL` constraint
with `ALTER TABLE ADD COLUMN`). This test seeds a row through the *old*
(pre-0012) schema directly, applies only that one migration, and asserts
the row survived intact with `scope='project'` -- proving the rebuild is a
real, safe data migration, not just a schema change verified against an
empty table.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import aiosqlite
from core.database.migrations.runner import discover_migrations


async def test_existing_project_memory_rows_survive_the_scope_rebuild() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="orchestrator-migration-test-"))
    db_path = tmp_dir / "legacy.db"
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    try:
        migrations = discover_migrations()
        pre_0012 = [(v, p) for v, p in migrations if v < 12]
        migration_0012 = next(p for v, p in migrations if v == 12)
        assert pre_0012, "expected at least migrations 0001-0011 to exist before 0012"

        for _version, path in pre_0012:
            await conn.executescript(path.read_text(encoding="utf-8"))
        await conn.commit()

        # Seed a project and a legacy-shape memory row exactly as Stage 1-3
        # code would have written it -- no `scope`/`agent_id`/`session_id`
        # columns exist yet at this point.
        await conn.execute(
            "INSERT INTO projects (id, name, description, status, config, created_at, updated_at) "
            "VALUES ('proj_legacy', 'Legacy', '', 'active', '{}', '2025-01-01T00:00:00', '2025-01-01T00:00:00')"
        )
        await conn.execute(
            """
            INSERT INTO project_memories
                (id, project_id, kind, key, value, importance, created_at, updated_at,
                 category, confidence, provenance, valid_from, valid_until, superseded_by)
            VALUES
                ('mem_legacy', 'proj_legacy', 'fact', 'stack.language', '{"language": "python"}', 0.8,
                 '2025-01-01T00:00:00', '2025-01-01T00:00:00', 'stack', 0.9, '{}',
                 '2025-01-01T00:00:00', NULL, NULL)
            """
        )
        await conn.commit()

        await conn.executescript(migration_0012.read_text(encoding="utf-8"))
        await conn.commit()

        row = await conn.execute_fetchall("SELECT * FROM project_memories WHERE id = 'mem_legacy'")
        assert len(row) == 1
        record = dict(row[0])
        assert record["project_id"] == "proj_legacy"
        assert record["scope"] == "project"
        assert record["agent_id"] is None
        assert record["session_id"] is None
        assert record["key"] == "stack.language"
        assert record["value"] == '{"language": "python"}'
        assert record["confidence"] == 0.9
    finally:
        await conn.close()
