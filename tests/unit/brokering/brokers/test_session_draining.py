"""Credential replacement cannot close a transport used by an in-flight call."""

from contextlib import asynccontextmanager

import pytest

from brokering._session_slot import BrokerSessionSlot


async def test_replacement_keeps_old_transport_until_last_call_finishes():
    closed = []
    @asynccontextmanager
    async def create(fields):
        try:
            yield fields['token']
        finally:
            closed.append(fields['token'])
    slot = BrokerSessionSlot(create)
    await (await slot.prepare({'token': 'old'})).activate()
    async with slot.borrow() as first:
        async with slot.borrow() as second:
            await (await slot.prepare({'token': 'new'})).activate()
            assert first == second == 'old'
            assert closed == []
            async with slot.borrow() as latest:
                assert latest == 'new'
        assert closed == []
    assert closed == ['old']
    await slot.close()
    assert closed == ['old', 'new']


async def test_failed_call_releases_retired_session_without_replay():
    closed = []
    @asynccontextmanager
    async def create(fields):
        try:
            yield fields
        finally:
            closed.append(fields)
    slot = BrokerSessionSlot(create)
    await (await slot.prepare({'token': 'old'})).activate()
    with pytest.raises(RuntimeError, match='call failed'):
        async with slot.borrow():
            await (await slot.prepare({'token': 'new'})).activate()
            raise RuntimeError('call failed')
    assert closed == [{'token': 'old'}]
    await slot.close()
