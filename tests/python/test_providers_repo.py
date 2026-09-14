from __future__ import annotations

import pytest
from core.database.connection import Database
from core.database.repositories.provider_accounts_repo import ProviderAccountsRepository
from core.database.repositories.provider_backends_repo import ProviderBackendsRepository
from core.database.repositories.providers_repo import ProvidersRepository
from core.providers.catalog import (
    ProviderAccountCreate,
    ProviderAccountStatus,
    ProviderBackendStatus,
    ProviderBackendUpsert,
)
from core.runtime.execution_backend import ExecutionBackendType
from core.utils.errors import NotFoundError


async def test_providers_are_seeded_by_migration_0007(tmp_db: Database) -> None:
    repo = ProvidersRepository(tmp_db)
    names = {p.name for p in await repo.list()}
    assert names == {"claude", "openai", "google"}


async def test_get_provider_by_name(tmp_db: Database) -> None:
    repo = ProvidersRepository(tmp_db)
    claude = await repo.get_by_name("claude")
    assert claude is not None
    assert claude.display_name == "Claude"
    assert await repo.get(claude.id) == claude


async def test_provider_account_create_and_list(tmp_db: Database) -> None:
    providers_repo = ProvidersRepository(tmp_db)
    google = await providers_repo.get_by_name("google")
    assert google is not None

    accounts_repo = ProviderAccountsRepository(tmp_db)
    personal = await accounts_repo.create(
        ProviderAccountCreate(provider_id=google.id, label="Google Personal")
    )
    secondary = await accounts_repo.create(
        ProviderAccountCreate(provider_id=google.id, label="Google Secondary")
    )

    accounts = await accounts_repo.list_by_provider(google.id)
    assert {a.id for a in accounts} == {personal.id, secondary.id}
    assert all(a.status == ProviderAccountStatus.DISCONNECTED for a in accounts)


async def test_provider_account_status_update(tmp_db: Database) -> None:
    providers_repo = ProvidersRepository(tmp_db)
    claude = await providers_repo.get_by_name("claude")
    assert claude is not None
    accounts_repo = ProviderAccountsRepository(tmp_db)
    account = await accounts_repo.create(ProviderAccountCreate(provider_id=claude.id, label="Default"))

    updated = await accounts_repo.update_status(account.id, ProviderAccountStatus.CONNECTED)
    assert updated.status == ProviderAccountStatus.CONNECTED


async def test_provider_account_delete(tmp_db: Database) -> None:
    providers_repo = ProvidersRepository(tmp_db)
    claude = await providers_repo.get_by_name("claude")
    assert claude is not None
    accounts_repo = ProviderAccountsRepository(tmp_db)
    account = await accounts_repo.create(ProviderAccountCreate(provider_id=claude.id, label="Default"))

    await accounts_repo.delete(account.id)
    with pytest.raises(NotFoundError):
        await accounts_repo.get_or_raise(account.id)


async def test_provider_backend_upsert_is_keyed_on_provider_and_type(tmp_db: Database) -> None:
    providers_repo = ProvidersRepository(tmp_db)
    claude = await providers_repo.get_by_name("claude")
    assert claude is not None
    backends_repo = ProviderBackendsRepository(tmp_db)

    await backends_repo.upsert(
        ProviderBackendUpsert(
            provider_id=claude.id, backend_type=ExecutionBackendType.SUBSCRIPTION,
            status=ProviderBackendStatus.CONNECTED, detail="Claude Code CLI v1.2.3",
        )
    )
    # A second upsert for the SAME (provider, backend_type) updates in
    # place -- one backend row per combination, never a duplicate.
    updated = await backends_repo.upsert(
        ProviderBackendUpsert(
            provider_id=claude.id, backend_type=ExecutionBackendType.SUBSCRIPTION,
            status=ProviderBackendStatus.ERROR, detail="Login expired",
        )
    )
    assert updated.status == ProviderBackendStatus.ERROR
    assert updated.detail == "Login expired"

    all_backends = await backends_repo.list_by_provider(claude.id)
    assert len(all_backends) == 1


async def test_provider_can_have_multiple_backend_types(tmp_db: Database) -> None:
    providers_repo = ProvidersRepository(tmp_db)
    claude = await providers_repo.get_by_name("claude")
    assert claude is not None
    backends_repo = ProviderBackendsRepository(tmp_db)

    await backends_repo.upsert(
        ProviderBackendUpsert(provider_id=claude.id, backend_type=ExecutionBackendType.SUBSCRIPTION)
    )
    await backends_repo.upsert(
        ProviderBackendUpsert(
            provider_id=claude.id, backend_type=ExecutionBackendType.API,
            status=ProviderBackendStatus.CONNECTED,
        )
    )

    backends = await backends_repo.list_by_provider(claude.id)
    assert {b.backend_type for b in backends} == {
        ExecutionBackendType.SUBSCRIPTION, ExecutionBackendType.API,
    }


async def test_get_missing_provider_backend_returns_none(tmp_db: Database) -> None:
    providers_repo = ProvidersRepository(tmp_db)
    claude = await providers_repo.get_by_name("claude")
    assert claude is not None
    backends_repo = ProviderBackendsRepository(tmp_db)
    assert await backends_repo.get(claude.id, ExecutionBackendType.SESSION) is None
