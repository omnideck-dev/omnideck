from __future__ import annotations

import pytest

from integrations.operation_grants import (
    legacy_permissions_to_operation_grants,
    normalize_operation_grants,
    operation_grants_from_env,
    operation_grants_to_env,
    operation_grants_to_legacy_permissions,
)
from integrations.operations import OPERATIONS_BY_GROUP
from integrations.permissions import Access, Capability


def test_legacy_read_write_expands_to_exact_known_operations() -> None:
    available = OPERATIONS_BY_GROUP["email"]
    grants = legacy_permissions_to_operation_grants(
        {Capability.EMAIL: Access.READ_WRITE},
        available,
    )
    assert grants == available


def test_legacy_http_read_does_not_widen_generic_request() -> None:
    available = OPERATIONS_BY_GROUP["http"]
    assert (
        legacy_permissions_to_operation_grants(
            {Capability.HTTP: Access.READ},
            available,
        )
        == frozenset()
    )
    assert legacy_permissions_to_operation_grants(
        {Capability.HTTP: Access.READ_WRITE},
        available,
    ) == frozenset({"http.request"})


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


def test_custom_subset_projects_to_off_instead_of_widening() -> None:
    projected = operation_grants_to_legacy_permissions(
        {"email.messages.search"},
        OPERATIONS_BY_GROUP["email"],
    )
    assert projected == {Capability.EMAIL: Access.OFF}


def test_exact_legacy_sets_round_trip() -> None:
    for access in (Access.OFF, Access.READ, Access.READ_WRITE):
        grants = legacy_permissions_to_operation_grants(
            {Capability.EMAIL: access},
            OPERATIONS_BY_GROUP["email"],
        )
        projected = operation_grants_to_legacy_permissions(
            grants,
            OPERATIONS_BY_GROUP["email"],
        )
        assert projected == {Capability.EMAIL: access}


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
