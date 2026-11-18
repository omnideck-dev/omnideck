"""Tests for migration 017: give ``assistant`` the ``theme`` category and its prompt guidance."""

import json

import pytest

from migrations._017_grant_theme_tools import migrate


def _write_assistant(state_dir, **fields):
    skills = state_dir / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    record = {"id": "assistant", "name": "assistant", "prompt": "hi", "tool_categories": ["memory"], **fields}
    (skills / "assistant.json").write_text(json.dumps(record), encoding="utf-8")


def _read_assistant(state_dir):
    return json.loads((state_dir / "skills" / "assistant.json").read_text(encoding="utf-8"))


@pytest.mark.unit
def test_appends_theme_to_assistant(tmp_path):
    _write_assistant(tmp_path, tool_categories=["memory", "email"])
    migrate(tmp_path)
    assert _read_assistant(tmp_path)["tool_categories"] == ["memory", "email", "theme"]


@pytest.mark.unit
def test_appends_the_guidance_after_the_existing_prompt(tmp_path):
    _write_assistant(tmp_path, prompt="my edited prompt")
    migrate(tmp_path)
    prompt = _read_assistant(tmp_path)["prompt"]
    assert prompt.startswith("my edited prompt\n\nTHEME")
    assert "get_theme" in prompt
    assert "set_theme" in prompt
    assert "never guess names" in prompt


@pytest.mark.unit
def test_leaves_other_fields_alone(tmp_path):
    _write_assistant(tmp_path, description="mine", name="my assistant")
    migrate(tmp_path)
    record = _read_assistant(tmp_path)
    assert record["description"] == "mine"
    assert record["name"] == "my assistant"
    assert record["id"] == "assistant"


@pytest.mark.unit
def test_guidance_is_added_when_the_category_was_already_granted(tmp_path):
    """Installs that got the category from an earlier build still lack the instructions."""
    _write_assistant(tmp_path, tool_categories=["memory", "theme"], prompt="hi")
    migrate(tmp_path)
    record = _read_assistant(tmp_path)
    assert record["tool_categories"] == ["memory", "theme"]
    assert "set_theme" in record["prompt"]


@pytest.mark.unit
def test_category_is_added_when_the_prompt_already_explains_the_tools(tmp_path):
    _write_assistant(tmp_path, prompt="Use set_theme for appearance requests.")
    migrate(tmp_path)
    record = _read_assistant(tmp_path)
    assert record["prompt"] == "Use set_theme for appearance requests."
    assert record["tool_categories"] == ["memory", "theme"]


@pytest.mark.unit
def test_a_complete_record_is_not_rewritten(tmp_path):
    _write_assistant(tmp_path, tool_categories=["theme", "memory"], prompt="Use set_theme for the look.")
    path = tmp_path / "skills" / "assistant.json"
    before = path.read_text(encoding="utf-8")
    migrate(tmp_path)
    assert path.read_text(encoding="utf-8") == before


@pytest.mark.unit
def test_running_twice_adds_the_guidance_once(tmp_path):
    _write_assistant(tmp_path)
    migrate(tmp_path)
    once = _read_assistant(tmp_path)
    migrate(tmp_path)
    twice = _read_assistant(tmp_path)
    assert twice == once
    assert twice["prompt"].count("THEME") == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("existing", "separator"),
    [("one line", "\n\n"), ("ends with one newline\n", "\n"), ("ends with a blank line\n\n", "")],
)
def test_the_existing_prompt_is_kept_exactly_and_the_paragraph_is_separated(tmp_path, existing, separator):
    _write_assistant(tmp_path, prompt=existing)
    migrate(tmp_path)
    prompt = _read_assistant(tmp_path)["prompt"]
    assert prompt.startswith(existing + separator + "THEME")


@pytest.mark.unit
@pytest.mark.parametrize("empty", ["", "   \n"])
def test_an_empty_prompt_becomes_just_the_guidance(tmp_path, empty):
    _write_assistant(tmp_path, prompt=empty)
    migrate(tmp_path)
    assert _read_assistant(tmp_path)["prompt"].startswith("THEME")


@pytest.mark.unit
def test_a_record_without_a_prompt_gets_one(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "assistant.json").write_text(
        json.dumps({"id": "assistant", "name": "assistant", "tool_categories": ["memory"]}), encoding="utf-8"
    )
    migrate(tmp_path)
    record = _read_assistant(tmp_path)
    assert record["prompt"].startswith("THEME")
    assert record["tool_categories"] == ["memory", "theme"]


@pytest.mark.unit
def test_deleted_assistant_stays_deleted(tmp_path):
    (tmp_path / "skills").mkdir()
    migrate(tmp_path)
    assert not (tmp_path / "skills" / "assistant.json").exists()


@pytest.mark.unit
def test_no_skills_dir_is_noop(tmp_path):
    migrate(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.unit
@pytest.mark.parametrize("contents", ["{not json", "[]", '"a string"'])
def test_corrupt_or_unexpected_record_is_skipped(tmp_path, contents):
    (tmp_path / "skills").mkdir()
    path = tmp_path / "skills" / "assistant.json"
    path.write_text(contents, encoding="utf-8")
    migrate(tmp_path)
    assert path.read_text(encoding="utf-8") == contents


@pytest.mark.unit
def test_shipped_assistant_default_grants_theme_and_explains_it():
    """Fresh installs get both from the shipped record, not the migration."""
    from pathlib import Path

    shipped = Path(__file__).parents[3] / "agent_core" / "skills" / "default_skills" / "assistant.json"
    record = json.loads(shipped.read_text(encoding="utf-8"))
    assert "theme" in record["tool_categories"]
    assert "get_theme" in record["prompt"]
    assert "set_theme" in record["prompt"]
