"""E2E tests: OpenAI provider field visibility and presets."""

import re

from playwright.sync_api import expect

from tests.e2e.pages import AgentsPage


VISIBLE_FIELDS = ("temperature", "top_p", "num_predict", "max_iterations", "thinking-level")
HIDDEN_FIELDS = ("top_k", "repeat_penalty", "context_window")


def test_openai_field_visibility(page, provider_profile):
    """OpenAI shows universal fields and a thinking level but hides Ollama-only fields."""
    provider_profile("test_prov_openai_vis", "openai")

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_openai_vis")
    agents.builder.open_advanced()

    for name in VISIBLE_FIELDS:
        expect(agents.builder.field(name)).to_be_visible()
    for name in HIDDEN_FIELDS:
        expect(agents.builder.field(name)).not_to_be_attached()


def test_openai_code_preset_saves_no_sampling_while_thinking(page, provider_profile, save_profile):
    """Code turns reasoning on, so it must not keep sampling values the Responses API refuses."""
    profile_id = provider_profile("test_prov_openai_code", "openai", temperature=0.7)

    agents = AgentsPage(page).goto()
    agents.profiles.select(profile_id)
    expect(agents.builder.preset("Balanced")).to_have_class(re.compile(r"presetActive"))

    agents.builder.preset("Code").click()

    expect(agents.builder.preset("Code")).to_have_class(re.compile(r"presetActive"))
    expect(agents.builder.field("temperature")).not_to_be_attached()
    expect(agents.builder.field("top_p")).not_to_be_attached()
    stored = save_profile(agents, profile_id)
    assert stored.get("think") is True
    assert stored.get("reasoning_effort") == "medium"
    assert stored.get("temperature") is None
    assert stored.get("top_p") is None


def test_openai_reasoning_fields_with_think(page, provider_profile):
    """With thinking on, the level and summary show and sampling fields hide."""
    provider_profile("test_prov_openai_reason", "openai", think=True)

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_openai_reason")
    agents.builder.open_advanced()

    expect(page.get_by_test_id("thinking-level-select")).to_have_attribute("data-value", "medium")
    expect(agents.builder.field("reasoning_summary")).to_be_visible()
    expect(agents.builder.field("temperature")).not_to_be_attached()
    expect(agents.builder.field("top_p")).not_to_be_attached()


def test_openai_reasoning_fields_hidden_without_think(page, provider_profile):
    """Without thinking, the level reads Automatic and the summary is hidden."""
    provider_profile("test_prov_openai_nothink", "openai", think=False)

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_openai_nothink")
    agents.builder.open_advanced()

    expect(page.get_by_test_id("thinking-level-select")).to_have_attribute("data-value", "automatic")
    expect(agents.builder.field("reasoning_summary")).not_to_be_attached()
