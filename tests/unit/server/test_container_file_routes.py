"""Tests for the container-home file read/write routes.

The read and write handlers share one home-directory jail: paths that escape
it are forbidden, and both act only on files that already exist. The write
handler additionally overwrites the target with the request body.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from server._container_file_routes import (
    container_file_handler,
    container_file_write_handler,
)


def _make_request(*, path: str, body: bytes | None = None) -> MagicMock:
    """Build a request double carrying a match_info path (and optional body)."""
    req = MagicMock()
    req.match_info = {"path": path}
    if body is not None:
        req.read = AsyncMock(return_value=body)
    return req


def _patch_home(monkeypatch, home) -> None:
    """Point the handlers' config at a temp home directory."""
    cfg = MagicMock()
    cfg.virtual_computer.home_dir = str(home)
    monkeypatch.setattr("server._container_file_routes.load_config", lambda: cfg)


# -- container_file_handler (read) ------------------------------------------


@pytest.mark.unit
async def test_read_serves_existing_file(monkeypatch, tmp_path) -> None:
    """A GET for an existing home file returns a 200 file response."""
    _patch_home(monkeypatch, tmp_path)
    (tmp_path / "notes.md").write_text("hello")

    resp = await container_file_handler(_make_request(path="notes.md"))

    assert resp.status == 200


@pytest.mark.unit
async def test_read_rejects_path_traversal(monkeypatch, tmp_path) -> None:
    """A path escaping the home jail is forbidden."""
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "secret.txt").write_text("keep")
    _patch_home(monkeypatch, home)

    resp = await container_file_handler(_make_request(path="../secret.txt"))

    assert resp.status == 403


@pytest.mark.unit
async def test_read_missing_file_returns_404(monkeypatch, tmp_path) -> None:
    """A GET for a file that does not exist is a 404."""
    _patch_home(monkeypatch, tmp_path)

    resp = await container_file_handler(_make_request(path="nope.txt"))

    assert resp.status == 404


# -- container_file_write_handler (write) -----------------------------------


@pytest.mark.unit
async def test_write_overwrites_existing_file(monkeypatch, tmp_path) -> None:
    """A PUT to an existing home file replaces its bytes and returns ok."""
    _patch_home(monkeypatch, tmp_path)
    target = tmp_path / "notes.md"
    target.write_text("old")

    resp = await container_file_write_handler(
        _make_request(path="notes.md", body=b"# new content")
    )

    assert resp.status == 200
    assert json.loads(resp.body)["ok"] is True
    assert target.read_text() == "# new content"


@pytest.mark.unit
async def test_write_rejects_path_traversal(monkeypatch, tmp_path) -> None:
    """A path escaping the home jail is forbidden and never written."""
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("keep")
    _patch_home(monkeypatch, home)

    resp = await container_file_write_handler(
        _make_request(path="../secret.txt", body=b"hacked")
    )

    assert resp.status == 403
    assert outside.read_text() == "keep"


@pytest.mark.unit
async def test_write_missing_file_returns_404(monkeypatch, tmp_path) -> None:
    """The route edits existing sources; a missing target is a 404, not a create."""
    _patch_home(monkeypatch, tmp_path)

    resp = await container_file_write_handler(
        _make_request(path="does-not-exist.txt", body=b"x")
    )

    assert resp.status == 404
    assert not (tmp_path / "does-not-exist.txt").exists()
