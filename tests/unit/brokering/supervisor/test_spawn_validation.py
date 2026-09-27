from __future__ import annotations

from pathlib import Path

import pytest

from integrations.catalog import IntegrationCatalogEntry
from brokering.drivers import BrokerDriver
from brokering.supervisor._spawn import BrokerSpawnError, spawn_broker


@pytest.mark.unit
@pytest.mark.asyncio
async def test_spawn_rejects_non_string_secret_before_starting_process(
    tmp_path: Path,
) -> None:
    entry = IntegrationCatalogEntry(
        slug="test",
        title="Test",
        description="Test",
        category="Test",
        driver=BrokerDriver(
            id="test",
            command=("does-not-run",),
            env_injection={"token": "TOKEN"},
        ),
    )

    with pytest.raises(BrokerSpawnError, match="auth field 'token' must be a string"):
        await spawn_broker(
            entry=entry,
            connection_id="test",
            secret_bundle={"token": None},
            operation_grants=frozenset(),
            sockets_dir=tmp_path / "sockets",
            host_paths={},
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_spawn_wraps_process_start_errors(tmp_path: Path) -> None:
    entry = IntegrationCatalogEntry(
        slug="test",
        title="Test",
        description="Test",
        category="Test",
        driver=BrokerDriver(id="test", command=("omnideck-command-that-does-not-exist",)),
    )

    with pytest.raises(BrokerSpawnError, match="could not start broker process"):
        await spawn_broker(
            entry=entry,
            connection_id="test",
            secret_bundle={},
            operation_grants=frozenset(),
            sockets_dir=tmp_path / "sockets",
            host_paths={},
        )
