"""Tests for the application entry point."""

from __future__ import annotations

import importlib
import sys

import pytest

import browser.runtime


@pytest.mark.unit
def test_main_imports_browser_shutdown_from_public_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """The entry point resolves shutdown through the Browser runtime API."""
    runtime_close_browser = object()
    monkeypatch.setattr(browser.runtime, "close_browser", runtime_close_browser)
    sys.modules.pop("main", None)

    try:
        main_module = importlib.import_module("main")
        assert main_module.close_browser is runtime_close_browser
    finally:
        sys.modules.pop("main", None)
