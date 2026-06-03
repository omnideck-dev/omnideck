"""Unit tests for build_categories.

build_categories returns the categories available under a set of feature flags,
keyed by id, each carrying its own tools. These cover which categories the flags
expose, that each carries real callables and catalog metadata, and that the
local-grounding tools appear only when visual grounding is on.
"""

import pytest

from config import FeaturesConfig
from sdk.tools._categories import build_categories, get_categories

_ALL_IDS = {
    "coding",
    "browser",
    "webfetch",
    "memory",
    "planning",
    "image_generation",
    "music_generation",
    "desktop",
    "custom_tools",
}


def _features(**overrides) -> FeaturesConfig:
    """A FeaturesConfig with every gate on unless overridden."""
    base = {
        "image_generation": True,
        "music_generation": True,
        "desktop": True,
        "visual_grounding": True,
        "custom_tools": True,
    }
    base.update(overrides)
    return FeaturesConfig(**base)


@pytest.mark.unit
def test_all_categories_present_when_features_enabled() -> None:
    assert set(build_categories(_features())) == _ALL_IDS


@pytest.mark.unit
@pytest.mark.parametrize("flag", ["desktop", "image_generation", "music_generation", "custom_tools"])
def test_feature_off_drops_its_category(flag: str) -> None:
    ids = set(build_categories(_features(**{flag: False})))
    assert flag not in ids
    assert "coding" in ids


@pytest.mark.unit
def test_each_category_has_metadata_and_callable_tools() -> None:
    for c in build_categories(_features()).values():
        assert c.label, f"{c.id} missing label"
        assert c.description, f"{c.id} missing description"
        assert c.tools, f"{c.id} has no tools"
        assert all(callable(t) for t in c.tools)


@pytest.mark.unit
def test_coding_category_contains_expected_tools() -> None:
    coding = build_categories(_features())["coding"]
    names = {t.__name__ for t in coding.tools}
    assert {"read_file", "run_bash_cmd"} <= names


@pytest.mark.unit
def test_browser_grounding_tool_follows_visual_grounding() -> None:
    on = {t.__name__ for t in build_categories(_features(visual_grounding=True))["browser"].tools}
    off = {t.__name__ for t in build_categories(_features(visual_grounding=False))["browser"].tools}
    assert "browser_visual_action" in on
    assert "browser_visual_action" not in off
    assert "goto" in off


@pytest.mark.unit
def test_desktop_grounding_tool_follows_visual_grounding() -> None:
    on = {t.__name__ for t in build_categories(_features(visual_grounding=True))["desktop"].tools}
    off = {t.__name__ for t in build_categories(_features(visual_grounding=False))["desktop"].tools}
    assert "perform_visual_action" in on
    assert "perform_visual_action" not in off
    assert "mouse_click" in off


@pytest.mark.unit
def test_custom_tools_category_present_only_when_feature_on() -> None:
    on = build_categories(_features(custom_tools=True))
    assert "custom_tools" in on
    assert {t.__name__ for t in on["custom_tools"].tools} == {
        "create_custom_tool",
        "lookup_custom_tools",
        "run_custom_tool",
    }
    assert "custom_tools" not in build_categories(_features(custom_tools=False))


@pytest.mark.unit
def test_get_categories_is_built_once_and_held() -> None:
    # Memoized for the process: the same object is returned each call.
    assert get_categories() is get_categories()
