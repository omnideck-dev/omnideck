"""Unit tests for the tool-category registry.

``tool_categories()`` returns every tool category with the tools it currently
grants: feature-gated static categories carry a fixed tool set, integration
categories resolve against the connected integrations. These cover which static
categories the flags expose, grounding tools following visual grounding, and
integration categories resolving (or staying empty) by connection state.
"""

import inspect
from types import SimpleNamespace

import pytest

from config import FeaturesConfig
from integrations.permissions import Access, Capability
from sdk.agent_capabilities import _base_tools
from sdk.skills._tool_categories import _custom_tools_category
from sdk.skills._tool_categories import _static_tool_categories, tool_categories
from sdk.tools._callable_schema import callable_to_json_schema
from tools.integrations._tool_resolution import _BUILDERS
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
    }
    base.update(overrides)
    return FeaturesConfig(**base)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Default: all flags on, no integrations connected; static cache cleared per test."""
    _set_flags(monkeypatch)
    monkeypatch.setattr("settings.custom_tools_enabled", lambda: True)

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
async def test_agent_tools_have_schema_ready_google_docstrings():
    """Require agent-visible descriptions and Google-style argument docs."""
    exposed_tools = _base_tools(allow_spawn=True, allow_load_skills=True)
    for category in (await tool_categories()).values():
        exposed_tools.extend(category.tools)
    exposed_tools.extend(_custom_tools_category().tools)
    for tiers in _BUILDERS.values():
        for builders in tiers.values():
            exposed_tools.extend(build(["example"]) for build in builders)

    errors: list[str] = []
    for tool in {tool.__name__: tool for tool in exposed_tools}.values():
        signature = inspect.signature(tool)
        missing_types = [
            name for name, parameter in signature.parameters.items()
            if parameter.annotation is inspect.Parameter.empty
        ]
        if missing_types:
            errors.append(f"{tool.__name__}: untyped args: {', '.join(missing_types)}")
        if signature.return_annotation is inspect.Signature.empty:
            errors.append(f"{tool.__name__}: missing return type")
        schema = callable_to_json_schema(tool)["function"]
        if not schema["description"]:
            errors.append(f"{tool.__name__}: missing summary")
        properties = schema["parameters"]["properties"]
        if properties and "Args:" not in (inspect.getdoc(tool) or ""):
            errors.append(f"{tool.__name__}: parameters must use a Google-style Args: section")
        missing_args = [name for name, prop in properties.items() if not prop.get("description")]
        if missing_args:
            errors.append(f"{tool.__name__}: undocumented args: {', '.join(missing_args)}")

    assert not errors, "\n".join(errors)


@pytest.mark.unit
async def test_static_category_carries_its_tools():
    coding = (await tool_categories())["coding"]
    assert {"read_file", "run_bash_cmd"} <= _names(coding.tools)


@pytest.mark.unit
@pytest.mark.parametrize("flag", ["desktop", "image_generation", "music_generation"])
async def test_feature_off_drops_static_category(monkeypatch, flag):
    _set_flags(monkeypatch, **{flag: False})
    cats = await tool_categories()
    assert flag not in cats
    assert "coding" in cats


@pytest.mark.unit
async def test_custom_tools_follows_runtime_setting(monkeypatch):
    """Custom Tools availability changes immediately with its user setting."""
    monkeypatch.setattr("settings.custom_tools_enabled", lambda: False)
    assert "custom_tools" not in await tool_categories()

    monkeypatch.setattr("settings.custom_tools_enabled", lambda: True)
    custom_tools = (await tool_categories())["custom_tools"]
    assert custom_tools.description == "The agent can create, look up, and run reusable tools."


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
