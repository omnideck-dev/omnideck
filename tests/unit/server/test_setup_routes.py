"""Tests for setup API route handlers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server._setup_routes import handle_defaults


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
