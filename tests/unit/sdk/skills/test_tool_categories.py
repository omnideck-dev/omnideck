"""Unit tests for the tool-category registry.

``tool_categories()`` returns every tool category with the tools it currently
grants: feature-gated static categories carry a fixed tool set, integration
categories resolve against the connected integrations. These cover which static
categories the flags expose, grounding tools following visual grounding, and
integration categories resolving (or staying empty) by connection state.
"""

from types import SimpleNamespace

import pytest

from config import FeaturesConfig
from integrations.permissions import Access, Capability
from sdk.skills._tool_categories import _static_tool_categories, tool_categories
from tools.integrations.types import RegisteredIntegration

_STATIC_IDS = {
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
_INTEGRATION_IDS = {"email", "calendar", "drive", "contacts", "http"}


def _features(**overrides) -> FeaturesConfig:
    base = {
        "image_generation": True,
        "music_generation": True,
        "desktop": True,
        "visual_grounding": True,
        "custom_tools": True,
    }
    base.update(overrides)
    return FeaturesConfig(**base)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Default: all flags on, no integrations connected; static cache cleared per test."""
    _set_flags(monkeypatch)

    async def _none():
        return {}

    monkeypatch.setattr("tools.integrations._tool_resolution.registered_integrations", _none)
    yield
    _static_tool_categories.cache_clear()


def _set_flags(monkeypatch, **overrides):
    monkeypatch.setattr("config.load_config", lambda: SimpleNamespace(features=_features(**overrides)))
    _static_tool_categories.cache_clear()


def _connect(monkeypatch, cap, access=Access.READ):
    async def _get():
        return {"acct-1": RegisteredIntegration(id="acct-1", slug="acct", permissions={cap: access})}

    monkeypatch.setattr("tools.integrations._tool_resolution.registered_integrations", _get)


def _names(tools):
    return {t.__name__ for t in tools}


@pytest.mark.unit
async def test_lists_static_and_integration_categories():
    cats = await tool_categories()
    assert _STATIC_IDS <= set(cats)
    assert _INTEGRATION_IDS <= set(cats)


@pytest.mark.unit
async def test_each_category_has_metadata():
    for c in (await tool_categories()).values():
        assert c.label, f"{c.id} missing label"
        assert c.description, f"{c.id} missing description"


@pytest.mark.unit
async def test_static_category_carries_its_tools():
    coding = (await tool_categories())["coding"]
    assert {"read_file", "run_bash_cmd"} <= _names(coding.tools)


@pytest.mark.unit
@pytest.mark.parametrize("flag", ["desktop", "image_generation", "music_generation", "custom_tools"])
async def test_feature_off_drops_static_category(monkeypatch, flag):
    _set_flags(monkeypatch, **{flag: False})
    cats = await tool_categories()
    assert flag not in cats
    assert "coding" in cats


@pytest.mark.unit
async def test_grounding_tool_follows_visual_grounding(monkeypatch):
    on = _names((await tool_categories())["browser"].tools)
    _set_flags(monkeypatch, visual_grounding=False)
    off = _names((await tool_categories())["browser"].tools)
    assert "browser_visual_action" in on
    assert "browser_visual_action" not in off
    assert "goto" in off


@pytest.mark.unit
async def test_integration_category_empty_when_disconnected():
    email = (await tool_categories())["email"]
    assert email.tools == []


@pytest.mark.unit
async def test_integration_category_resolves_when_connected(monkeypatch):
    _connect(monkeypatch, Capability.EMAIL, Access.READ)
    email = (await tool_categories())["email"]
    names = _names(email.tools)
    assert "search_email" in names
    assert "send_email" not in names  # read tier only


@pytest.mark.unit
async def test_connected_flag_tracks_integration_state(monkeypatch):
    cats = await tool_categories()
    assert cats["coding"].connected is None  # static: no connection concept
    assert cats["email"].connected is False  # integration, nothing connected
    _connect(monkeypatch, Capability.EMAIL, Access.READ)
    assert (await tool_categories())["email"].connected is True


@pytest.mark.unit
async def test_static_categories_built_once():
    # Cached for the process under fixed flags: same object each call.
    assert _static_tool_categories() is _static_tool_categories()
