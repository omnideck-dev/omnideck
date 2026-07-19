"""End-to-end coverage for Custom Apps."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import ChatView

_TEST_APP_FILES = {
    "omnideck.json": """{"title":"Text Lab","description":"E2E fixture","icon":"bi-fonts"}""",
    "app.py": """import re

from custom_apps import action

@action
def analyze(text: str):
    words = re.findall(r"\\b[\\w'-]+\\b", text)
    return {"words": len(words)}
""",
    "web/index.html": """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Text Lab</title>
    <link rel="stylesheet" href="app.css">
  </head>
  <body>
    <h1>Text Lab</h1>
    <textarea id="text">The simplest useful app should feel like a folder you can open.</textarea>
    <button id="analyze">Analyze</button>
    <button id="ask-agent">Ask agent about this</button>
    <div id="status">Ready</div>
    <div id="metrics" hidden><span>Words</span> <strong id="words"></strong></div>
    <script src="/api/custom-apps/sdk.js"></script>
    <script src="app.js"></script>
  </body>
</html>
""",
    "web/app.css": """body { font-family: sans-serif; }""",
    "web/app.js": """const text = document.querySelector('#text');

document.querySelector('#analyze').addEventListener('click', async () => {
  const result = await window.omnideck.invoke('analyze', { text: text.value });
  document.querySelector('#words').textContent = result.words;
  document.querySelector('#metrics').hidden = false;
  document.querySelector('#status').textContent = 'Analysis complete';
});

