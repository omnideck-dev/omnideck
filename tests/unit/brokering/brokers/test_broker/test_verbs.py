from __future__ import annotations

import pytest

from brokering._rpc import RpcError
from brokering.brokers.test_broker._verbs import VerbDispatcher


@pytest.mark.unit
async def test_get_and_set_form_a_minimal_stateful_surface() -> None:
    dispatcher = VerbDispatcher(
        operation_grants=frozenset({"test.value.get", "test.value.set"}),
        initial_value="initial value",
    )

    assert await dispatcher.dispatch("test.value.get", {}) == {"value": "initial value"}
    assert await dispatcher.dispatch("test.value.set", {"value": "changed"}) == {
        "value": "changed",
    }
    assert await dispatcher.dispatch("test.value.get", {}) == {"value": "changed"}


@pytest.mark.unit
async def test_each_operation_is_independently_enforced() -> None:
    dispatcher = VerbDispatcher(
        operation_grants=frozenset({"test.value.get"}),
        initial_value="initial value",
    )

    assert await dispatcher.dispatch("test.value.get", {}) == {"value": "initial value"}
    with pytest.raises(RpcError, match="PERMISSION_DENIED") as exc_info:
        await dispatcher.dispatch("test.value.set", {"value": "changed"})
    assert exc_info.value.code == "PERMISSION_DENIED"


@pytest.mark.unit
async def test_set_rejects_an_empty_value() -> None:
    dispatcher = VerbDispatcher(
        operation_grants=frozenset({"test.value.set"}),
        initial_value="initial value",
    )

    with pytest.raises(RpcError, match="non-empty string") as exc_info:
        await dispatcher.dispatch("test.value.set", {"value": ""})
    assert exc_info.value.code == "BAD_REQUEST"
