"""Repository for the `model_registry` table.

Seeds from `core.providers.registry.DEFAULT_MODELS` on first startup only;
an existing row (identified by `provider` + `model_id`) is never overwritten
by a later seed call, since the user may have disabled it or edited its
priority/cost.
"""

from __future__ import annotations

import aiosqlite

from core.database.connection import Database
from core.database.json_codec import dumps, loads
from core.providers.registry import ModelInfo
from core.utils.ids import new_id
from core.utils.time import utc_now


def _row_to_model(row: aiosqlite.Row) -> ModelInfo:
    return ModelInfo(
        provider=row["provider"],
        model_id=row["model_id"],
        display_name=row["display_name"],
        capabilities=tuple(loads(row["capabilities"], [])),
        context_window=row["context_window"],
        supports_tools=bool(row["supports_tools"]),
        supports_images=bool(row["supports_images"]),
        supports_files=bool(row["supports_files"]),
        supports_structured_output=bool(row["supports_structured_output"]),
        input_cost_per_million_usd=row["input_cost_per_million_usd"],
        output_cost_per_million_usd=row["output_cost_per_million_usd"],
        priority=row["priority"],
        enabled=bool(row["enabled"]),
    )


class ModelRegistryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def seed_defaults(self, models: list[ModelInfo]) -> None:
        for model in models:
            existing = await self._db.fetch_one(
                "SELECT 1 FROM model_registry WHERE provider = ? AND model_id = ?",
                (model.provider, model.model_id),
            )
            if existing:
                continue
            await self._insert(model)

    async def _insert(self, model: ModelInfo) -> None:
        now = utc_now().isoformat()
        await self._db.execute(
            """
            INSERT INTO model_registry (
                id, provider, model_id, display_name, capabilities, context_window,
                supports_tools, supports_images, supports_files, supports_structured_output,
                input_cost_per_million_usd, output_cost_per_million_usd, priority, enabled,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("model"), model.provider, model.model_id, model.display_name,
                dumps(list(model.capabilities)), model.context_window,
                int(model.supports_tools), int(model.supports_images), int(model.supports_files),
                int(model.supports_structured_output), model.input_cost_per_million_usd,
                model.output_cost_per_million_usd, model.priority, int(model.enabled),
                now, now,
            ),
        )

    async def list_all(self) -> list[ModelInfo]:
        rows = await self._db.fetch_all("SELECT * FROM model_registry ORDER BY priority DESC")
        return [_row_to_model(row) for row in rows]

    async def set_enabled(self, provider: str, model_id: str, enabled: bool) -> None:
        await self._db.execute(
            "UPDATE model_registry SET enabled = ?, updated_at = ? "
            "WHERE provider = ? AND model_id = ?",
            (int(enabled), utc_now().isoformat(), provider, model_id),
        )
