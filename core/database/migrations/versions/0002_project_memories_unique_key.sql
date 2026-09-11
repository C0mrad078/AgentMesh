-- 0002_project_memories_unique_key.sql
--
-- `ProjectMemoriesRepository.upsert` previously did a SELECT to decide
-- between INSERT and UPDATE, which is a TOCTOU race under concurrent calls
-- for the same (project_id, key): two coroutines could both see "no
-- existing row" and both INSERT, producing duplicate memory rows for the
-- same logical fact. A UNIQUE index lets the repository use a single
-- atomic `INSERT ... ON CONFLICT DO UPDATE` instead.

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_memories_project_key
    ON project_memories(project_id, key);
