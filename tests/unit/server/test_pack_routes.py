"""Tests for the pack export/import HTTP handlers.

Export returns a downloadable pack with a Content-Disposition header; import
accepts one back and creates fresh copies. These cover the option query params,
404s for unknown items, the download filename, and rejection of malformed
uploads.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents._agent_profiles import AgentProfile, list_agent_profiles, save_agent_profile
from sdk.skills._store import SkillRecord, list_skill_records, save_skill_record
from server._pack_routes import (
    _slug,
    handle_export_profile,
    handle_export_skill,
    handle_import_pack,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agents._agent_profiles._profiles_dir", lambda: tmp_path / "agent_profiles"
    )
    monkeypatch.setattr("sdk.skills._store._skills_dir", lambda: tmp_path / "skills")


def _make_request(*, match_info=None, json_body=None, query=None, raw_body=None):
    """Build a stub request. Import reads the raw uploaded bytes, not parsed JSON."""
    req = MagicMock()
    req.match_info = match_info or {}
    req.query = query or {}
    if raw_body is not None:
        req.read = AsyncMock(return_value=raw_body)
    elif json_body is not None:
        req.read = AsyncMock(return_value=json.dumps(json_body).encode())
    return req


@pytest.mark.unit
async def test_export_profile_unknown_returns_404():
    resp = await handle_export_profile(_make_request(match_info={"id": "nope"}))
    assert resp.status == 404


@pytest.mark.unit
async def test_export_profile_downloads_pack_with_attachment_header():
    save_agent_profile(AgentProfile(id="researcher", name="Researcher", system_prompt="hi"))
    resp = await handle_export_profile(_make_request(match_info={"id": "researcher"}))
    assert resp.status == 200
    disposition = resp.headers["Content-Disposition"]
    assert "attachment" in disposition
    assert 'filename="Researcher.agent.omnideck.json"' in disposition
    pack = json.loads(resp.body)
    assert pack["profiles"][0]["system_prompt"] == "hi"


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
    pack = json.loads(resp.body)
    assert pack["profiles"][0]["provider"] == ""
    assert pack["profiles"][0]["model"] == ""
    assert {s["id"] for s in pack["skills"]} == {"coder"}


@pytest.mark.unit
async def test_export_profile_rejects_non_boolean_option():
    save_agent_profile(AgentProfile(id="r", name="R"))
    req = _make_request(match_info={"id": "r"}, query={"include_skills": "maybe"})
    resp = await handle_export_profile(req)
    assert resp.status == 400


@pytest.mark.unit
async def test_export_skill_unknown_returns_404():
    resp = await handle_export_skill(_make_request(match_info={"id": "nope"}))
    assert resp.status == 404


@pytest.mark.unit
async def test_export_skill_downloads_pack():
    save_skill_record(SkillRecord(id="coder", name="Coder", prompt="Write code."))
    resp = await handle_export_skill(_make_request(match_info={"id": "coder"}))
    assert resp.status == 200
    assert 'filename="Coder.skill.omnideck.json"' in resp.headers["Content-Disposition"]
    pack = json.loads(resp.body)
    assert pack["skills"][0]["prompt"] == "Write code."


@pytest.mark.unit
def test_slug_replaces_dots_so_only_structural_dots_remain():
    assert _slug("v1.2 Researcher") == "v1-2-Researcher"


@pytest.mark.unit
def test_slug_does_not_produce_a_dotfile():
    assert _slug(".hidden") == "hidden"


@pytest.mark.unit
def test_slug_falls_back_when_nothing_survives():
    assert _slug("!!!") == "pack"


@pytest.mark.unit
def test_slug_caps_length_without_leaving_a_trailing_separator():
    stem = _slug("a" * 60 + " " + "b" * 40)
    assert len(stem) <= 64
    assert not stem.endswith("-")


@pytest.mark.unit
async def test_import_unparseable_bytes_returns_400():
    resp = await handle_import_pack(_make_request(raw_body=b"not json {"))
    assert resp.status == 400


@pytest.mark.unit
async def test_import_non_utf8_bytes_returns_400():
    # An uploaded binary file reaches the handler as raw bytes that never decode.
    resp = await handle_import_pack(_make_request(raw_body=b"\xff\xfe\x00\x01"))
    assert resp.status == 400


@pytest.mark.unit
async def test_import_empty_body_returns_400():
    resp = await handle_import_pack(_make_request(raw_body=b""))
    assert resp.status == 400


@pytest.mark.unit
async def test_import_empty_pack_returns_400():
    resp = await handle_import_pack(_make_request(json_body={"kind": "omnideck.pack"}))
    assert resp.status == 400
    assert "no agents or skills" in json.loads(resp.body)["error"].lower()


@pytest.mark.unit
async def test_import_foreign_kind_returns_400():
    req = _make_request(json_body={"kind": "evil", "skills": [{"id": "x", "name": "X"}]})
    resp = await handle_import_pack(req)
    assert resp.status == 400


@pytest.mark.unit
async def test_import_creates_profiles_and_skills():
    body = {
        "kind": "omnideck.pack",
        "version": 1,
        "profiles": [{"id": "r", "name": "Researcher", "skills": ["coder"]}],
        "skills": [{"id": "coder", "name": "Coder"}],
    }
    resp = await handle_import_pack(_make_request(json_body=body))
    assert resp.status == 201
    summary = json.loads(resp.body)
    assert len(summary["profiles"]) == 1
    assert len(summary["skills"]) == 1
    # Persisted with fresh ids and the reference remapped.
    assert len(list_agent_profiles(include_disabled=True)) == 1
    assert len(list_skill_records()) == 1
    assert summary["profiles"][0]["skills"] == [summary["skills"][0]["id"]]
