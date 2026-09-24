"""Tests for setup API route handlers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import server._setup_routes as setup_routes
from server._setup_routes import handle_complete, handle_defaults


@pytest.mark.unit
async def test_setup_defaults_returns_ollama_host_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "  http://host-gateway:11434  ")

    resp = await handle_defaults(MagicMock())

    assert resp.status == 200
    assert json.loads(resp.body)["ollama_host"] == "http://host-gateway:11434"


@pytest.mark.unit
async def test_setup_defaults_returns_null_without_ollama_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    resp = await handle_defaults(MagicMock())

    assert resp.status == 200
    assert json.loads(resp.body)["ollama_host"] is None


@pytest.mark.unit
def test_welcome_payload_respects_deleted_or_archived_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_artifacts = MagicMock()
    monkeypatch.setattr(setup_routes, "conversation_exists", lambda _conversation_id: False)
    monkeypatch.setattr(setup_routes, "list_artifacts", list_artifacts)

    assert setup_routes._welcome_startup_payload() is None
    list_artifacts.assert_not_called()


@pytest.mark.unit
async def test_repeated_setup_completion_does_not_offer_welcome_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = MagicMock()
    request.json = AsyncMock(return_value={
        "provider": "ollama",
        "main_model": "test-model",
    })
    request.app = {}
    welcome_payload = MagicMock()

    monkeypatch.setattr(setup_routes, "load_settings", lambda: {"setup_complete": True})
    monkeypatch.setattr(setup_routes, "get_provider", lambda _provider: object())
    monkeypatch.setattr(setup_routes, "save_settings", lambda values: values)
    monkeypatch.setattr(setup_routes, "apply_llm_config_to_profiles", MagicMock())
    monkeypatch.setattr(setup_routes, "mark_ready", MagicMock())
    monkeypatch.setattr(setup_routes, "_welcome_startup_payload", welcome_payload)

    response = await handle_complete(request)

    assert response.status == 200
    assert json.loads(response.body)["welcome"] is None
    welcome_payload.assert_not_called()
