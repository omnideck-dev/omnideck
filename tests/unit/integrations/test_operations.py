from __future__ import annotations

from integrations.operations import (
    NATIVE_OPERATIONS,
    OPERATIONS_BY_ID,
    operation_descriptors,
    operation_for_id,
)


def test_native_operation_ids_are_unique() -> None:
    ids = [operation.id for operation in NATIVE_OPERATIONS]
    assert len(ids) == len(set(ids))


def test_every_native_operation_has_display_metadata() -> None:
    for operation in NATIVE_OPERATIONS:
        assert operation.title
        assert operation.description


def test_operation_lookup_accepts_only_canonical_ids() -> None:
    for operation in NATIVE_OPERATIONS:
        assert operation_for_id(operation.id) is operation
        assert OPERATIONS_BY_ID[operation.id] is operation
    assert operation_for_id("search_messages") is None
    assert operation_for_id("unknown") is None


def test_public_operation_descriptors_keep_their_existing_shape() -> None:
    assert operation_descriptors({"email.mailboxes.list"}) == [
        {
            "id": "email.mailboxes.list",
            "title": "List email folders",
            "description": "List the folders in an email account.",
        }
    ]
