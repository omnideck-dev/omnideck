"""Unit tests for ``server._integrations_routes``.

Covers the pure suffix helpers and the route
handler logic for LLM vs. non-LLM integrations — the add handler's
suffix derivation, permissions injection, and supervisor call arguments.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server._integrations_routes import (
    _derive_connection_suffix,
    _derive_suffix_from_email,
    handle_add_integration,
    handle_integration_catalog,
    handle_list_integrations,
    handle_reconnect_integration,
    handle_update_integration,
)
from server._integration_cache import INTEGRATION_CACHE_KEY


# ── email-based suffix derivation ────────────────────────────────────────────


@pytest.mark.unit
def test_derive_suffix_returns_local_part_for_simple_address() -> None:
    assert _derive_suffix_from_email({"email": "alice@example.com"}) == "alice"


@pytest.mark.unit
def test_derive_suffix_lowercases_email() -> None:
    assert _derive_suffix_from_email({"email": "Alice@Example.com"}) == "alice"


@pytest.mark.unit
def test_derive_suffix_replaces_dots_and_pluses_with_dashes() -> None:
    assert _derive_suffix_from_email({"email": "alice.smith+work@x.com"}) == "alice-smith-work"


@pytest.mark.unit
def test_derive_suffix_collapses_dash_runs() -> None:
    assert _derive_suffix_from_email({"email": "a..b@x.com"}) == "a-b"


@pytest.mark.unit
def test_derive_suffix_strips_leading_and_trailing_dashes() -> None:
    assert _derive_suffix_from_email({"email": "-alice-@x.com"}) == "alice"


@pytest.mark.unit
def test_derive_suffix_preserves_underscore_and_dash() -> None:
    assert _derive_suffix_from_email({"email": "alice_smith-2@x.com"}) == "alice_smith-2"


@pytest.mark.unit
def test_derive_suffix_caps_at_48_chars() -> None:
    long_local = "a" * 100
    out = _derive_suffix_from_email({"email": f"{long_local}@x.com"})
    assert out is not None
    assert len(out) == 48
    assert out == "a" * 48


@pytest.mark.unit
def test_derive_suffix_returns_none_when_local_is_all_disallowed() -> None:
    assert _derive_suffix_from_email({"email": "++@x.com"}) is None


@pytest.mark.unit
def test_derive_suffix_handles_address_without_at_sign() -> None:
    assert _derive_suffix_from_email({"email": "noatsign"}) == "noatsign"


@pytest.mark.unit
def test_derive_suffix_returns_none_for_non_email_blob() -> None:
    assert _derive_suffix_from_email({"api_key": "sk-..."}) is None


@pytest.mark.unit
def test_derive_suffix_returns_none_when_no_email() -> None:
    assert _derive_suffix_from_email({}) is None


@pytest.mark.unit
def test_derive_suffix_returns_none_when_email_not_a_string() -> None:
    assert _derive_suffix_from_email({"email": 123}) is None  # type: ignore[arg-type]


@pytest.mark.unit
def test_derive_suffix_returns_none_when_auth_blob_is_none() -> None:
    assert _derive_suffix_from_email(None) is None


@pytest.mark.unit
def test_derive_suffix_returns_none_when_auth_blob_is_not_a_dict() -> None:
    assert _derive_suffix_from_email("not a dict") is None  # type: ignore[arg-type]


# ── handle_add_integration — domain separation ──────────────────────────────


def _make_add_request(body: dict) -> MagicMock:
    """Build a minimal aiohttp Request mock with a JSON body."""
    req = MagicMock()
    req.json = AsyncMock(return_value=body)
    req.app = {INTEGRATION_CACHE_KEY: MagicMock(refresh=AsyncMock(return_value=True))}
    return req


def _supervisor_ok(integration_id: str, slug: str) -> dict:
    """Minimal supervisor add response."""
    return {
        "id": integration_id,
        "slug": slug,
        "label": "Test",
        "permissions": {},
        "max_access": {},
        "capabilities": [],
        "state": "running",
        "socket": f"/run/cvault/{integration_id}.sock",
    }


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["llm_openai", "llm_anthropic", "llm_openrouter"])
async def test_model_provider_is_rejected_by_integrations_api(slug: str) -> None:
    body = {"slug": slug, "label": "Provider", "auth_blob": {"api_key": "sk-test"}}
    resp = await handle_add_integration(_make_add_request(body))
    assert resp.status == 400
    data = json.loads(resp.body)
    assert "providers api" in data["error"]["message"].lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_email_integration_derives_suffix_from_label() -> None:
    """Generic integrations do not need to invent an email identity."""
    body = {"slug": "test", "label": "Local Test", "auth_blob": {"token": "secret"}}
    captured_args = {}

    async def fake_supervisor_call(verb, args):
        captured_args.update(args)
        return _supervisor_ok("test_local-test", "test")

    with (
        patch("server._integrations_routes._supervisor_call", side_effect=fake_supervisor_call),
    ):
        resp = await handle_add_integration(_make_add_request(body))

    assert resp.status == 201
    assert captured_args["user_suffix"] == "local-test"
    assert _derive_connection_suffix(body["auth_blob"], body["label"]) == "local-test"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_llm_add_derives_suffix_from_email() -> None:
    """Non-LLM integrations derive user_suffix from auth_blob email."""
    body = {
        "slug": "icloud",
        "label": "iCloud",
        "auth_blob": {"email": "alice@example.com", "password": "secret"},
        "operation_grants": ["email.messages.send"],
    }
    captured_args = {}

    async def fake_supervisor_call(verb, args):
        captured_args.update(args)
        return _supervisor_ok("icloud_alice", "icloud")

    with (
        patch("server._integrations_routes._supervisor_call", side_effect=fake_supervisor_call),
    ):
        resp = await handle_add_integration(_make_add_request(body))

    assert resp.status == 201
    assert captured_args["user_suffix"] == "alice"
    assert captured_args["kind"] == "integration"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_requests_only_integration_domain() -> None:
    async def fake_supervisor_call(verb, args):
        assert verb == "list"
        assert args == {"kind": "integration"}
        return {"connections": []}

    with patch("server._integrations_routes._supervisor_call", side_effect=fake_supervisor_call):
        response = await handle_list_integrations(MagicMock())
    assert response.status == 200

    assert json.loads(response.text) == {"connections": []}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_accepts_operation_ids_and_rejects_mixed_legacy_policy() -> None:
    request = MagicMock()
    request.app = {INTEGRATION_CACHE_KEY: MagicMock(refresh=AsyncMock(return_value=True))}
    request.match_info = {"id": "gmail_alice"}
    request.json = AsyncMock(return_value={
        "operation_grants": ["email.messages.search"],
        "permissions": {"email": "r"},
    })
    response = await handle_update_integration(request)
    assert response.status == 400

    captured = {}
    request.json = AsyncMock(return_value={
        "operation_grants": ["email.messages.search"],
    })

    async def fake_supervisor_call(verb, args):
        captured.update(args)
        return _supervisor_ok("gmail_alice", "gmail") | {
            "operation_grants": ["email.messages.search"],
            "available_operation_ids": ["email.messages.search"],
        }

    with (
        patch("server._integrations_routes._supervisor_call", side_effect=fake_supervisor_call),
    ):
        response = await handle_update_integration(request)
    assert response.status == 200
    assert captured["operation_grants"] == ["email.messages.search"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconnect_forwards_only_the_existing_id_and_new_credentials() -> None:
    request = MagicMock()
    request.app = {INTEGRATION_CACHE_KEY: MagicMock(refresh=AsyncMock(return_value=True))}
    request.match_info = {"id": "gmail_alice"}
    request.json = AsyncMock(return_value={
        "auth_blob": {"email": "alice@example.com", "password": "new-secret"},
    })
    captured = {}

    async def fake_supervisor_call(verb, args):
        assert verb == "reconnect"
        captured.update(args)
        return _supervisor_ok("gmail_alice", "gmail") | {
            "operation_grants": ["email.messages.search"],
            "available_operation_ids": ["email.messages.search"],
        }

    with (
        patch("server._integrations_routes._supervisor_call", side_effect=fake_supervisor_call),
    ):
        response = await handle_reconnect_integration(request)

    assert response.status == 200
    assert captured == {
        "id": "gmail_alice",
        "kind": "integration",
        "auth_blob": {"email": "alice@example.com", "password": "new-secret"},
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_catalog_projection_does_not_expose_driver_commands_or_secret_bindings() -> None:
    response = await handle_integration_catalog(MagicMock())
    payload = json.loads(response.body)
    assert payload["integrations"]
    assert all("driver" not in entry for entry in payload["integrations"])
    assert all("env_injection" not in entry for entry in payload["integrations"])
    assert all(entry["description"] for entry in payload["integrations"])
    assert all(entry["category"] for entry in payload["integrations"])
    assert any(
        operation["id"] == "http.request"
        for entry in payload["integrations"]
        for operation in entry["operations"]
    )
    google = next(entry for entry in payload["integrations"] if entry["id"] == "google_workspace")
    assert {group["id"] for group in google["operation_groups"]} == {
        "email", "calendar", "drive", "contacts",
    }
    http = next(entry for entry in payload["integrations"] if entry["id"] == "http")
    assert "operation_groups" not in http
