"""Credential control ownership, exact acknowledgments, and secret-safe errors."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from brokering import _control
from brokering._control import BrokerControl, CredentialRejected, PreparedBrokerSession
from brokering._session_slot import BrokerSessionSlot
from brokering._rpc import encode_frame


def message(command, update_id="one", **fields):
    return {"command": command, "id": update_id, **fields}


async def test_prepare_does_not_activate_and_commit_is_single_use():
    candidate = PreparedBrokerSession(activate=AsyncMock(), discard=AsyncMock())
    prepare = AsyncMock(return_value=candidate)
    control = BrokerControl(Mock(), prepare)
    reply = await control.handle(message("prepare_credentials", credentials={"TOKEN": "secret"}))
    assert reply == message("prepare_credentials", status="ok")
    assert "secret" not in str(reply)
    candidate.activate.assert_not_awaited()
    with pytest.raises(ValueError):
        await control.handle(message("activate_credentials", "wrong"))
    with pytest.raises(ValueError):
        await control.handle({"grants": []})
    await control.handle(message("activate_credentials"))
    candidate.activate.assert_awaited_once()
    candidate.discard.assert_not_awaited()
    with pytest.raises(ValueError):
        await control.handle(message("activate_credentials"))
    await control.close()
    candidate.discard.assert_not_awaited()


@pytest.mark.parametrize("command", ["discard_credentials", None])
async def test_discard_or_parent_loss_cleans_up_candidate(command):
    candidate = PreparedBrokerSession(activate=AsyncMock(), discard=AsyncMock())
    grants = Mock()
    control = BrokerControl(grants, AsyncMock(return_value=candidate))
    await control.handle(message("prepare_credentials", credentials={}))
    if command:
        await control.handle(message(command))
    await control.close()
    candidate.discard.assert_awaited_once()
    candidate.activate.assert_not_awaited()
    grants.assert_called_with(frozenset())


@pytest.mark.parametrize("error,code", [
    (CredentialRejected("AUTH"), "AUTH"),
    (ValueError("secret-in-upstream-error"), "BAD_REQUEST"),
    (KeyError("secret-in-upstream-error"), "BAD_REQUEST"),
    (OSError("secret-in-upstream-error"), "UPSTREAM"),
])
async def test_rejection_is_secret_safe_and_control_remains_usable(error, code):
    prepare = AsyncMock(side_effect=error)
    grants = Mock()
    control = BrokerControl(grants, prepare)
    reply = await control.handle(message("prepare_credentials", credentials={"TOKEN": "secret"}))
    assert reply == message("prepare_credentials", status="rejected", code=code)
    assert "secret" not in str(reply)
    assert await control.handle({"grants": []}) == {"grants": []}
    await control.close()


async def test_slot_keeps_current_on_rejection_and_closes_on_swap_without_draining():
    closed = []

    @asynccontextmanager
    async def factory(fields):
        if fields["token"] == "bad":
            raise CredentialRejected("AUTH")
        try:
            yield fields["token"]
        finally:
            closed.append(fields["token"])

    slot = BrokerSessionSlot(factory)
    await (await slot.prepare({"token": "old"})).activate()
    with pytest.raises(CredentialRejected):
        await slot.prepare({"token": "bad"})
    assert slot.current == "old"
    pending = await slot.prepare({"token": "new"})
    assert slot.current == "old"
    assert closed == []
    await pending.activate()
    assert slot.current == "new"
    assert closed == ["old"]
    await slot.close()
    assert closed == ["old", "new"]


@pytest.mark.parametrize("reply,exception", [
    (message("prepare_credentials", status="rejected", code="AUTH"), CredentialRejected),
    (message("prepare_credentials", "stale", status="ok"), ConnectionError),
    ({"status": "ok"}, ConnectionError),
    (None, asyncio.IncompleteReadError),
])
async def test_credential_acknowledgements_are_exact(reply, exception):
    reader = asyncio.StreamReader()
    if reply is not None:
        reader.feed_data(encode_frame(reply))
    reader.feed_eof()
    proc = SimpleNamespace(stdin=Mock(drain=AsyncMock()), stdout=reader, returncode=None)
    with pytest.raises(exception):
        await _control.credential_command(proc, "prepare_credentials", "one", {"TOKEN": "secret"})


async def test_credential_command_deadline(monkeypatch):
    monkeypatch.setattr(_control, "CREDENTIAL_UPDATE_TIMEOUT", .01)
    proc = SimpleNamespace(stdin=Mock(drain=AsyncMock()), stdout=asyncio.StreamReader(), returncode=None)
    with pytest.raises(TimeoutError):
        await _control.credential_command(proc, "activate_credentials", "one")
