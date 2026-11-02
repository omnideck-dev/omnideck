"""Tests for the custom.css route (blank-by-default user style overrides)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from server._ui_routes import _ensure_custom_css, custom_css_handler

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate_custom_css(tmp_path: Path, monkeypatch):
    """Point the custom.css path at a temp file."""
    monkeypatch.setattr(
        "server._ui_routes._custom_css_path",
        lambda: tmp_path / "custom.css",
    )
    return tmp_path / "custom.css"


def _request() -> MagicMock:
    req = MagicMock()
    req.match_info = {}
    req.query = {}
    return req


class TestEnsureCustomCss:
    def test_creates_blank_file_when_missing(self, _isolate_custom_css: Path):
        assert not _isolate_custom_css.exists()
        _ensure_custom_css()
        assert _isolate_custom_css.exists()
        assert _isolate_custom_css.read_text(encoding="utf-8") == ""

    def test_does_not_overwrite_existing_content(self, _isolate_custom_css: Path):
        _isolate_custom_css.parent.mkdir(parents=True, exist_ok=True)
        _isolate_custom_css.write_text(".foo { color: red; }", encoding="utf-8")
        _ensure_custom_css()
        assert _isolate_custom_css.read_text(encoding="utf-8") == ".foo { color: red; }"


async def test_custom_css_handler_creates_and_serves_blank_file(_isolate_custom_css: Path):
    resp = await custom_css_handler(_request())
    assert _isolate_custom_css.exists()
    assert resp._path == _isolate_custom_css
    assert resp.headers["Cache-Control"] == "no-cache"


async def test_custom_css_handler_serves_existing_file(_isolate_custom_css: Path):
    _isolate_custom_css.parent.mkdir(parents=True, exist_ok=True)
    _isolate_custom_css.write_text(".foo { color: red; }", encoding="utf-8")
    resp = await custom_css_handler(_request())
    assert resp._path == _isolate_custom_css
