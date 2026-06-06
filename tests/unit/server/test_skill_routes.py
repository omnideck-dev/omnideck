"""Tests for server._skill_routes HTTP handlers.

CRUD over /api/skills keyed by ``id``: create generates an id, rename via PUT
keeps the id, a name already in use is rejected, and delete works on any saved
record (starters included).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from sdk.skills._store import SkillRecord, save_skill_record
from server._skill_routes import (
    handle_create_skill,
    handle_delete_skill,
    handle_get_skill,
    handle_list_skills,
    handle_update_skill,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Point the skill store at a temp directory."""
    monkeypatch.setattr("sdk.skills._store._skills_dir", lambda: tmp_path / "skills")


def _make_request(*, match_info=None, json_body=None, query=None):
    """Build a minimal aiohttp.web.Request-ish double."""
    req = MagicMock()
    req.match_info = match_info or {}
    req.query = query or {}
    if json_body is not None:
        req.json = AsyncMock(return_value=json_body)
    return req


@pytest.mark.unit
async def test_create_generates_id_and_returns_201():
    req = _make_request(json_body={"name": "Coder", "prompt": "Write code.", "tool_categories": ["coding"]})
    resp = await handle_create_skill(req)
    assert resp.status == 201
    body = json.loads(resp.body)
    assert body["id"]  # server-generated, non-empty
    assert body["name"] == "Coder"
    assert body["tool_categories"] == ["coding"]


@pytest.mark.unit
async def test_create_honors_explicit_id():
    req = _make_request(json_body={"id": "coder", "name": "Coder"})
    resp = await handle_create_skill(req)
    assert resp.status == 201
    assert json.loads(resp.body)["id"] == "coder"


@pytest.mark.unit
async def test_create_duplicate_name_rejected():
    save_skill_record(SkillRecord(id="coder", name="Coder"))
    req = _make_request(json_body={"name": "Coder"})
    resp = await handle_create_skill(req)
    assert resp.status == 400
    assert "in use" in json.loads(resp.body)["error"].lower()


@pytest.mark.unit
async def test_create_invalid_json_returns_400():
    req = MagicMock()
    req.json = AsyncMock(side_effect=json.JSONDecodeError("x", "", 0))
    resp = await handle_create_skill(req)
    assert resp.status == 400


@pytest.mark.unit
async def test_list_returns_saved_skills():
    save_skill_record(SkillRecord(id="a", name="Alpha"))
    save_skill_record(SkillRecord(id="b", name="Beta"))
    resp = await handle_list_skills(_make_request())
    body = json.loads(resp.body)
    assert {r["id"] for r in body} == {"a", "b"}


@pytest.mark.unit
async def test_get_returns_record():
    save_skill_record(SkillRecord(id="coder", name="Coder", prompt="Write code."))
    resp = await handle_get_skill(_make_request(match_info={"id": "coder"}))
    assert resp.status == 200
    assert json.loads(resp.body)["prompt"] == "Write code."


@pytest.mark.unit
async def test_get_unknown_returns_404():
    resp = await handle_get_skill(_make_request(match_info={"id": "nope"}))
    assert resp.status == 404


@pytest.mark.unit
async def test_update_renames_and_keeps_id():
    save_skill_record(SkillRecord(id="coder", name="Coder"))
    req = _make_request(match_info={"id": "coder"}, json_body={"name": "Renamed"})
    resp = await handle_update_skill(req)
    assert resp.status == 200
    body = json.loads(resp.body)
    assert body["id"] == "coder"
    assert body["name"] == "Renamed"


@pytest.mark.unit
async def test_update_unknown_returns_404():
    req = _make_request(match_info={"id": "ghost"}, json_body={"name": "Ghost"})
    resp = await handle_update_skill(req)
    assert resp.status == 404


@pytest.mark.unit
async def test_update_duplicate_name_rejected():
    save_skill_record(SkillRecord(id="coder", name="Coder"))
    save_skill_record(SkillRecord(id="browser", name="Browser"))
    req = _make_request(match_info={"id": "browser"}, json_body={"name": "Coder"})
    resp = await handle_update_skill(req)
    assert resp.status == 400


@pytest.mark.unit
async def test_delete_returns_204():
    save_skill_record(SkillRecord(id="coder", name="Coder"))
    resp = await handle_delete_skill(_make_request(match_info={"id": "coder"}))
    assert resp.status == 204


@pytest.mark.unit
async def test_delete_unknown_returns_404():
    resp = await handle_delete_skill(_make_request(match_info={"id": "ghost"}))
    assert resp.status == 404
