from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.provider_configs_repo import ProviderConfigsRepository


async def test_upsert_creates_a_new_row(tmp_db: Database) -> None:
    repo = ProviderConfigsRepository(tmp_db)
    await repo.upsert("anthropic", display_name="Anthropic", secret_ref="provider_api_key:anthropic", enabled=True)
    config = await repo.get("anthropic")
    assert config is not None
    assert config["display_name"] == "Anthropic"
    assert bool(config["enabled"]) is True


async def test_upsert_updates_existing_row(tmp_db: Database) -> None:
    repo = ProviderConfigsRepository(tmp_db)
    await repo.upsert("anthropic", display_name="Anthropic", secret_ref="k", enabled=True)
    await repo.upsert("anthropic", display_name="Anthropic (Claude)", secret_ref="k", enabled=False)
    config = await repo.get("anthropic")
    assert config["display_name"] == "Anthropic (Claude)"
    assert bool(config["enabled"]) is False


async def test_set_enabled(tmp_db: Database) -> None:
    repo = ProviderConfigsRepository(tmp_db)
    await repo.upsert("gemini", display_name="Gemini", secret_ref="k", enabled=True)
    await repo.set_enabled("gemini", False)
    config = await repo.get("gemini")
    assert bool(config["enabled"]) is False


async def test_get_missing_provider_returns_none(tmp_db: Database) -> None:
    repo = ProviderConfigsRepository(tmp_db)
    assert await repo.get("openai") is None


async def test_list_all_returns_every_provider(tmp_db: Database) -> None:
    repo = ProviderConfigsRepository(tmp_db)
    await repo.upsert("anthropic", display_name="A", secret_ref="k1", enabled=True)
    await repo.upsert("gemini", display_name="G", secret_ref="k2", enabled=False)
    all_configs = await repo.list_all()
    assert {c["provider"] for c in all_configs} == {"anthropic", "gemini"}
