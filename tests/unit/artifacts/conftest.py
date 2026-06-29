"""Shared fixtures for artifacts-index unit tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from artifacts import _store, record_artifact


@pytest.fixture()
def vc_home(tmp_path: Path) -> Path:
    """Point the index file and the virtual-computer home at temp dirs.

    Yields the VC home dir so tests can create real files there and exercise
    reconcile / delete / prune against actual on-disk state.
    """
    index_path = tmp_path / "artifacts" / "index.json"
    home = tmp_path / "vc"
    home.mkdir()
    with (
        patch.object(_store, "_index_path", return_value=index_path),
        patch.object(_store, "_vc_home", return_value=home.resolve()),
    ):
        yield home


@pytest.fixture()
def make_file(vc_home: Path):
    """Factory: create a file under the VC home, return its absolute path."""
    def _make(name: str) -> str:
        p = vc_home / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("data", encoding="utf-8")
        return str(p)

    return _make


@pytest.fixture()
def record_file(make_file):
    """Factory: create a file under the VC home and index it; return its path."""
    def _record(conv: str, name: str, *, timestamp: str, filename: str | None = None) -> str:
        path = make_file(name)
        record_artifact(
            conversation_id=conv,
            path=path,
            filename=filename or name,
            content_type="text/markdown",
            agent_name="Claude",
            sent_at=timestamp,
        )
        return path

    return _record
