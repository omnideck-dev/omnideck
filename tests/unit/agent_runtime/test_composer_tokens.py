"""Tests for agent_runtime._composer_tokens shortcut resolution."""

import pytest

from agent_runtime._composer_tokens import resolve_composer_tokens
from agents._agent_profiles import AgentProfile
from skills._store import SkillRecord, save_skill_record

pytestmark = [pytest.mark.unit]

PROFILE = AgentProfile(id="root", name="Root")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("skills._store._skills_dir", lambda: tmp_path / "skills")


def _make_skill(name: str, id_: str | None = None) -> SkillRecord:
    record = SkillRecord(id=id_ or name, name=name, description="", prompt="", tool_categories=[])
    return save_skill_record(record)


def _resolve(text: str, profile: AgentProfile = PROFILE) -> str | None:
    return resolve_composer_tokens(text, profile)


def test_no_tokens_returns_none():
    assert _resolve("hello, just a plain message with no slashes at all") is None


def test_bare_skill_load():
    _make_skill("review-code", id_="skill_review")
    result = _resolve("/review-code please check this")
    assert "load_skill" in result
    assert 'skill "review-code" (id: skill_review)' in result
    assert "please check this" in result
    assert "Do not spawn a subagent" in result


def test_bare_skill_no_args_asks_for_output_not_a_status_report():
    """With nothing typed after the token, the instruction must steer the
    model toward delivering the skill's actual output, not toward reporting
    on whether the load worked."""
    _make_skill("review-code", id_="skill_review")
    result = _resolve("/review-code")
    assert "respond with what it produces, not a report on whether it loaded" in result


def test_text_before_the_token_is_kept():
    _make_skill("summarize", id_="skill_sum")
    result = _resolve("please handle this /summarize")
    assert result.startswith("please handle this ")
    assert 'skill "summarize" (id: skill_sum)' in result


def test_multiline_args_preserved():
    _make_skill("summarize", id_="skill_sum")
    assert "line one\nline two" in _resolve("/summarize line one\nline two")


def test_unresolved_skill_is_left_fully_inert():
    assert _resolve("/does-not-exist do something") is None


def test_path_like_text_is_left_fully_inert():
    """A path that parses as a token but names no skill is never a command."""
    assert _resolve("check /etc/hosts and also /home/ron/project/file.py") is None


def test_unresolved_token_after_a_skill_stays_in_its_task():
    """A path in the task text must not cut the task off from the skill."""
    _make_skill("summarize", id_="skill_sum")
    result = _resolve("/summarize /tmp/report.txt please")
    assert "then use it to: /tmp/report.txt please." in result
    assert "in order" not in result


def test_unresolved_token_before_a_skill_passes_through():
    _make_skill("review-code", id_="skill_review")
    result = _resolve("look at /etc/hosts then /review-code it please")
    assert result.startswith("look at /etc/hosts then ")
    assert "then use it to: it please." in result


def test_whitespace_boundary_ignores_mid_word_slash():
    _make_skill("b", id_="skill_b")
    assert _resolve("check a/b and http://example.com/b for details") is None


def test_resolves_by_id_as_well_as_name():
    _make_skill("Review Code", id_="skill_review")
    assert 'skill "Review Code" (id: skill_review)' in _resolve("/skill_review do it")


def test_resolves_skill_by_slug_of_multiword_name():
    _make_skill("Joke teller", id_="4dffecbf8559")
    assert 'skill "Joke teller" (id: 4dffecbf8559)' in _resolve("/joke-teller tell me one")


def test_ambiguous_skill_slug_is_left_fully_inert():
    _make_skill("Joke teller", id_="skill_a")
    _make_skill("joke   TELLER!!", id_="skill_b")
    assert _resolve("/joke-teller tell me one") is None


def test_reserved_skill_is_left_fully_inert():
    _make_skill("browser", id_="browser")
    assert _resolve("/browser open the page") is None


def test_profile_that_cannot_load_skills_gets_no_rewrite():
    _make_skill("review-code", id_="skill_review")
    profile = AgentProfile(id="locked", name="Locked", allow_load_skills=False)
    assert _resolve("/review-code do it", profile) is None


def test_chained_skills_get_sequencing_instruction():
    _make_skill("create-draft", id_="skill_create")
    _make_skill("review-draft", id_="skill_review_draft")
    result = _resolve("/create-draft from mynotes.txt and then /review-draft")
    assert result.index("skill_create") < result.index("skill_review_draft")
    assert "in order" in result
    assert "mynotes.txt and then" in result
    # The single space between the tokens survives, so the two rendered
    # instructions don't run together.
    assert "in this conversation. Load skill" in result


def test_multiple_tokens_beyond_two():
    for i in (1, 2, 3):
        _make_skill(f"s{i}", id_=f"skill{i}")
    assert _resolve("/s1 a /s2 b /s3 c").count("load_skill") == 3


def test_at_and_hash_are_not_tokens_yet():
    _make_skill("review-code", id_="skill_review")
    _make_skill("tag", id_="skill_tag")
    result = _resolve("@coder #tag /review-code myfile.py")
    assert result.startswith("@coder #tag Load skill")
