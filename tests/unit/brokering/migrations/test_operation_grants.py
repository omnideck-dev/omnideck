from __future__ import annotations

from datetime import UTC, datetime

import pytest

from integrations.operations import OPERATIONS_BY_GROUP
from brokering.migrations._001_operation_grants import convert_metadata
from brokering.supervisor.types import IntegrationConnectionMeta, ModelProviderConnectionMeta, connection_meta_from_dict


def _raw(*, slug: str, version: int = 2) -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "version": version,
        "id": f"{slug}_example" if not slug.startswith("llm_") else slug,
        "slug": slug,
        "label": "Example",
        "added_at": now,
        "updated_at": now,
    }


def test_v2_read_write_expands_once_to_exact_native_operations() -> None:
    raw = _raw(slug="icloud") | {
        "permissions": {"email": "r", "calendar": "rw"},
    }
    migrated = convert_metadata(raw)
    meta = connection_meta_from_dict(migrated)
    assert isinstance(meta, IntegrationConnectionMeta)
    assert meta.version == 3
    assert meta.kind == "integration"
    assert (
        meta.agent_operation_grants
        == frozenset(
            {
                "email.mailboxes.list",
                "email.messages.list",
                "email.messages.search",
                "email.messages.get",
                "email.attachments.download",
            }
        )
        | OPERATIONS_BY_GROUP["calendar"]
    )
    assert "permissions" not in migrated


def test_v1_write_flag_migrates_without_retaining_global_access() -> None:
    raw = _raw(slug="gmail", version=1) | {"write_allowed": True}
    migrated = convert_metadata(raw)
    meta = connection_meta_from_dict(migrated)
    assert isinstance(meta, IntegrationConnectionMeta)
    assert meta.agent_operation_grants == OPERATIONS_BY_GROUP["email"]
    assert "write_allowed" not in migrated


def test_legacy_http_read_is_denied_without_widening_access() -> None:
    migrated = convert_metadata(
        _raw(slug="http") | {"permissions": {"http": "r"}},
    )
    meta = connection_meta_from_dict(migrated)
    assert isinstance(meta, IntegrationConnectionMeta)
    assert meta.agent_operation_grants == frozenset()


def test_brokered_llm_record_becomes_model_provider_without_fake_grants() -> None:
    raw = _raw(slug="llm_openai") | {"permissions": {"llm_proxy": "rw"}}
    migrated = convert_metadata(raw)
    meta = connection_meta_from_dict(migrated)
    assert isinstance(meta, ModelProviderConnectionMeta)
    assert meta.id == "llm_openai"
    assert meta.kind == "model_provider"
    assert "permissions" not in migrated
    assert "agent_operation_grants" not in migrated


def test_v3_parse_is_idempotent() -> None:
    migrated = convert_metadata(
        _raw(slug="gmail") | {"permissions": {"email": "r"}},
    )
    first = connection_meta_from_dict(migrated)
    second = connection_meta_from_dict(first.model_dump(mode="json"))
    assert second == first


def test_google_migration_needs_neither_scopes_nor_current_catalog(monkeypatch):
    # Availability and even the live operation catalog must not affect a
    # historical conversion: no scopes or credentials are supplied here.
    monkeypatch.setattr("integrations.operations.OPERATIONS_BY_GROUP", {})
    raw = _raw(slug="google_workspace") | {"permissions": {"email": "rw"}}
    migrated = convert_metadata(raw)
    assert "email.messages.send" in migrated["agent_operation_grants"]
    assert len(migrated["agent_operation_grants"]) == 7


def test_current_metadata_is_unchanged_even_for_a_new_preset():
    raw = _raw(slug="future", version=3) | {
        "kind": "integration", "agent_operation_grants": ["future.operation"],
    }
    assert convert_metadata(raw) == raw


@pytest.mark.parametrize("raw", [
    {"version": 2},
    {"version": 3, "kind": "integration", "permissions": {}},
])
def test_normal_connection_loading_rejects_legacy_data(raw):
    with pytest.raises(ValueError):
        connection_meta_from_dict(raw)
