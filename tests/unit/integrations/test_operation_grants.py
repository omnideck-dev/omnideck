from __future__ import annotations

import pytest

from integrations.operation_grants import (
    normalize_operation_grants,
    operation_grants_from_env,
    operation_grants_to_env,
)


def test_unknown_and_new_operations_are_denied_by_default() -> None:
    assert normalize_operation_grants(
        ["email.messages.search", "email.future.operation", "unknown"],
        ["email.messages.search", "email.future.operation"],
    ) == frozenset({"email.messages.search", "email.future.operation"})
    # A newly available operation is not added merely because another one was granted.
    assert normalize_operation_grants(
        ["email.messages.search"],
        ["email.messages.search", "email.future.operation"],
    ) == frozenset({"email.messages.search"})


def test_grants_env_round_trip_is_stable() -> None:
    raw = operation_grants_to_env({"email.messages.send", "email.messages.search"})
    assert raw == '["email.messages.search","email.messages.send"]'
    assert operation_grants_from_env(raw) == frozenset(
        {
            "email.messages.search",
            "email.messages.send",
        }
    )


@pytest.mark.parametrize("raw", ["not-json", "{}", '["ok", 3]'])
def test_grants_env_rejects_malformed_values(raw: str) -> None:
    with pytest.raises(ValueError):
        operation_grants_from_env(raw)
