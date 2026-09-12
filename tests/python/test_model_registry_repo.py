from __future__ import annotations

from core.database.connection import Database
from core.database.repositories.model_registry_repo import ModelRegistryRepository
from core.providers.registry import DEFAULT_MODELS, ModelInfo


async def test_seed_defaults_inserts_all_models(tmp_db: Database) -> None:
    repo = ModelRegistryRepository(tmp_db)
    await repo.seed_defaults(list(DEFAULT_MODELS))
    models = await repo.list_all()
    assert len(models) == len(DEFAULT_MODELS)


async def test_seed_defaults_does_not_overwrite_existing_rows(tmp_db: Database) -> None:
    repo = ModelRegistryRepository(tmp_db)
    await repo.seed_defaults(list(DEFAULT_MODELS))
    await repo.set_enabled("mock", "mock-general-1", False)

    await repo.seed_defaults(list(DEFAULT_MODELS))  # re-seed, e.g. on next startup

    models = {(m.provider, m.model_id): m for m in await repo.list_all()}
    assert models[("mock", "mock-general-1")].enabled is False


async def test_set_enabled_toggles_a_model(tmp_db: Database) -> None:
    repo = ModelRegistryRepository(tmp_db)
    await repo.seed_defaults([ModelInfo(provider="anthropic", model_id="claude-sonnet-5", display_name="Sonnet")])
    await repo.set_enabled("anthropic", "claude-sonnet-5", False)
    models = {(m.provider, m.model_id): m for m in await repo.list_all()}
    assert models[("anthropic", "claude-sonnet-5")].enabled is False


async def test_round_trips_capabilities_and_costs(tmp_db: Database) -> None:
    repo = ModelRegistryRepository(tmp_db)
    model = ModelInfo(
        provider="openai", model_id="gpt-5.1", display_name="GPT-5.1",
        capabilities=("coding", "testing"), input_cost_per_million_usd=2.5,
        output_cost_per_million_usd=10.0, supports_tools=True,
    )
    await repo.seed_defaults([model])
    loaded = (await repo.list_all())[0]
    assert loaded.capabilities == ("coding", "testing")
    assert loaded.input_cost_per_million_usd == 2.5
    assert loaded.supports_tools is True
