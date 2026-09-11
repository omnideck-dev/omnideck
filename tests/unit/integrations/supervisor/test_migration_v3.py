from __future__ import annotations

from datetime import UTC, datetime

from integrations.catalog import DEFAULT_CATALOG
from integrations.operations import OPERATIONS_BY_GROUP
from integrations.supervisor._manager import _migrate_to_v3
from integrations.supervisor.types import IntegrationMeta, ModelProviderMeta, connection_meta_from_dict


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
    entry = DEFAULT_CATALOG["icloud"]
    available = entry.resolve_operations({})
    raw = _raw(slug="icloud") | {
        "permissions": {"email": "r", "calendar": "rw"},
    }
    migrated = _migrate_to_v3(raw, entry, available)
    meta = connection_meta_from_dict(migrated)
    assert isinstance(meta, IntegrationMeta)
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
    entry = DEFAULT_CATALOG["gmail"]
    raw = _raw(slug="gmail", version=1) | {"write_allowed": True}
    migrated = _migrate_to_v3(raw, entry, entry.resolve_operations({}))
    meta = connection_meta_from_dict(migrated)
    assert isinstance(meta, IntegrationMeta)
    assert meta.agent_operation_grants == OPERATIONS_BY_GROUP["email"]
    assert "write_allowed" not in migrated


def test_legacy_http_read_is_denied_without_widening_access() -> None:
    entry = DEFAULT_CATALOG["http"]
    migrated = _migrate_to_v3(
        _raw(slug="http") | {"permissions": {"http": "r"}},
        entry,
        entry.resolve_operations({}),
    )
    meta = connection_meta_from_dict(migrated)
    assert isinstance(meta, IntegrationMeta)
    assert meta.agent_operation_grants == frozenset()


def test_brokered_llm_record_becomes_model_provider_without_fake_grants() -> None:
    entry = DEFAULT_CATALOG["llm_openai"]
    raw = _raw(slug="llm_openai") | {"permissions": {"llm_proxy": "rw"}}
    migrated = _migrate_to_v3(raw, entry, frozenset())
    meta = connection_meta_from_dict(migrated)
    assert isinstance(meta, ModelProviderMeta)
    assert meta.id == "llm_openai"
    assert meta.kind == "model_provider"
    assert "permissions" not in migrated
    assert "agent_operation_grants" not in migrated


def test_v3_parse_is_idempotent() -> None:
    entry = DEFAULT_CATALOG["gmail"]
    migrated = _migrate_to_v3(
        _raw(slug="gmail") | {"permissions": {"email": "r"}},
        entry,
        entry.resolve_operations({}),
    )
    first = connection_meta_from_dict(migrated)
    second = connection_meta_from_dict(first.model_dump(mode="json"))
    assert second == first
