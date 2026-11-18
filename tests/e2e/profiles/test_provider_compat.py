"""E2E tests: OpenAI-compatible provider field visibility and presets."""

import re

from playwright.sync_api import expect

from tests.e2e.pages import AgentsPage


VISIBLE_FIELDS = ("temperature", "top_p", "num_predict", "max_iterations", "thinking-level")
HIDDEN_FIELDS = ("top_k", "repeat_penalty", "context_window")


def test_compat_field_visibility(page, provider_profile):
    """OpenAI-compat shows basic fields and a thinking level, hides Ollama-only fields."""
    provider_profile("test_prov_compat_vis", "openai_compat")

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_compat_vis")
    agents.builder.open_advanced()

    for name in VISIBLE_FIELDS:
        expect(agents.builder.field(name)).to_be_visible()
    for name in HIDDEN_FIELDS:
        expect(agents.builder.field(name)).not_to_be_attached()


def test_compat_code_preset(page, provider_profile):
    """Code preset on openai_compat sets temperature=0.3 and thinking at the default level."""
    provider_profile("test_prov_compat_code", "openai_compat", temperature=0.3, think=True)

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_compat_code")

    expect(agents.builder.preset("Code")).to_have_class(re.compile(r"presetActive"))


def test_compat_reasoning_fields_with_think(page, provider_profile):
    """OpenAI-compat shows the thinking level at its default when thinking is on."""
    provider_profile("test_prov_compat_reason", "openai_compat", think=True)

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_compat_reason")
    agents.builder.open_advanced()

    expect(page.get_by_test_id("thinking-level-select")).to_have_attribute("data-value", "medium")
    expect(agents.builder.field("reasoning_summary")).not_to_be_attached()
    # Chat Completions keeps sampling while reasoning.
    expect(agents.builder.field("temperature")).to_be_visible()
