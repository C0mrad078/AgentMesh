from __future__ import annotations

import httpx
import pytest
import respx
from core.bridge.context import build_context
from core.bridge.handlers import dispatch
from core.database.repositories.audit_logs_repo import AuditLogsRepository
from core.security.secret_store import InMemorySecretStore
from core.utils.errors import ValidationError


@pytest.fixture
async def ctx(tmp_path):
    context = await build_context(tmp_path / "providers.db", secret_store=InMemorySecretStore())
    try:
        yield context
    finally:
        await context.close()


async def test_provider_list_shows_all_supported_providers_disconnected_by_default(ctx) -> None:
    result = await dispatch("provider.list", {}, ctx)
    providers = {p["provider"] for p in result}
    assert providers == {"anthropic", "gemini", "openai"}
    assert all(p["connected"] is False for p in result)
    assert all(p["enabled"] is False for p in result)


async def test_set_credential_registers_the_provider_and_never_echoes_the_key(ctx) -> None:
    result = await dispatch("provider.set_credential", {"provider": "anthropic", "api_key": "sk-secret"}, ctx)
    assert result == {"provider": "anthropic", "enabled": True}
    assert "sk-secret" not in str(result)

    providers = await dispatch("provider.list", {}, ctx)
    anthropic = next(p for p in providers if p["provider"] == "anthropic")
    assert anthropic["connected"] is True
    assert anthropic["enabled"] is True

    stored_key = await ctx.secret_store.get_secret("provider_api_key:anthropic")
    assert stored_key == "sk-secret"


async def test_set_credential_records_an_audit_entry_without_the_key(ctx) -> None:
    await dispatch("provider.set_credential", {"provider": "anthropic", "api_key": "sk-secret"}, ctx)

    entries = await AuditLogsRepository(ctx.db).list_for_resource("provider", "anthropic")
    assert len(entries) == 1
    assert entries[0]["action"] == "provider.set_credential"
    assert "sk-secret" not in entries[0]["context"]


async def test_set_credential_rejects_unsupported_provider(ctx) -> None:
    with pytest.raises(ValidationError):
        await dispatch("provider.set_credential", {"provider": "not-real", "api_key": "x"}, ctx)


async def test_remove_credential_disconnects_the_provider(ctx) -> None:
    await dispatch("provider.set_credential", {"provider": "openai", "api_key": "sk-x"}, ctx)
    result = await dispatch("provider.remove_credential", {"provider": "openai"}, ctx)
    assert result == {"provider": "openai", "enabled": False}

    providers = await dispatch("provider.list", {}, ctx)
    openai = next(p for p in providers if p["provider"] == "openai")
    assert openai["connected"] is False
    assert await ctx.secret_store.get_secret("provider_api_key:openai") is None


@respx.mock
async def test_test_connection_reports_connected_on_success(ctx) -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "OK"}], "model": "claude-haiku-4-5",
                "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )
    )
    result = await dispatch(
        "provider.test_connection", {"provider": "anthropic", "api_key": "sk-test"}, ctx
    )
    assert result == {"provider": "anthropic", "result": "connected"}


@respx.mock
async def test_test_connection_reports_invalid_key_on_401(ctx) -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    result = await dispatch(
        "provider.test_connection", {"provider": "anthropic", "api_key": "sk-bad"}, ctx
    )
    assert result == {"provider": "anthropic", "result": "invalid_key"}


async def test_test_connection_without_any_key_reports_provider_unavailable(ctx) -> None:
    result = await dispatch("provider.test_connection", {"provider": "gemini"}, ctx)
    assert result == {"provider": "gemini", "result": "provider_unavailable"}


async def test_provider_health_lists_every_supported_provider(ctx) -> None:
    result = await dispatch("provider.health", {}, ctx)
    assert {r["provider"] for r in result} == {"anthropic", "gemini", "openai"}
    assert all(r["status"] == "unknown" for r in result)
    # Stage 3: real backoff data (never fabricated) surfaces here too.
    assert all(r["retry_after_seconds"] is None for r in result)


async def test_model_list_includes_seeded_defaults(ctx) -> None:
    result = await dispatch("model.list", {}, ctx)
    model_ids = {(m["provider"], m["model_id"]) for m in result}
    assert ("anthropic", "claude-sonnet-5") in model_ids
    assert ("mock", "mock-general-1") in model_ids


async def test_budget_get_defaults_to_no_limits(ctx) -> None:
    result = await dispatch("budget.get", {}, ctx)
    assert result["max_per_execution_usd"] is None
    assert result["daily_limit_usd"] is None


async def test_budget_set_persists_and_updates_the_live_manager(ctx) -> None:
    result = await dispatch(
        "budget.set", {"max_per_execution_usd": 5.0, "daily_limit_usd": 20.0}, ctx
    )
    assert result["max_per_execution_usd"] == 5.0
    assert ctx.budget.limits.max_per_execution_usd == 5.0

    reloaded = await dispatch("budget.get", {}, ctx)
    assert reloaded["max_per_execution_usd"] == 5.0
    assert reloaded["daily_limit_usd"] == 20.0
