"""Tests for agent_runtime._composer_effects: applying composer skill selections."""

import pytest

from agent_core.agent_capabilities import AgentCapabilities
from agent_core.skills import Skill
from agent_runtime import SkillContextRef
from agent_runtime._composer_effects import LoadSkill, apply_composer_effects, composer_effects
from skills._store import SkillRecord, save_skill_record

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("skills._store._skills_dir", lambda: tmp_path / "skills")


@pytest.fixture
def published(monkeypatch):
    events = []
    monkeypatch.setattr("agent_runtime._composer_effects.publish_event", lambda event: events.append(event.payload))
    return events


def _make_skill(name: str, id_: str) -> SkillRecord:
    return save_skill_record(SkillRecord(id=id_, name=name, description="", prompt="", tool_categories=[]))


def _runtime_skill(record: SkillRecord) -> Skill:
    return Skill(id=record.id, name=record.name, description="", prompt="p", tools=[])


def _capabilities(*records: SkillRecord) -> AgentCapabilities:
    by_name = {record.name: record for record in records}

    async def resolver(name):
        return _runtime_skill(by_name[name]) if name in by_name else None

    return AgentCapabilities([], skill_resolver=resolver)


def test_effects_keep_selection_order_and_drop_repeats():
    a, b = SkillContextRef("a", "A"), SkillContextRef("b", "B")
    effects = composer_effects([a, b, a])
    assert effects == [LoadSkill(a), LoadSkill(b)]


async def test_selected_skill_is_loaded_and_reported(published):
    record = _make_skill("Joke teller", "4dffecbf8559")
    capabilities = _capabilities(record)

    await apply_composer_effects(composer_effects([SkillContextRef("4dffecbf8559", "Joke teller")]), capabilities)

    assert capabilities.loaded_skill_ids == frozenset({"4dffecbf8559"})
    assert [(p.skill_id, p.skill_name, p.status) for p in published] == [("4dffecbf8559", "Joke teller", "loaded")]


async def test_loading_is_by_id_and_records_the_current_name(published):
    """Two skills may share a name up to case; the selected id decides, and
    history records the skill's name as it was when loaded."""
    _make_skill("Foo", "skill_upper")
    lower = _make_skill("foo", "skill_lower")
    capabilities = _capabilities(lower)

    await apply_composer_effects(composer_effects([SkillContextRef("skill_lower", "an older label")]), capabilities)

    assert capabilities.loaded_skill_ids == frozenset({"skill_lower"})
    assert published[0].skill_name == "foo"


async def test_already_attached_skill_is_not_loaded_again(published):
    record = _make_skill("coder", "coder")
    capabilities = _capabilities(record)
    capabilities.add(_runtime_skill(record))

    await apply_composer_effects(composer_effects([SkillContextRef("coder", "coder")]), capabilities)

    assert capabilities.loaded_skill_ids == frozenset()
    assert [p.status for p in published] == ["already_loaded"]


async def test_missing_skill_is_reported_with_the_name_the_user_saw(published):
    capabilities = _capabilities()

    await apply_composer_effects(composer_effects([SkillContextRef("gone", "Deleted skill")]), capabilities)

    assert capabilities.skill_ids == frozenset()
    assert [(p.skill_name, p.status) for p in published] == [("Deleted skill", "unavailable")]


async def test_reserved_skill_is_never_loaded(published):
    record = _make_skill("browser", "browser")
    capabilities = _capabilities(record)

    await apply_composer_effects(composer_effects([SkillContextRef("browser", "browser")]), capabilities)

    assert capabilities.skill_ids == frozenset()
    assert [p.status for p in published] == ["unavailable"]
