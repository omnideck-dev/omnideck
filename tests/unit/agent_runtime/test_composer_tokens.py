"""Tests for agent_runtime._composer_tokens shortcut resolution and effects."""

import json
from pathlib import Path

import pytest

from agent_core.agent_capabilities import AgentCapabilities
from agent_core.skills import Skill
from agent_runtime._composer_tokens import (
    LoadSkill,
    _match_skill,
    apply_composer_effects,
    resolve_composer_effects,
)
from agents import AgentProfile
from skills._store import SkillRecord, save_skill_record

pytestmark = [pytest.mark.unit]

PROFILE = AgentProfile(id="root", name="Root")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("skills._store._skills_dir", lambda: tmp_path / "skills")


def _make_skill(name: str, id_: str | None = None) -> SkillRecord:
    record = SkillRecord(id=id_ or name, name=name, description="", prompt="", tool_categories=[])
    return save_skill_record(record)


def _loaded_ids(text: str, profile: AgentProfile = PROFILE) -> list[str]:
    return [effect.record.id for effect in resolve_composer_effects(text, profile)]


# ── resolution ──────────────────────────────────────────────────────────


def test_no_tokens_has_no_effects():
    assert _loaded_ids("hello, just a plain message with no slashes at all") == []


def test_skill_token_anywhere_in_the_message():
    _make_skill("review-code", id_="skill_review")
    assert _loaded_ids("/review-code please check this") == ["skill_review"]
    assert _loaded_ids("Fix the auth bug in login.py using /review-code") == ["skill_review"]


def test_bare_token():
    _make_skill("Joke teller", id_="4dffecbf8559")
    assert _loaded_ids("/joke-teller") == ["4dffecbf8559"]


def test_several_tokens_in_message_order():
    _make_skill("summarize", id_="skill_sum")
    _make_skill("review-code", id_="skill_review")
    assert _loaded_ids("/review-code main.py then /summarize it") == ["skill_review", "skill_sum"]


def test_repeated_token_loads_once():
    _make_skill("summarize", id_="skill_sum")
    assert _loaded_ids("/summarize a and /summarize b") == ["skill_sum"]


def test_path_like_text_has_no_effect():
    """A path that parses as a token but names no skill is never a command."""
    _make_skill("hosts", id_="skill_hosts")
    assert _loaded_ids("check /etc/hosts and also /home/ron/project/file.py") == []


def test_whitespace_boundary_ignores_mid_word_slash():
    _make_skill("b", id_="skill_b")
    assert _loaded_ids("check a/b and http://example.com/b for details") == []


def test_reserved_skill_has_no_effect():
    _make_skill("browser", id_="browser")
    assert _loaded_ids("/browser open the page") == []


def test_profile_that_cannot_load_skills_has_no_effects():
    _make_skill("review-code", id_="skill_review")
    profile = AgentProfile(id="locked", name="Locked", allow_load_skills=False)
    assert _loaded_ids("/review-code do it", profile) == []


def test_at_and_hash_are_not_tokens_yet():
    _make_skill("coder", id_="skill_coder")
    _make_skill("tag", id_="skill_tag")
    assert _loaded_ids("@coder #tag hello") == []


# ── applying effects ────────────────────────────────────────────────────


def _runtime_skill(record: SkillRecord) -> Skill:
    return Skill(id=record.id, name=record.name, description="", prompt="p", tools=[])


@pytest.fixture
def published(monkeypatch):
    events = []
    monkeypatch.setattr("agent_runtime._composer_tokens.publish_event", lambda event: events.append(event.payload))
    return events


async def test_apply_loads_the_skill_and_reports_it(published):
    record = _make_skill("Joke teller", id_="4dffecbf8559")

    async def resolver(name):
        return _runtime_skill(record) if name == record.name else None

    capabilities = AgentCapabilities([], skill_resolver=resolver)
    await apply_composer_effects([LoadSkill(record)], capabilities)

    assert capabilities.loaded_skill_ids == frozenset({"4dffecbf8559"})
    assert [(p.skill_id, p.skill_name, p.status) for p in published] == [
        ("4dffecbf8559", "Joke teller", "loaded"),
    ]


async def test_apply_reports_an_already_attached_skill(published):
    record = _make_skill("coder", id_="coder")
    capabilities = AgentCapabilities([])
    capabilities.add(_runtime_skill(record))

    await apply_composer_effects([LoadSkill(record)], capabilities)

    assert capabilities.loaded_skill_ids == frozenset()
    assert [p.status for p in published] == ["already_loaded"]


async def test_apply_reports_a_skill_that_no_longer_resolves(published):
    record = _make_skill("gone", id_="gone")

    async def resolver(_name):
        return None

    capabilities = AgentCapabilities([], skill_resolver=resolver)
    await apply_composer_effects([LoadSkill(record)], capabilities)

    assert capabilities.skill_ids == frozenset()
    assert [p.status for p in published] == ["unavailable"]


# ── shared cases, also run by the composer ──────────────────────────────


_SHARED = json.loads((Path(__file__).parents[2] / "fixtures" / "composer_skill_matching.json").read_text())
_SHARED_SKILLS = [
    SkillRecord(id=s["id"], name=s["name"], description="", prompt="", tool_categories=[])
    for s in _SHARED["skills"]
]


@pytest.mark.parametrize("case", _SHARED["cases"], ids=lambda c: c["ref"])
def test_shared_matching_cases(case):
    match = _match_skill(case["ref"], _SHARED_SKILLS)
    assert (match.id if match else None) == case["expect"], case["why"]
