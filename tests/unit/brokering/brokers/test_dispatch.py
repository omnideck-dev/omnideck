"""Canonical operation IDs are used directly for authorization and dispatch."""

from unittest.mock import AsyncMock

import pytest

from brokering._rpc import RpcError
from brokering.brokers._common._dispatch import dispatch_granted_operation
from integrations.operations import NATIVE_OPERATIONS


@pytest.mark.parametrize("operation_id", [operation.id for operation in NATIVE_OPERATIONS])
async def test_granted_operation_dispatches_by_its_canonical_id(operation_id):
    handler = AsyncMock(return_value={"ok": True})
    arguments = {"example": "value"}

    result = await dispatch_granted_operation(
        operation_id,
        arguments,
        operation_grants=frozenset({operation_id}),
        handlers={operation_id: handler},
    )

    assert result == {"ok": True}
    handler.assert_awaited_once_with(arguments)


@pytest.mark.parametrize("operation_id", [operation.id for operation in NATIVE_OPERATIONS])
async def test_ungranted_operation_never_reaches_its_handler(operation_id):
    handler = AsyncMock()

    with pytest.raises(RpcError) as error:
        await dispatch_granted_operation(
            operation_id,
            {},
            operation_grants=frozenset(),
            handlers={operation_id: handler},
        )

    assert error.value.code == "PERMISSION_DENIED"
    handler.assert_not_awaited()


@pytest.mark.parametrize("operation_id", ["list_mailboxes", "http_request", "get_test_value", "unknown"])
async def test_noncanonical_ids_are_rejected_even_if_granted_and_registered(operation_id):
    handler = AsyncMock()

    with pytest.raises(RpcError) as error:
        await dispatch_granted_operation(
            operation_id,
            {},
            operation_grants=frozenset({operation_id}),
            handlers={operation_id: handler},
        )

    assert error.value.code == "BAD_REQUEST"
    assert error.value.message == f"unknown operation: {operation_id}"
    handler.assert_not_awaited()


async def test_grant_check_precedes_handler_lookup():
    with pytest.raises(RpcError) as error:
        await dispatch_granted_operation(
            "email.messages.send",
            {},
            operation_grants=frozenset(),
            handlers={},
        )
    assert error.value.code == "PERMISSION_DENIED"


async def test_granted_but_unimplemented_operation_reports_a_missing_handler():
    with pytest.raises(RpcError) as error:
        await dispatch_granted_operation(
            "email.messages.send",
            {},
            operation_grants=frozenset({"email.messages.send"}),
            handlers={},
        )
    assert error.value.code == "BAD_REQUEST"
    assert error.value.message == "operation not implemented: email.messages.send"
