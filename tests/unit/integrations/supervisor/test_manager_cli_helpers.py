"""Tests for the CLI-integration helper functions in ``_manager.py``.

Covers the pieces added to close code-review gaps in the CLI-exec
integration feature: path-prefix normalization, and the ``auth_blob``
validation that runs before a CLI integration's secret ever reaches the
vault.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from integrations._rpc import RpcError
from integrations.supervisor._catalog import _CLI, _HTTP
from integrations.supervisor._manager import BrokerManager, _normalize_path_prefix, _validate_cli_secret_bundle
from integrations.supervisor._registry import IntegrationRecord, Registry
from integrations.supervisor._spawn import BrokerHandle
from integrations.supervisor.types import IntegrationMeta


# ── _normalize_path_prefix ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),  # whitespace-only collapses to None, not a literal " " scope
        ("repo", "repo"),
        ("/repo", "repo"),
        ("repo/", "repo"),
        ("/repo/", "repo"),
        ("//repo//", "repo"),
        (" repo ", "repo"),
        ("repo/sub", "repo/sub"),
        (123, None),
        ([], None),
    ],
)
def test_normalize_path_prefix(raw: object, expected: str | None) -> None:
    assert _normalize_path_prefix(raw) == expected


def test_normalize_path_prefix_makes_slash_variants_equal() -> None:
    """The exact bug the collision check depends on this fixing."""
    assert _normalize_path_prefix("repo") == _normalize_path_prefix("/repo/")


def test_normalize_path_prefix_makes_whitespace_variants_equal() -> None:
    """A whitespace-only value must never become a literal scope no real directory can match."""
    assert _normalize_path_prefix("   ") is None


# ── _validate_cli_secret_bundle ─────────────────────────────────────────────


def test_validate_cli_secret_bundle_noop_for_non_cli_entry() -> None:
    # Should not raise even for a bundle that would fail CliSecretBundle validation.
    _validate_cli_secret_bundle(_HTTP, {"vars": "not-a-dict"})


def test_validate_cli_secret_bundle_accepts_valid_bundle() -> None:
    _validate_cli_secret_bundle(
        _CLI, {"command": ["python", "/opt/x.py"], "vars": {"TOKEN": "abc"}},
    )


def test_validate_cli_secret_bundle_rejects_missing_command() -> None:
    with pytest.raises(RpcError) as exc_info:
        _validate_cli_secret_bundle(_CLI, {"vars": {"TOKEN": "abc"}})
    assert exc_info.value.code == "BAD_REQUEST"
    assert "command" in exc_info.value.message


def test_validate_cli_secret_bundle_rejects_empty_command() -> None:
    with pytest.raises(RpcError) as exc_info:
        _validate_cli_secret_bundle(_CLI, {"command": []})
    assert exc_info.value.code == "BAD_REQUEST"


def test_validate_cli_secret_bundle_rejects_non_string_command_items() -> None:
    with pytest.raises(RpcError) as exc_info:
        _validate_cli_secret_bundle(_CLI, {"command": ["bin", 123]})
    assert exc_info.value.code == "BAD_REQUEST"


def test_validate_cli_secret_bundle_rejects_non_dict_vars() -> None:
    with pytest.raises(RpcError) as exc_info:
        _validate_cli_secret_bundle(_CLI, {"command": ["bin"], "vars": "nope"})
    assert exc_info.value.code == "BAD_REQUEST"


def test_validate_cli_secret_bundle_rejects_non_string_var_value() -> None:
    with pytest.raises(RpcError) as exc_info:
        _validate_cli_secret_bundle(_CLI, {"command": ["bin"], "vars": {"X": 123}})
    assert exc_info.value.code == "BAD_REQUEST"


# ── _reserve_cli_secret_names / _release_cli_secret_names (TOCTOU guard) ────


def _make_manager(tmp_path: Path) -> BrokerManager:
    return BrokerManager(
        vault_dir=tmp_path / "vault",
        sockets_dir=tmp_path / "sockets",
        host_paths={},
        master_key=b"0" * 32,
        catalog={"cli": _CLI},
        registry=Registry(),
    )


def test_reserve_then_release_allows_reuse(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    blob = {"command": ["bin"], "vars": {"TOKEN": "one"}}

    reservation = manager._reserve_cli_secret_names(_CLI, blob, None, exclude_id=None)
    assert reservation == frozenset({(None, "TOKEN")})

    manager._release_cli_secret_names(reservation)

    # Freed — a second reservation for the same scope+name succeeds.
    second = manager._reserve_cli_secret_names(_CLI, blob, None, exclude_id=None)
    assert second == frozenset({(None, "TOKEN")})


def test_reserve_rejects_concurrent_same_scope_collision(tmp_path: Path) -> None:
    """The TOCTOU case: neither integration has reached the registry yet.

    Simulates two concurrent `add()` calls racing past the registry-only
    collision check (empty registry, both would pass) — the in-flight
    reservation is what actually stops the second one.
    """
    manager = _make_manager(tmp_path)
    blob_a = {"command": ["bin"], "vars": {"SLACK_TOKEN": "one"}}
    blob_b = {"command": ["bin"], "vars": {"SLACK_TOKEN": "two"}}

    first = manager._reserve_cli_secret_names(_CLI, blob_a, None, exclude_id=None)
    try:
        with pytest.raises(RpcError) as exc_info:
            manager._reserve_cli_secret_names(_CLI, blob_b, None, exclude_id=None)
        assert exc_info.value.code == "BAD_REQUEST"
    finally:
        manager._release_cli_secret_names(first)


def test_reserve_allows_concurrent_different_scope(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    blob_a = {"command": ["bin"], "vars": {"SLACK_TOKEN": "one"}}
    blob_b = {"command": ["bin"], "vars": {"SLACK_TOKEN": "two"}}

    global_reservation = manager._reserve_cli_secret_names(_CLI, blob_a, None, exclude_id=None)
    scoped_reservation = manager._reserve_cli_secret_names(_CLI, blob_b, "repo", exclude_id=None)

    assert global_reservation != scoped_reservation
    manager._release_cli_secret_names(global_reservation)
    manager._release_cli_secret_names(scoped_reservation)


def test_reserve_does_not_collide_with_its_own_pending_reservation(tmp_path: Path) -> None:
    """A single integration's own overlapping calls (e.g. a double-submit) don't self-collide.

    Two update() calls rotating the SAME integration's secret to the same
    var name both pass `exclude_id=<that integration's id>` — the second
    must not be rejected just because the first is still pending, since
    they're not two different integrations racing for the same name.
    """
    manager = _make_manager(tmp_path)
    blob = {"command": ["bin"], "vars": {"TOKEN": "one"}}

    first = manager._reserve_cli_secret_names(_CLI, blob, None, exclude_id="same_id")
    try:
        second = manager._reserve_cli_secret_names(_CLI, blob, None, exclude_id="same_id")
        manager._release_cli_secret_names(second)
    finally:
        manager._release_cli_secret_names(first)


def test_reserve_still_collides_with_a_different_owners_pending_reservation(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    blob_a = {"command": ["bin"], "vars": {"TOKEN": "one"}}
    blob_b = {"command": ["bin"], "vars": {"TOKEN": "two"}}

    first = manager._reserve_cli_secret_names(_CLI, blob_a, None, exclude_id="integration_a")
    try:
        with pytest.raises(RpcError) as exc_info:
            manager._reserve_cli_secret_names(_CLI, blob_b, None, exclude_id="integration_b")
        assert exc_info.value.code == "BAD_REQUEST"
    finally:
        manager._release_cli_secret_names(first)


# ── _cli_secret_name_cache (avoids re-decrypting on every check) ───────────


def test_check_collisions_uses_cache_not_decryption(tmp_path: Path) -> None:
    """The registry-based collision check must not need to decrypt anything.

    Registers a record directly (no vault files on disk for it at all) and
    populates its cache entry by hand — if `_check_cli_secret_collisions`
    tried to `read_secrets` for it, this would raise (no `.enc` file
    exists), proving the check is cache-only.
    """
    manager = _make_manager(tmp_path)
    other = _registered_record("cli", integration_id="other_x")
    manager._registry.add(other)
    manager._cache_cli_secret_names(_CLI, "other_x", {"vars": {"SLACK_TOKEN": "x"}})

    with pytest.raises(RpcError) as exc_info:
        manager._check_cli_secret_collisions(
            _CLI, {"vars": {"SLACK_TOKEN": "y"}}, None, exclude_id=None,
        )
    assert exc_info.value.code == "BAD_REQUEST"


def test_check_collisions_cache_miss_is_not_a_collision(tmp_path: Path) -> None:
    """A registered CLI integration with no cache entry (or an empty one) never blocks."""
    manager = _make_manager(tmp_path)
    other = _registered_record("cli", integration_id="other_x")
    manager._registry.add(other)
    # No _cache_cli_secret_names call at all — simulates any gap before the
    # cache is populated; must fail open (no false-positive collision), not
    # fail closed by decrypting.
    manager._check_cli_secret_collisions(
        _CLI, {"vars": {"SLACK_TOKEN": "y"}}, None, exclude_id=None,
    )


def test_cache_removed_on_remove(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    manager._cache_cli_secret_names(_CLI, "gone", {"vars": {"X": "y"}})
    assert manager._cli_secret_name_cache["gone"] == frozenset({"X"})
    manager._cli_secret_name_cache.pop("gone", None)
    assert "gone" not in manager._cli_secret_name_cache


# ── update() catalog lookup stays lazy (regression) ──────────────────────────


def _registered_record(slug: str, *, integration_id: str = "orphaned_x") -> IntegrationRecord:
    now = datetime.now(UTC)
    meta = IntegrationMeta(
        id=integration_id, slug=slug, label="Old Label", permissions={},
        added_at=now, updated_at=now,
    )
    return IntegrationRecord(
        meta=meta,
        broker=BrokerHandle(
            integration_id=integration_id, socket_path=Path("/tmp/unused.sock"), proc=MagicMock(),
        ),
        max_access={},
    )


@pytest.mark.asyncio
async def test_update_label_only_succeeds_when_slug_missing_from_catalog(tmp_path: Path) -> None:
    """Regression: a label-only rename must not require a catalog entry.

    Before the secret-rotation feature, ``update()`` only consulted the
    catalog inside the permissions-changed/respawn branch — a label-only
    rename worked even for an integration whose slug had since been dropped
    from ``DEFAULT_CATALOG`` (a deprecated provider). The catalog lookup
    must stay conditional on actually needing it.
    """
    manager = BrokerManager(
        vault_dir=tmp_path / "vault", sockets_dir=tmp_path / "sockets", host_paths={},
        master_key=b"0" * 32, catalog={}, registry=Registry(),
    )
    manager._registry.add(_registered_record("deprecated_slug"))

    updated = await manager.update("orphaned_x", label="New Label")
    assert updated.meta.label == "New Label"


@pytest.mark.asyncio
async def test_update_noop_succeeds_when_slug_missing_from_catalog(tmp_path: Path) -> None:
    """Same regression for the idempotent no-op path (identical label resubmitted)."""
    manager = BrokerManager(
        vault_dir=tmp_path / "vault", sockets_dir=tmp_path / "sockets", host_paths={},
        master_key=b"0" * 32, catalog={}, registry=Registry(),
    )
    manager._registry.add(_registered_record("deprecated_slug"))

    updated = await manager.update("orphaned_x", label="Old Label")
    assert updated.meta.label == "Old Label"
