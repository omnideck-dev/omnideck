"""E2E tests: OpenRouter provider field visibility and presets."""

import re

from playwright.sync_api import expect

from tests.e2e.pages import AgentsPage


VISIBLE_FIELDS = ("temperature", "top_p", "num_predict", "max_iterations", "think", "context_window")
HIDDEN_FIELDS = ("top_k", "repeat_penalty")


def test_missing_saved_provider_can_be_replaced_in_picker(page, provider_profile):
    """A stale saved provider must not trap the picker on an unavailable tab."""
    profile_id = provider_profile("test_missing_provider", "openrouter", model="old-model")
    # The disposable suite has one configured provider, Ollama, and no real
    # OpenRouter key. This exercises the same fallback without live credentials.
    providers = page.request.get("/api/providers").json()["providers"]
    assert [provider["name"] for provider in providers] == ["ollama"]
    agents = AgentsPage(page).goto()
    agents.profiles.select(profile_id)
    page.get_by_test_id("model-picker-trigger").click()
    expect(page.get_by_role("button", name="Refresh ollama models")).to_be_visible()
    row = page.get_by_test_id("model-item").first
    expect(row).to_be_visible()
    model_name = row.get_attribute("data-model-name")
    assert page.request.get(f"/api/profiles/{profile_id}").json()["provider"] == "openrouter"
    row.click()
    # Picking changes only the editor draft until Save.
    assert page.request.get(f"/api/profiles/{profile_id}").json()["provider"] == "openrouter"
    with page.expect_response(lambda response: response.url.endswith(f"/api/profiles/{profile_id}")
                              and response.request.method == "PUT") as saved:
        agents.builder.save()
    assert saved.value.ok
    stored = page.request.get(f"/api/profiles/{profile_id}").json()
    assert (stored["provider"], stored["model"]) == ("ollama", model_name)


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
