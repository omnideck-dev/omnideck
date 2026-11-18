"""E2E tests: Anthropic provider field visibility and presets."""

import re

from playwright.sync_api import expect

from tests.e2e.pages import AgentsPage


VISIBLE_FIELDS = ("temperature", "top_k", "top_p", "num_predict", "max_iterations", "thinking-level")
HIDDEN_FIELDS = ("repeat_penalty", "context_window")


def test_anthropic_field_visibility(page, provider_profile):
    """Anthropic shows top_k and a thinking level but no context window or repeat penalty."""
    provider_profile("test_prov_anth_vis", "anthropic")

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_anth_vis")
    agents.builder.open_advanced()

    for name in VISIBLE_FIELDS:
        expect(agents.builder.field(name)).to_be_visible()
    for name in HIDDEN_FIELDS:
        expect(agents.builder.field(name)).not_to_be_attached()


def test_anthropic_code_preset_saves_no_temperature_while_thinking(page, provider_profile, save_profile):
    """Code turns thinking on, so it must not keep a temperature Claude refuses."""
    profile_id = provider_profile("test_prov_anth_code", "anthropic", temperature=0.7)

    agents = AgentsPage(page).goto()
    agents.profiles.select(profile_id)
    expect(agents.builder.preset("Balanced")).to_have_class(re.compile(r"presetActive"))

    agents.builder.preset("Code").click()

    expect(agents.builder.preset("Code")).to_have_class(re.compile(r"presetActive"))
    expect(agents.builder.field("temperature")).not_to_be_attached()
    stored = save_profile(agents, profile_id)
    assert stored.get("think") is True
    assert stored.get("temperature") is None


def test_anthropic_thinking_clears_temperature_and_top_k(page, provider_profile, save_profile):
    """Choosing a thinking level hides and clears the values Claude refuses while thinking."""
    profile_id = provider_profile("test_prov_anth_think", "anthropic", temperature=0.5, top_k=40, top_p=0.9)

    agents = AgentsPage(page).goto()
    agents.profiles.select(profile_id)
    agents.builder.open_advanced()
    expect(agents.builder.field("temperature")).to_have_value("0.5")

    page.get_by_test_id("thinking-level-select").click()
    page.locator('[role="option"][data-value="standard"]').click()

    expect(agents.builder.field("temperature")).not_to_be_attached()
    expect(agents.builder.field("top_k")).not_to_be_attached()
    expect(agents.builder.field("top_p")).to_have_value("0.9")
    stored = save_profile(agents, profile_id)
    assert stored.get("think") is True
    assert stored.get("thinking_budget") == "standard"
    assert stored.get("temperature") is None
    assert stored.get("top_k") is None
    assert stored.get("top_p") == 0.9


def test_anthropic_thinking_level_offers_off_and_budgets(page, provider_profile):
    """The thinking level offers Off plus the token budgets."""
    provider_profile("test_prov_anth_budget", "anthropic", think=True)

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_anth_budget")
    agents.builder.open_advanced()

    select = page.get_by_test_id("thinking-level-select")
    expect(select).to_have_attribute("data-value", "standard")
    select.click()
    options = page.get_by_role("option")
    expect(options).to_have_count(4)
    for value in ("off", "minimal", "standard", "extended"):
        expect(page.locator(f'[role="option"][data-value="{value}"]')).to_be_visible()
    expect(agents.builder.field("reasoning_summary")).not_to_be_attached()


def test_anthropic_max_output_placeholder(page, provider_profile):
    """Max Output shows the typical Anthropic limit when the model does not report one."""
    provider_profile("test_prov_anth_placeholder", "anthropic")

    agents = AgentsPage(page).goto()
    agents.profiles.select("test_prov_anth_placeholder")
    agents.builder.open_advanced()

    expect(agents.builder.field("num_predict")).to_have_attribute("placeholder", "auto (16,384 typical)")