document.querySelector('#ask-agent').addEventListener('click', () => {
  window.omnideck.chat.compose({
    text: 'Help me improve this text while preserving its intent:',
    context: { text: text.value },
  });
});
""",
}


@pytest.fixture()
def installed_custom_app(page: Page):
    """Install Text Lab only for this test; it is not a packaged app."""
    container_exec(
        "from pathlib import Path\n"
        f"files = {_TEST_APP_FILES!r}\n"
        "root = Path('/home/omnideck/apps/text-lab')\n"
        "for name, content in files.items():\n"
        "    path = root / name\n"
        "    path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    path.write_text(content, encoding='utf-8')\n"
        "Path('/home/omnideck/custom-app-alpha.txt').write_text('read from home', encoding='utf-8')"
    )
    try:
        yield
    finally:
        page.request.put("/api/settings", data={"custom_apps_enabled": True})
        page.request.delete("/api/custom-apps/home")
        page.request.put("/api/settings", data={"custom_apps_enabled": False})
        container_exec(
            "import shutil\n"
            "from pathlib import Path\n"
            "shutil.rmtree('/home/omnideck/apps/text-lab', ignore_errors=True)\n"
            "Path('/home/omnideck/custom-app-alpha.txt').unlink(missing_ok=True)"
        )


def _open_custom_apps_library(page: Page) -> None:
    """Enable Custom Apps and open the app library from a fresh shell."""
    response = page.request.put("/api/settings", data={"custom_apps_enabled": True})
    assert response.ok
    ChatView(page).goto()
    expect(page.get_by_test_id("sidebar-nav-apps")).to_be_visible()
    page.get_by_test_id("sidebar-nav-apps").click()
    expect(page.get_by_test_id("apps-view")).to_be_visible()
    expect(page.get_by_text("Text Lab", exact=True)).to_be_visible()


def _expect_app_beside_chat(page: Page) -> None:
    """Assert the shared chat/Custom App workspace is active."""
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()
    expect(page.get_by_test_id("preview-tab-app:text-lab")).to_be_visible()
    expect(
        page.frame_locator('[data-testid="custom-app-frame"]').get_by_role("heading", name="Text Lab")
    ).to_be_visible()


def test_custom_app_opening_matrix_full_space(page: Page, installed_custom_app) -> None:
    """An app can open by itself, then move beside the current chat without remounting."""
    _open_custom_apps_library(page)

    page.get_by_test_id("custom-app-card").click()
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()
    expect(page.get_by_test_id("custom-app-back")).to_be_visible()
    expect(page.get_by_test_id("chat-title-bar")).not_to_be_visible()
    expect(page.get_by_test_id("preview-tab-app:text-lab")).not_to_be_visible()

    working_text = "Full-space state survives the move beside chat."
    frame.locator("#text").fill(working_text)
    page.get_by_test_id("custom-app-chat").click()

    _expect_app_beside_chat(page)
    expect(frame.locator("#text")).to_have_value(working_text)


def test_custom_app_opening_matrix_beside_chat(page: Page, installed_custom_app) -> None:
    """An app can open directly beside chat, survive a new chat, and close globally."""
    _open_custom_apps_library(page)

    page.get_by_test_id("custom-app-open-split-text-lab").click()
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    _expect_app_beside_chat(page)

    working_text = "Direct split state survives a new conversation."
    frame.locator("#text").fill(working_text)
    page.get_by_test_id("sidebar-new-chat").click()

    _expect_app_beside_chat(page)
    expect(frame.locator("#text")).to_have_value(working_text)

    page.get_by_test_id("close-tab-app:text-lab").click()
    expect(page.get_by_test_id("preview-tab-app:text-lab")).not_to_be_visible()
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()


def test_custom_app_opening_matrix_home(page: Page, installed_custom_app) -> None:
    """A Home app opens full-space and can move beside chat and back Home."""
    assert page.request.put("/api/settings", data={"custom_apps_enabled": True}).ok
    assert page.request.put("/api/custom-apps/home", data={"slug": "text-lab"}).ok

    ChatView(page).goto()
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    expect(page.get_by_test_id("home-view")).to_be_visible()
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()
    expect(page.get_by_test_id("home-app-remove")).to_be_visible()
    expect(page.get_by_test_id("chat-title-bar")).not_to_be_visible()
    expect(page.get_by_test_id("preview-tab-app:text-lab")).not_to_be_visible()

    working_text = "Home state survives full and split navigation."
    frame.locator("#text").fill(working_text)
    page.get_by_test_id("custom-app-chat").click()

    _expect_app_beside_chat(page)
    expect(frame.locator("#text")).to_have_value(working_text)

    page.get_by_test_id("sidebar-nav-home").click()
    expect(page.get_by_test_id("home-app-remove")).to_be_visible()
    expect(page.get_by_test_id("chat-title-bar")).not_to_be_visible()
    expect(page.get_by_test_id("preview-tab-app:text-lab")).not_to_be_visible()
    expect(frame.locator("#text")).to_have_value(working_text)


def test_custom_app_opens_and_invokes_python(page: Page, installed_custom_app) -> None:
    """The shell lists an installed app, opens its frame, and bridges an action."""
    page.request.put("/api/settings", data={"custom_apps_enabled": False})
    ChatView(page).goto()

    # Custom Apps is a user setting, not an environment-level feature flag.
    expect(page.get_by_test_id("sidebar-nav-apps")).not_to_be_visible()
    page.get_by_test_id("sidebar-settings").click()
    page.get_by_test_id("settings-tab-system").click()
    custom_apps_toggle = page.get_by_role("switch", name="Custom Apps")
    expect(custom_apps_toggle).not_to_be_checked()
    page.get_by_test_id("custom-apps-toggle").click()
    expect(custom_apps_toggle).to_be_checked()
    expect(page.get_by_test_id("sidebar-nav-apps")).to_be_visible()

    page.get_by_test_id("sidebar-nav-apps").click()
    expect(page.get_by_test_id("apps-view")).to_be_visible()
    expect(page.get_by_text("Text Lab", exact=True)).to_be_visible()

    page.get_by_test_id("custom-app-card").click()
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()

    # Trusted apps can use the existing container-home file route directly.
    home_text = frame.locator("body").evaluate(
        "async () => (await fetch('/home/omnideck/custom-app-alpha.txt')).text()"
    )
    assert home_text == "read from home"
    write_status = frame.locator("body").evaluate(
        """async () => (await fetch('/home/omnideck/custom-app-alpha.txt', {
            method: 'PUT',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            body: 'written by app',
        })).status"""
    )
    assert write_status == 200
    assert page.request.get("/home/omnideck/custom-app-alpha.txt").text() == "written by app"

    frame.get_by_role("button", name="Analyze").click()

    expect(frame.get_by_text("Analysis complete")).to_be_visible()
    expect(frame.get_by_text("Words", exact=True)).to_be_visible()
    expect(frame.get_by_text("12", exact=True)).to_be_visible()

    # The app can explicitly open the existing chat and seed its composer.
    working_text = "This state should survive full, split, and a new conversation."
    frame.locator("#text").fill(working_text)
    frame.get_by_role("button", name="Ask agent about this").click()
    expect(page.get_by_test_id("preview-tab-app:text-lab")).to_be_visible()
    expect(page.locator("textarea").first).to_have_value(re.compile(re.escape(working_text)))
    expect(frame.locator("#text")).to_have_value(working_text)

    # A new conversation clears conversation previews, not the shell-scoped app.
    page.get_by_test_id("sidebar-new-chat").click()
    expect(page.get_by_test_id("preview-tab-app:text-lab")).to_be_visible()
    expect(frame.locator("#text")).to_have_value(working_text)

    # Split-view tabs can reload frontend files without refreshing Omnideck.
    page.get_by_test_id("custom-app-tab-reload").click()
    expect(frame.locator("#text")).to_have_value("The simplest useful app should feel like a folder you can open.")

    # Closing the app removes its global tab and leaves Chat full-space.
    page.get_by_test_id("close-tab-app:text-lab").click()
    expect(page.get_by_test_id("preview-tab-app:text-lab")).not_to_be_visible()
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()

    # Reopen full-space before assigning it as Home.
    page.get_by_test_id("sidebar-nav-apps").click()
    page.get_by_test_id("custom-app-card").click()
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()

    # Docking persists the app as Home; a full reload should land there.
    page.get_by_test_id("custom-app-home-toggle").click()
    expect(page.get_by_test_id("custom-app-home-toggle")).to_contain_text("Remove from Home")
    page.reload()

    expect(page.get_by_test_id("home-view")).to_be_visible()
    home_frame = page.frame_locator('[data-testid="custom-app-frame"]')
    expect(home_frame.get_by_role("heading", name="Text Lab")).to_be_visible()

    # Clear persisted state so this spike remains isolated from the rest of the suite.
    page.get_by_test_id("home-app-remove").click()
    expect(page.get_by_test_id("apps-view")).to_be_visible()

    # Turning the setting back off removes app navigation immediately.
    page.get_by_test_id("sidebar-settings").click()
    page.get_by_test_id("settings-tab-system").click()
    custom_apps_toggle = page.get_by_role("switch", name="Custom Apps")
    page.get_by_test_id("custom-apps-toggle").click()
    expect(custom_apps_toggle).not_to_be_checked()
    expect(page.get_by_test_id("sidebar-nav-apps")).not_to_be_visible()
