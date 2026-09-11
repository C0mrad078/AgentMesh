from __future__ import annotations

import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from core.database.connection import Database


@pytest_asyncio.fixture
async def tmp_db() -> AsyncIterator[Database]:
    tmp_dir = tempfile.mkdtemp(prefix="orchestrator-test-")
    db_path = Path(tmp_dir) / "test.db"
    db = Database(db_path)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)
