"""Private control acknowledgements must be exact and bounded."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from brokering import _control
from brokering._rpc import encode_frame


@pytest.mark.parametrize("reply", [{}, {"grants": []}, {"grants": ["wrong"]}, None])
async def test_invalid_or_missing_acknowledgement_is_not_success(reply):
    reader = asyncio.StreamReader()
    if reply is not None:
        reader.feed_data(encode_frame(reply))
    reader.feed_eof()
    proc = SimpleNamespace(stdin=Mock(drain=AsyncMock()), stdout=reader, returncode=None)
    with pytest.raises((ConnectionError, asyncio.IncompleteReadError)):
        await _control.update_broker_grants(proc, frozenset({"test.value.get"}))


async def test_acknowledgement_has_a_deadline(monkeypatch):
    monkeypatch.setattr(_control, "GRANT_UPDATE_TIMEOUT", .01)
    proc = SimpleNamespace(stdin=Mock(drain=AsyncMock()), stdout=asyncio.StreamReader(), returncode=None)
    with pytest.raises(TimeoutError):
        await _control.update_broker_grants(proc, frozenset())


async def test_acknowledgement_accepts_exact_grants():
    reader = asyncio.StreamReader()
    reader.feed_data(encode_frame({"grants": ["test.value.get"]}))
    writer = Mock(drain=AsyncMock())
    proc = SimpleNamespace(stdin=writer, stdout=reader, returncode=None)
    await _control.update_broker_grants(proc, frozenset({"test.value.get"}))
    writer.write.assert_called_once_with(encode_frame({"grants": ["test.value.get"]}))
