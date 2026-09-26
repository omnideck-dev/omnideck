"""Tests for agent_runtime._composer_tokens enrichment of `/skill` and `@agent /skill` tokens."""

import pytest

from agent_runtime._composer_tokens import enrich_composer_message
from agents._agent_profiles import save_agent_profile
from agents._agent_profiles import AgentProfile
from skills._store import SkillRecord, save_skill_record


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("skills._store._skills_dir", lambda: tmp_path / "skills")
    monkeypatch.setattr("agents._agent_profiles._profiles_dir", lambda: tmp_path / "agent_profiles")


def _make_skill(name: str, id_: str | None = None) -> SkillRecord:
    record = SkillRecord(id=id_ or name, name=name, description="", prompt="", tool_categories=[])
    return save_skill_record(record)


def _make_profile(name: str, id_: str | None = None, *, enabled: bool = True) -> AgentProfile:
    profile = AgentProfile(id=id_ or name, name=name, enabled=enabled)
    return save_agent_profile(profile)


@pytest.mark.unit
def test_no_tokens_passes_through_unchanged():
    text = "hello, just a plain message with no slashes at all"
    assert enrich_composer_message(text) == text


@pytest.mark.unit
def test_bare_skill_load():
    _make_skill("review-code", id_="skill_review")
    result = enrich_composer_message("/review-code please check this")
    assert "load_skill" in result
    assert 'skill "review-code" (id: skill_review)' in result
    assert "please check this" in result
    assert "Do not spawn a subagent" in result


@pytest.mark.unit
def test_bare_skill_no_args():
    _make_skill("review-code", id_="skill_review")
    result = enrich_composer_message("/review-code")
    assert "load_skill" in result
    assert 'skill "review-code" (id: skill_review)' in result


@pytest.mark.unit
def test_single_delegate():
    _make_skill("review-code", id_="skill_review")
    _make_profile("coder", id_="code_expert")
    result = enrich_composer_message("@coder /review-code myfile.py")
    assert "spawn_agent" in result
    assert 'agent profile "coder" (id: code_expert)' in result
    assert 'skill "review-code" (id: skill_review)' in result
    assert "myfile.py" in result
    assert 'profile="code_expert"' in result


@pytest.mark.unit
def test_chained_delegates():
    _make_skill("create-draft", id_="skill_create")
    _make_skill("review-draft", id_="skill_review_draft")
    _make_profile("writer", id_="writer_profile")
    _make_profile("editor", id_="editor_profile")
    result = enrich_composer_message(
        "@writer /create-draft from mynotes.txt and then @editor /review-draft"
    )
    assert result.index('profile="writer_profile"') < result.index('profile="editor_profile"')
    assert "in order" in result
    assert "mynotes.txt and then" in result
    # The first instruction's closing period must not run directly into the
    # second's opening word — there was exactly one space between the two
    # tokens in the original text and that separation must survive.
    assert '"writer_profile". Spawn a subagent' in result


@pytest.mark.unit
def test_token_at_end_of_message_args_terminate_correctly():
    _make_skill("summarize", id_="skill_sum")
    result = enrich_composer_message("please handle this /summarize")
    # "please handle this" is untouched literal text preceding the token.
    assert result.startswith("please handle this ")
    assert 'skill "summarize" (id: skill_sum)' in result


@pytest.mark.unit
def test_multiline_args_preserved():
    _make_skill("summarize", id_="skill_sum")
    result = enrich_composer_message("/summarize line one\nline two")
    assert "line one\nline two" in result


@pytest.mark.unit
def test_unresolved_skill_is_left_fully_inert():
    """A name that matches no known skill is never a real command — treat it
    as ordinary text, not a typo to explain. This is also what keeps
    incidental text that merely looks like a token (a file path, a URL
    segment) from being misfired into a fabricated instruction."""
    text = "/does-not-exist do something"
    assert enrich_composer_message(text) == text


@pytest.mark.unit
def test_unresolved_agent_is_left_fully_inert():
    _make_skill("review-code", id_="skill_review")
    text = "@ghost /review-code do it"
    assert enrich_composer_message(text) == text


@pytest.mark.unit
def test_disabled_profile_is_left_fully_inert():
    """A disabled profile is excluded from the resolution pool just like an
    unknown one — no special-cased hint, matching the frontend picker never
    offering it either."""
    _make_skill("review-code", id_="skill_review")
    _make_profile("retired", id_="retired_profile", enabled=False)
    text = "@retired /review-code do it"
    assert enrich_composer_message(text) == text


@pytest.mark.unit
def test_path_like_text_is_left_fully_inert():
    """The real-world case the inert rule exists for: an absolute path or
    root-relative URL that happens to parse as a token but names no real
    skill must never be rewritten into a fabricated instruction."""
    text = "check /etc/hosts for the entry, and also look at /home/ron/project/file.py"
    assert enrich_composer_message(text) == text


@pytest.mark.unit
def test_resolves_by_id_as_well_as_name():
    _make_skill("Review Code", id_="skill_review")
    result = enrich_composer_message("/skill_review do it")
    assert 'skill "Review Code" (id: skill_review)' in result


@pytest.mark.unit
def test_whitespace_boundary_ignores_mid_word_slash():
    text = "check a/b path and http://example.com/x for details"
    assert enrich_composer_message(text) == text


@pytest.mark.unit
def test_multiple_tokens_beyond_two():
    _make_skill("s1", id_="skill1")
    _make_skill("s2", id_="skill2")
    _make_skill("s3", id_="skill3")
    result = enrich_composer_message("/s1 a /s2 b /s3 c")
    assert result.count("load_skill") == 3


@pytest.mark.unit
def test_mix_of_resolved_and_unresolved_tokens_in_one_message():
    """Only the resolvable token is rewritten; the unresolved one — and all
    surrounding text — passes through exactly as typed."""
    _make_skill("review-code", id_="skill_review")
    text = "look at /etc/hosts then /review-code it please"
    result = enrich_composer_message(text)
    assert result.startswith("look at /etc/hosts then ")
    assert 'skill "review-code" (id: skill_review)' in result
    assert "it please" in result
