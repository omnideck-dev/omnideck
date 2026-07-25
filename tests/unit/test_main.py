"""Tests for the application entry point."""

from __future__ import annotations

import importlib
import sys

import pytest

import tools.browser


@pytest.mark.unit
def test_main_imports_browser_shutdown_from_public_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """The entry point resolves shutdown through the package facade."""
    facade_close_browser = object()
    monkeypatch.setattr(tools.browser, "close_browser", facade_close_browser)
    sys.modules.pop("main", None)

    try:
        main_module = importlib.import_module("main")
        assert main_module.close_browser is facade_close_browser
    finally:
        sys.modules.pop("main", None)
