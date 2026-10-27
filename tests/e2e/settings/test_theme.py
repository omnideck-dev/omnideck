"""Agent-driven theme changes, from the tool call through to the rendered UI.

The model is scripted to call the real ``set_theme`` tool. Everything after that is
real: validation, persistence, the generated stylesheet and the browser's refresh.
"""

import ast
import json
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._api import ApiClient
from tests.e2e._helpers import container_exec
from tests.e2e._protocol import call_tool
from tests.e2e._runtime import agent_profile, delete_conversation, run_turn
from tests.e2e.pages import ChatView

CANVAS = "#123456"
CANVAS_RGB = "rgb(18, 52, 86)"
DEFAULT_LIGHT_ACCENT = "#2563eb"
DEFAULT_DARK_CANVAS = "#0c0e14"

_READ_SAVED_THEME = "import json\nfrom theme import get_theme_state\nprint(json.dumps(get_theme_state()['overrides']))"


def saved_theme() -> dict:
    """Overrides as a brand-new interpreter reads them, i.e. what a restarted server would load."""
    return json.loads(container_exec(_READ_SAVED_THEME))


def css_var(page: Page, name: str) -> str:
    return page.evaluate("name => getComputedStyle(document.documentElement).getPropertyValue(name).trim()", name)


def wait_for_theme_applied(page: Page) -> None:
    """Wait until the page has swapped to the versioned stylesheet and dropped the bootstrap link."""
    page.wait_for_function(
        """() => {
            const links = [...document.querySelectorAll('link[rel="stylesheet"]')]
                .filter((l) => (l.getAttribute('href') || '').startsWith('/theme.css'));
            return links.length === 1 && links[0].getAttribute('href').includes('?v=');
        }"""
    )


def set_theme_result(events: list[dict]) -> dict:
    results = [
        e["payload"]
        for e in events
        if e["payload"]["type"] == "tool_result" and e["payload"]["tool_name"] == "set_theme"
    ]
    assert len(results) == 1, events
    # The runtime hands back the tool's return value as its Python repr, not JSON.
    return ast.literal_eval(results[0]["content"])


@pytest.fixture(autouse=True)
def clean_theme():
    """The theme is app-wide state, so every test starts and ends from the default theme."""
    reset = "from theme import update_theme\nupdate_theme(reset=True)"
    container_exec(reset)
    yield
    container_exec(reset)


@pytest.fixture
def agent():
    """Run set_theme/get_theme through the real agent loop and return the parsed tool result."""
    with agent_profile(skills=["assistant"]) as profile:

        def run(**arguments) -> dict:
            conversation = f"e2e_theme_{uuid4().hex}"
            try:
                events = run_turn(conversation, call_tool("set_theme", **arguments), profile_id=profile["id"])
                return set_theme_result(events)
            finally:
                delete_conversation(conversation)

        yield run


def test_a_tool_call_restyles_the_open_app_without_a_reload(page: Page):
    chat = ChatView(page).goto()
    body = page.locator("body")
    expect(body).not_to_have_css("background-color", CANVAS_RGB)
    page.evaluate("window.__stillTheSamePage = true")

    chat.send(call_tool("set_theme", light={"canvas": CANVAS})).wait_streaming()

    expect(body).to_have_css("background-color", CANVAS_RGB)
    assert page.evaluate("window.__stillTheSamePage") is True


def test_a_saved_theme_survives_a_reload_and_a_fresh_process(page: Page, agent):
    result = agent(light={"canvas": CANVAS}, dark={"accent": "#00aa00"}, fonts={"font-code": "monospace"})
    assert result["status"] == "ok"
    expected = {"light": {"canvas": CANVAS}, "dark": {"accent": "#00aa00"}, "fonts": {"font-code": "monospace"}}

    # A separate interpreter reading the file is what a restarted server does on startup.
    assert saved_theme() == expected

    ChatView(page).goto()
    expect(page.locator("body")).to_have_css("background-color", CANVAS_RGB)
    assert css_var(page, "--font-code") == "monospace"


def test_light_and_dark_modes_are_themed_independently(page: Page, agent):
    agent(light={"canvas": CANVAS, "accent": "#aa0000"}, dark={"accent": "#00aa00"})

    ChatView(page).goto()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    assert css_var(page, "--canvas") == CANVAS
    assert css_var(page, "--accent") == "#aa0000"

    page.emulate_media(color_scheme="dark")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    assert css_var(page, "--accent") == "#00aa00"
    # A light-only override must not leak into dark mode.
    assert css_var(page, "--canvas") == DEFAULT_DARK_CANVAS


def test_clearing_one_setting_and_resetting_everything(page: Page, agent):
    agent(light={"canvas": CANVAS, "accent": "#aa0000"}, fonts={"font-body": "Georgia, serif"})

    cleared = agent(light={"accent": None})
    assert cleared["overrides"] == {"light": {"canvas": CANVAS}, "dark": {}, "fonts": {"font-body": "Georgia, serif"}}
    ChatView(page).goto()
    assert css_var(page, "--accent") == DEFAULT_LIGHT_ACCENT
    assert css_var(page, "--canvas") == CANVAS

    restored = agent(reset=True)
    assert restored["overrides"] == {"light": {}, "dark": {}, "fonts": {}}
    assert saved_theme() == {"light": {}, "dark": {}, "fonts": {}}
    page.reload()
    expect(page.locator("body")).not_to_have_css("background-color", CANVAS_RGB)
    assert css_var(page, "--canvas") != CANVAS
    assert "Georgia" not in css_var(page, "--font-body")


def test_invalid_input_is_rejected_and_leaves_the_saved_theme_alone(page: Page, agent):
    agent(light={"canvas": CANVAS})

    result = agent(light={"accent": "purple", "surface": "#eeeeee"}, fonts={"font-body": "Inter; color: red"})

    assert result["status"] == "error"
    assert "light.accent" in result["error"]
    assert "fonts.font-body" in result["error"]
    # The valid part of the rejected update was not applied either.
    assert saved_theme() == {"light": {"canvas": CANVAS}, "dark": {}, "fonts": {}}
    ChatView(page).goto()
    expect(page.locator("body")).to_have_css("background-color", CANVAS_RGB)
    assert css_var(page, "--surface") != "#eeeeee"


def test_a_failed_stylesheet_load_recovers_without_a_reload(page: Page):
    chat = ChatView(page).goto()
    wait_for_theme_applied(page)
    page.evaluate("window.__stillTheSamePage = true")

    refused: list[str] = []

    def fail_first_theme_load(route):
        if refused:
            route.continue_()
            return
        refused.append(route.request.url)
        route.abort()

    page.route("**/theme.css?v=*", fail_first_theme_load)

    chat.send(call_tool("set_theme", light={"canvas": CANVAS})).wait_streaming()

    # The first load of the new theme fails; the app retries by itself and ends up themed.
    expect(page.locator("body")).to_have_css("background-color", CANVAS_RGB, timeout=15_000)
    assert len(refused) == 1
    assert page.evaluate("window.__stillTheSamePage") is True


def test_hand_written_custom_css_is_no_longer_served(api_client: ApiClient):
    container_exec(
        "from config import load_config\n"
        "from pathlib import Path\n"
        "(Path(load_config().settings.home_dir) / 'custom.css').write_text('body { display: none; }')"
    )
    try:
        response = api_client.get("/custom.css")
        assert response.status == 404
        assert "display: none" not in response.text
    finally:
        container_exec(
            "from config import load_config\n"
            "from pathlib import Path\n"
            "(Path(load_config().settings.home_dir) / 'custom.css').unlink(missing_ok=True)"
        )
