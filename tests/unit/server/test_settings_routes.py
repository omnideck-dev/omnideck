"""Tests for the settings API route handlers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import server._settings_routes as settings_routes
from server._settings_routes import handle_get_settings


@pytest.mark.unit
async def test_settings_include_the_output_limit_each_helper_role_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_routes, "load_settings", lambda: {"vision_model": "m"})

    response = await handle_get_settings(MagicMock())

    body = json.loads(response.body)
    assert body["vision_model"] == "m"
    assert body["utility_output_caps"] == {"vision": 512, "compaction": 8192, "title": 50}
