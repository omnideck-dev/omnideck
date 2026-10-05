"""Cancellation ownership and commit ordering, without remote credentials."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from server._mcp_setup import MCPSetupManager


@pytest.mark.parametrize("origin", ["https://evil.test", "http://127.0.0.1:9000", "http://localhost:9000/path", "http://user@localhost:9000", "http://localhost:9000?x=1"])
def test_callback_address_must_come_from_explicit_loopback_runtime_configuration(origin):
    with pytest.raises(ValueError):
        MCPSetupManager(callback_origin=origin, commit=AsyncMock())


async def test_cancel_during_commit_waits_for_definitive_connection(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def commit(verb, args):
        entered.set()
        await release.wait()
        assert verb == "add" and args["operation_grants"] == []
        return {"id": "mcp_created"}

    manager = MCPSetupManager(callback_origin="http://localhost:9000", commit=commit)
    monkeypatch.setattr("server._mcp_setup.validated_address", AsyncMock())
    monkeypatch.setattr(manager, "_authorize_and_discover", AsyncMock(return_value={"access_token": "not-public"}))
    pending = await manager.start({"endpoint": "https://fixture.test", "slug": "mcp", "label": "Fixture"})
    await entered.wait()
    cancel = asyncio.create_task(manager.cancel(pending.handle))
    await asyncio.sleep(0)
    assert not cancel.done()
    release.set()
    result = await cancel
    assert result.status == "success" and result.integration_id == "mcp_created"
    assert "not-public" not in str(result.public_status())
    await manager.close()


async def test_cancel_waiting_for_consent_never_commits(monkeypatch):
    commit = AsyncMock()
    manager = MCPSetupManager(callback_origin="http://localhost:9000", commit=commit)
    monkeypatch.setattr("server._mcp_setup.validated_address", AsyncMock())

    async def wait(pending, settings):
        pending.ready.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(manager, "_authorize_and_discover", wait)
    pending = await manager.start({"endpoint": "https://fixture.test"})
    result = await manager.cancel(pending.handle)
    assert result.status == "cancelled"
    commit.assert_not_called()
    await manager.close()
