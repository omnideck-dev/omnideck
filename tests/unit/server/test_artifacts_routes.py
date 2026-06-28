"""Tests for the artifacts hub HTTP handlers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from artifacts import record_artifact
from server._artifacts_routes import (
    delete_artifact_handler,
    list_artifacts_handler,
    prune_missing_handler,
)


@pytest.fixture()
def vc_home(tmp_path: Path, monkeypatch) -> Path:
    """Point the artifacts index and VC home at temp dirs."""
    index_path = tmp_path / "artifacts" / "index.json"
    home = tmp_path / "vc"
    home.mkdir()
    monkeypatch.setattr("artifacts._store._index_path", lambda: index_path)
    monkeypatch.setattr("artifacts._store._vc_home", lambda: home.resolve())
    return home


def _seed(home: Path, conv: str, name: str) -> str:
    """Create a file under the VC home and index it; return its path."""
    p = home / name
    p.write_text("data", encoding="utf-8")
    record_artifact(
        conversation_id=conv, path=str(p), filename=name,
        content_type="text/markdown", agent_name="Claude", sent_at="2026-01-01T00:00:00",
    )
    return str(p)


def _request(*, query: dict | None = None, match: dict | None = None) -> MagicMock:
    """Build a minimal aiohttp.web.Request double (query + match_info only)."""
    req = MagicMock()
    req.query = query or {}
    req.match_info = match or {}
    return req


def _body(resp) -> dict:
    return json.loads(resp.body)


pytestmark = pytest.mark.unit


# ── GET /api/artifacts ────────────────────────────────────────────────────────

async def test_list_all(vc_home: Path) -> None:
    _seed(vc_home, "c1", "a.md")
    _seed(vc_home, "c2", "b.md")
    resp = await list_artifacts_handler(_request())
    artifacts = _body(resp)["artifacts"]
    assert len(artifacts) == 2
    assert {a["status"] for a in artifacts} == {"present"}


async def test_list_scoped_by_conversation(vc_home: Path) -> None:
    _seed(vc_home, "c1", "a.md")
    _seed(vc_home, "c2", "b.md")
    resp = await list_artifacts_handler(_request(query={"conversation_id": "c1"}))
    artifacts = _body(resp)["artifacts"]
    assert [a["conversation_id"] for a in artifacts] == ["c1"]


async def test_reconcile_marks_missing(vc_home: Path) -> None:
    _seed(vc_home, "c1", "here.md")
    gone = _seed(vc_home, "c1", "gone.md")
    Path(gone).unlink()
    resp = await list_artifacts_handler(_request())
    statuses = {a["filename"]: a["status"] for a in _body(resp)["artifacts"]}
    assert statuses == {"here.md": "present", "gone.md": "missing"}


# ── DELETE /api/artifacts/{id} ────────────────────────────────────────────────

async def test_delete_entry_only_keeps_file(vc_home: Path) -> None:
    path = _seed(vc_home, "c1", "keep.md")
    artifact_id = _body(await list_artifacts_handler(_request()))["artifacts"][0]["id"]
    resp = await delete_artifact_handler(_request(match={"artifact_id": artifact_id}))
    assert resp.status == 204
    assert _body(await list_artifacts_handler(_request()))["artifacts"] == []
    assert Path(path).is_file()


async def test_delete_with_file_unlinks(vc_home: Path) -> None:
    path = _seed(vc_home, "c1", "remove.md")
    artifact_id = _body(await list_artifacts_handler(_request()))["artifacts"][0]["id"]
    resp = await delete_artifact_handler(
        _request(match={"artifact_id": artifact_id}, query={"delete_file": "true"}),
    )
    assert resp.status == 204
    assert not Path(path).exists()


async def test_delete_unknown_id_returns_404(vc_home: Path) -> None:
    resp = await delete_artifact_handler(_request(match={"artifact_id": "nope"}))
    assert resp.status == 404


# ── POST /api/artifacts/prune-missing ─────────────────────────────────────────

async def test_prune_removes_only_missing(vc_home: Path) -> None:
    _seed(vc_home, "c1", "here.md")
    gone = _seed(vc_home, "c1", "gone.md")
    Path(gone).unlink()
    resp = await prune_missing_handler(_request())
    assert _body(resp) == {"removed": 1}
    remaining = _body(await list_artifacts_handler(_request()))["artifacts"]
    assert [a["filename"] for a in remaining] == ["here.md"]


async def test_prune_scoped_by_conversation(vc_home: Path) -> None:
    g1 = _seed(vc_home, "c1", "g1.md")
    g2 = _seed(vc_home, "c2", "g2.md")
    Path(g1).unlink()
    Path(g2).unlink()
    resp = await prune_missing_handler(_request(query={"conversation_id": "c1"}))
    assert _body(resp) == {"removed": 1}
    remaining = _body(await list_artifacts_handler(_request()))["artifacts"]
    assert {a["conversation_id"] for a in remaining} == {"c2"}
