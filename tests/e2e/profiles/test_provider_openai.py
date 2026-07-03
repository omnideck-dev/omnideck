"""E2E tests: OpenAI provider field visibility and presets."""

import re

from playwright.sync_api import expect

from tests.e2e.pages import AgentsPage


VISIBLE_FIELDS = ("temperature", "top_p", "num_predict", "max_iterations", "think")
HIDDEN_FIELDS = ("top_k", "repeat_penalty", "context_window")


def test_openai_field_visibility(page, provider_profile):
    """OpenAI shows universal fields but hides Ollama-only fields."""
    provider_profile("test_prov_openai_vis", "openai")

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_openai_vis")
    agents.builder.open_advanced()

    for name in VISIBLE_FIELDS:
        expect(agents.builder.field(name)).to_be_visible()
    for name in HIDDEN_FIELDS:
        expect(agents.builder.field(name)).not_to_be_attached()


def test_openai_code_preset(page, provider_profile):
    """Code preset on OpenAI sets temperature=0.3 and think=true."""
    provider_profile("test_prov_openai_code", "openai", temperature=0.3, think=True)

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_openai_code")

    expect(agents.builder.preset("Code")).to_have_class(re.compile(r"presetActive"))


def test_openai_reasoning_fields_with_think(page, provider_profile):
    """Reasoning effort and summary dropdowns appear when thinking is enabled."""
    provider_profile("test_prov_openai_reason", "openai", think=True)

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_openai_reason")
    agents.builder.open_advanced()

    expect(agents.builder.field("reasoning_effort")).to_be_visible()
    expect(agents.builder.field("reasoning_summary")).to_be_visible()
    expect(agents.builder.field("thinking_budget")).not_to_be_attached()


def test_openai_reasoning_fields_hidden_without_think(page, provider_profile):
    """Reasoning fields are hidden when thinking is disabled."""
    provider_profile("test_prov_openai_nothink", "openai", think=False)

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_openai_nothink")
    agents.builder.open_advanced()

    expect(agents.builder.field("reasoning_effort")).not_to_be_attached()
    expect(agents.builder.field("reasoning_summary")).not_to_be_attached()
