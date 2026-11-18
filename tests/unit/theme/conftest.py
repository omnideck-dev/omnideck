"""Shared fixtures for the theme subsystem tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def theme_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the saved theme at a temp file so no test touches the real app home."""
    path = tmp_path / "home" / "theme.json"
    monkeypatch.setattr("theme.store.theme_path", lambda: path)
    return path
