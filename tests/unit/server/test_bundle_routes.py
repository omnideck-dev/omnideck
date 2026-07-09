"""Tests for server._bundle_routes HTTP handlers.

Export returns a downloadable bundle with a Content-Disposition header; import
accepts a bundle back and creates fresh copies. These cover the option query
params, 404s for unknown items, and rejection of malformed import bodies.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents._agent_profiles import AgentProfile, list_agent_profiles, save_agent_profile
from sdk.skills._store import SkillRecord, list_skill_records, save_skill_record
from server._bundle_routes import (
    handle_export_profile,
    handle_export_skill,
    handle_import_bundle,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agents._agent_profiles._profiles_dir", lambda: tmp_path / "agent_profiles"
    )
    monkeypatch.setattr("sdk.skills._store._skills_dir", lambda: tmp_path / "skills")


def _make_request(*, match_info=None, json_body=None, query=None, json_error=None):
    req = MagicMock()
    req.match_info = match_info or {}
    req.query = query or {}
    if json_error is not None:
        req.json = AsyncMock(side_effect=json_error)
    elif json_body is not None:
        req.json = AsyncMock(return_value=json_body)
    return req


@pytest.mark.unit
async def test_export_profile_unknown_returns_404():
    resp = await handle_export_profile(_make_request(match_info={"id": "nope"}))
    assert resp.status == 404


@pytest.mark.unit
async def test_export_profile_downloads_bundle_with_attachment_header():
    save_agent_profile(AgentProfile(id="researcher", name="Researcher", system_prompt="hi"))
    resp = await handle_export_profile(_make_request(match_info={"id": "researcher"}))
    assert resp.status == 200
    assert "attachment" in resp.headers["Content-Disposition"]
    assert ".omnideck.agent" in resp.headers["Content-Disposition"]
    bundle = json.loads(resp.body)
    assert bundle["profiles"][0]["system_prompt"] == "hi"


@pytest.mark.unit
async def test_export_profile_include_skills_and_exclude_model():
    save_skill_record(SkillRecord(id="coder", name="Coder"))
    save_agent_profile(
        AgentProfile(id="r", name="R", provider="anthropic", model="claude-x", skills=["coder"])
    )
    req = _make_request(
        match_info={"id": "r"},
        query={"include_skills": "true", "include_model": "false"},
    )
    resp = await handle_export_profile(req)
    bundle = json.loads(resp.body)
    assert bundle["profiles"][0]["provider"] == ""
    assert bundle["profiles"][0]["model"] == ""
    assert {s["id"] for s in bundle["skills"]} == {"coder"}


@pytest.mark.unit
async def test_export_skill_unknown_returns_404():
    resp = await handle_export_skill(_make_request(match_info={"id": "nope"}))
    assert resp.status == 404


@pytest.mark.unit
async def test_export_skill_downloads_bundle():
    save_skill_record(SkillRecord(id="coder", name="Coder", prompt="Write code."))
    resp = await handle_export_skill(_make_request(match_info={"id": "coder"}))
    assert resp.status == 200
    assert ".omnideck.skill" in resp.headers["Content-Disposition"]
    bundle = json.loads(resp.body)
    assert bundle["skills"][0]["prompt"] == "Write code."


@pytest.mark.unit
async def test_import_invalid_json_returns_400():
    req = _make_request(json_error=json.JSONDecodeError("x", "", 0))
    resp = await handle_import_bundle(req)
    assert resp.status == 400


@pytest.mark.unit
async def test_import_empty_bundle_returns_400():
    resp = await handle_import_bundle(_make_request(json_body={"kind": "omnideck.bundle"}))
    assert resp.status == 400
    assert "empty" in json.loads(resp.body)["error"].lower()


@pytest.mark.unit
async def test_import_foreign_kind_returns_400():
    req = _make_request(json_body={"kind": "evil", "skills": [{"id": "x", "name": "X"}]})
    resp = await handle_import_bundle(req)
    assert resp.status == 400


@pytest.mark.unit
async def test_import_creates_profiles_and_skills():
    body = {
        "kind": "omnideck.bundle",
        "version": 1,
        "profiles": [{"id": "r", "name": "Researcher", "skills": ["coder"]}],
        "skills": [{"id": "coder", "name": "Coder"}],
    }
    resp = await handle_import_bundle(_make_request(json_body=body))
    assert resp.status == 201
    summary = json.loads(resp.body)
    assert len(summary["profiles"]) == 1
    assert len(summary["skills"]) == 1
    # Persisted with fresh ids and the reference remapped.
    assert len(list_agent_profiles(include_disabled=True)) == 1
    assert len(list_skill_records()) == 1
    assert summary["profiles"][0]["skills"] == [summary["skills"][0]["id"]]
