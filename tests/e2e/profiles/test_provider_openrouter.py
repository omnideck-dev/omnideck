"""E2E tests: OpenRouter provider field visibility and presets."""

import re

from playwright.sync_api import expect

from tests.e2e.pages import AgentsPage


VISIBLE_FIELDS = ("temperature", "top_p", "num_predict", "max_iterations", "think", "context_window")
HIDDEN_FIELDS = ("top_k", "repeat_penalty")


def test_openrouter_field_visibility(page, provider_profile):
    """OpenRouter shows think toggle but hides Ollama-only fields."""
    provider_profile("test_prov_or_vis", "openrouter")

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_or_vis")
    agents.builder.open_advanced()

    for name in VISIBLE_FIELDS:
        expect(agents.builder.field(name)).to_be_visible()
    for name in HIDDEN_FIELDS:
        expect(agents.builder.field(name)).not_to_be_attached()


def test_openrouter_code_preset(page, provider_profile):
    """Code preset on OpenRouter sets temperature=0.3 and think=true."""
    provider_profile("test_prov_or_code", "openrouter", temperature=0.3, think=True)

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_or_code")

    expect(agents.builder.preset("Code")).to_have_class(re.compile(r"presetActive"))


def test_openrouter_reasoning_fields_with_think(page, provider_profile):
    """OpenRouter shows reasoning_effort when think is enabled."""
    provider_profile("test_prov_or_reason", "openrouter", think=True)

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_or_reason")
    agents.builder.open_advanced()

    expect(agents.builder.field("reasoning_effort")).to_be_visible()
    expect(agents.builder.field("reasoning_summary")).not_to_be_attached()
    expect(agents.builder.field("thinking_budget")).not_to_be_attached()
