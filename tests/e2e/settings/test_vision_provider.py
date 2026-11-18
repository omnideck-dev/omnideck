"""E2E tests: provider-aware visibility for vision advanced settings."""

from playwright.sync_api import Page, expect

from tests.e2e.pages import SettingsPage


def _set_vision_provider(page: Page, provider: str) -> None:
    """Switch which provider drives the vision advanced panel's field visibility."""
    page.request.put("/api/settings", data={"vision_provider": provider})


def test_ollama_shows_all_vision_options(page: Page):
    """All vision option fields are visible when vision runs on Ollama."""
    _set_vision_provider(page, "ollama")
    settings = SettingsPage(page).goto_system()
    settings.system.open_vision_advanced()

    for key in ("temperature", "top_k", "top_p", "num_ctx", "num_predict"):
        expect(settings.system.vision_option(key)).to_be_visible()


def test_openai_hides_top_k_and_num_ctx(page: Page):
    """OpenAI does not support top_k or num_ctx for vision."""
    _set_vision_provider(page, "openai")

    try:
        settings = SettingsPage(page).goto_system()
        settings.system.open_vision_advanced()

        for key in ("temperature", "top_p", "num_predict"):
            expect(settings.system.vision_option(key)).to_be_visible()

        for key in ("top_k", "num_ctx"):
            expect(settings.system.vision_option(key)).not_to_be_attached()
    finally:
        _set_vision_provider(page, "ollama")


def test_anthropic_shows_top_k_hides_num_ctx(page: Page):
    """Anthropic supports top_k but not num_ctx."""
    _set_vision_provider(page, "anthropic")

    try:
        settings = SettingsPage(page).goto_system()
        settings.system.open_vision_advanced()

        for key in ("temperature", "top_k", "top_p", "num_predict"):
            expect(settings.system.vision_option(key)).to_be_visible()

        expect(settings.system.vision_option("num_ctx")).not_to_be_attached()
    finally:
        _set_vision_provider(page, "ollama")


def test_anthropic_vision_thinking_clears_temperature(page: Page):
    """Turning vision thinking on removes the temperature older Claude models refuse."""
    original_model = page.request.get("/api/settings").json()["vision_model"]
    # The wizard's vision model cannot think, so use the fake model that can.
    page.request.put("/api/settings", data={
        "vision_provider": "anthropic",
        "vision_model": "kimi-k2.5:cloud",
        "vision_think": False,
        "vision_options": {"temperature": 0.5, "top_p": 0.9},
    })

    try:
        settings = SettingsPage(page).goto_system()
        settings.system.open_vision_advanced()
        expect(settings.system.vision_option("temperature")).to_have_value("0.5")

        with page.expect_response(
            lambda r: r.url.endswith("/api/settings") and r.request.method == "PUT",
        ) as saved:
            page.get_by_role("combobox", name="Vision thinking level").click()
            page.locator('[role="option"][data-value="standard"]').click()
        assert saved.value.ok

        expect(settings.system.vision_option("temperature")).not_to_be_attached()
        expect(settings.system.vision_option("top_k")).not_to_be_attached()
        expect(settings.system.vision_option("top_p")).to_have_value("0.9")

        stored = page.request.get("/api/settings").json()
        assert stored["vision_think"] is True
        assert stored["vision_options"].get("temperature") is None
        assert stored["vision_options"]["top_p"] == 0.9
    finally:
        page.request.put("/api/settings", data={
            "vision_provider": "ollama",
            "vision_model": original_model,
            "vision_think": False,
            "vision_options": {},
        })
