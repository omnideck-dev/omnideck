"""End-to-end coverage for Custom Apps."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import bash, say
from tests.e2e.pages import ChatView, DesktopLayout, RecentConversations

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
    <button id="open-chat">Open chat</button>
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

document.querySelector('#open-chat').addEventListener('click', () => {
  window.omnideck.chat.open();
});
""",
}

_SECOND_TEST_APP_FILES = {
    "omnideck.json": """{"title":"Notes Lab","description":"Second E2E fixture","icon":"bi-journal"}""",
    "web/index.html": """<!doctype html>
<html lang="en"><body><h1>Notes Lab</h1><textarea id="notes">second app</textarea></body></html>
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


@pytest.fixture()
def installed_two_custom_apps(page: Page, installed_custom_app):
    """Add a second app when a test needs concurrent app views."""
    container_exec(
        "from pathlib import Path\n"
        f"files = {_SECOND_TEST_APP_FILES!r}\n"
        "root = Path('/home/omnideck/apps/notes-lab')\n"
        "for name, content in files.items():\n"
        "    path = root / name\n"
        "    path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    path.write_text(content, encoding='utf-8')"
    )
    try:
        yield
    finally:
        container_exec(
            "import shutil\n"
            "shutil.rmtree('/home/omnideck/apps/notes-lab', ignore_errors=True)"
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
    """Assert Chat and the Custom App are active in left and right tab groups."""
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()
    expect(page.get_by_test_id("desktop-layout")).to_have_attribute(
        "data-split", "true"
    )
    expect(page.get_by_test_id("view-tab-custom-app:text-lab")).to_be_visible()
    expect(
        page.locator("[data-view-id='destination:conversation']")
    ).to_have_attribute("data-tab-group-id", "left")
    expect(
        page.locator("[data-view-id='custom-app:text-lab']")
    ).to_have_attribute("data-tab-group-id", "right")
    expect(
        page.frame_locator('[data-testid="custom-app-frame"]').get_by_role("heading", name="Text Lab")
    ).to_be_visible()


def _docked_app_order(page: Page) -> list[str]:
    """Return pinned Apps in their current sidebar order."""
    return page.locator("[data-testid^='sidebar-docked-app-']").evaluate_all(
        """rows => rows.map((row) => row.getAttribute('data-reorder-id'))"""
    )


def _drag_app_above(page: Page, source_slug: str, target_slug: str) -> None:
    """Drag one pinned App above another within the Apps group."""
    source = page.get_by_test_id(f"sidebar-docked-app-{source_slug}")
    target = page.get_by_test_id(f"sidebar-docked-app-{target_slug}")
    source_box = source.bounding_box()
    target_box = target.bounding_box()
    assert source_box is not None
    assert target_box is not None

    page.mouse.move(
        source_box["x"] + source_box["width"] / 2,
        source_box["y"] + source_box["height"] / 2,
    )
    page.mouse.down()
    page.mouse.move(
        target_box["x"] + target_box["width"] / 2,
        target_box["y"] + target_box["height"] * 0.2,
        steps=8,
    )
    page.mouse.up()


def test_apps_can_be_pinned_from_hub_and_open_view_then_reordered(
    page: Page, installed_two_custom_apps
) -> None:
    """Hub and open-App pin controls stay in sync with the reorderable sidebar."""
    _open_custom_apps_library(page)

    apps_section = page.get_by_test_id("sidebar-docked-section")
    expect(apps_section).to_be_visible()
    expect(apps_section.get_by_text("Apps", exact=True)).to_be_visible()

    # Pin directly from the Apps Hub.
    page.get_by_test_id("custom-app-pin-text-lab").click()
    text_app = page.get_by_test_id("sidebar-docked-app-text-lab")
    expect(text_app).to_be_visible()

    # The opened App view can unpin and repin itself.
    page.get_by_test_id("custom-app-card").filter(has_text="Text Lab").click()
    expect(
        page.frame_locator('[data-testid="custom-app-frame"]').get_by_role(
            "heading", name="Text Lab"
        )
    ).to_be_visible()
    open_view_pin = page.get_by_test_id("custom-app-view-pin")
    expect(open_view_pin).to_have_text("Pinned")
    open_view_pin.click()
    expect(text_app).to_have_count(0)
    expect(open_view_pin).to_have_text("Pin to sidebar")
    open_view_pin.click()
    expect(text_app).to_be_visible()

    # Add another App from the Hub and reorder the Apps group by dragging.
    page.get_by_test_id("sidebar-nav-apps").click()
    page.get_by_test_id("custom-app-pin-notes-lab").click()
    expect(page.get_by_test_id("sidebar-docked-app-notes-lab")).to_be_visible()
    assert _docked_app_order(page) == ["text-lab", "notes-lab"]
    _drag_app_above(page, "notes-lab", "text-lab")
    assert _docked_app_order(page) == ["notes-lab", "text-lab"]

    # Ordering and pin state survive reload.
    page.reload()
    expect(page.get_by_test_id("sidebar-docked-app-notes-lab")).to_be_visible()
    expect(text_app).to_be_visible()
    assert _docked_app_order(page) == ["notes-lab", "text-lab"]

    # Context-menu unpin returns the App to the section picker.
    text_app.click(button="right")
    page.get_by_test_id("sidebar-reorder-unpin").click()
    expect(text_app).to_have_count(0)
    page.get_by_test_id("sidebar-docked-add").click()
    expect(page.get_by_test_id("sidebar-dock-option-text-lab")).to_be_visible()


def test_custom_app_moves_left_to_right_and_back_without_losing_state(
    page: Page, installed_custom_app
) -> None:
    """Moving a view between tab groups preserves its one iframe."""
    _open_custom_apps_library(page)

    page.get_by_test_id("custom-app-card").click()
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()
    expect(page.get_by_test_id("custom-app-view")).to_be_visible()
    expect(page.get_by_test_id("custom-app-back")).to_have_count(0)
    expect(page.get_by_test_id("custom-app-chat")).to_have_count(0)
    expect(page.get_by_test_id("custom-app-close")).to_have_count(0)
    expect(page.get_by_test_id("custom-app-home-toggle")).to_have_count(0)
    expect(page.get_by_test_id("chat-title-bar")).not_to_be_visible()
    expect(page.get_by_test_id("view-tab-custom-app:text-lab")).to_be_visible()
    expect(
        page.locator("[data-view-id='custom-app:text-lab']")
    ).to_have_attribute("data-tab-group-id", "left")

    working_text = "Left-tab group state survives the move beside chat."
    frame.locator("#text").fill(working_text)
    desktop = DesktopLayout(page)
    desktop.move("custom-app:text-lab", "right")

    expect(page.get_by_test_id("apps-view")).to_be_visible()
    expect(
        page.locator("[data-view-id='custom-app:text-lab']")
    ).to_have_attribute("data-tab-group-id", "right")
    expect(frame.locator("#text")).to_have_value(working_text)

    desktop.move("custom-app:text-lab", "left")
    expect(
        page.locator("[data-view-id='custom-app:text-lab']")
    ).to_have_attribute("data-tab-group-id", "left")
    expect(page.get_by_test_id("desktop-tab-group-right")).to_have_count(0)
    expect(page.get_by_test_id("chat-title-bar")).not_to_be_visible()
    expect(frame.locator("#text")).to_have_value(working_text)

    desktop.float("custom-app:text-lab")
    expect(
        page.locator("[data-view-id='custom-app:text-lab']")
    ).to_have_attribute("data-floating", "true")
    expect(frame.locator("#text")).to_have_value(working_text)
    page.get_by_test_id("dock-view-custom-app:text-lab-left").click()
    expect(frame.locator("#text")).to_have_value(working_text)

    desktop.choose_tab_action("custom-app:text-lab", "close")
    expect(page.get_by_test_id("custom-app-frame")).to_have_count(0)
    expect(page.get_by_test_id("apps-view")).to_be_visible()


def test_custom_app_stays_mounted_while_other_left_tabs_are_selected(
    page: Page, installed_custom_app
) -> None:
    """Selecting other left-tab group tabs retains the app iframe and its state."""
    _open_custom_apps_library(page)
    page.get_by_test_id("custom-app-card").click()

    frame_element = page.get_by_test_id("custom-app-frame")
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    working_text = "Hidden presentation keeps this in-page state."
    frame.locator("#text").fill(working_text)

    page.get_by_test_id("sidebar-settings").click()
    expect(page.get_by_test_id("settings-tab-skills")).to_be_visible()
    expect(frame_element).to_have_count(1)
    expect(frame_element).not_to_be_visible()

    page.get_by_test_id("view-tab-custom-app:text-lab").click()
    expect(frame_element).to_be_visible()
    expect(frame.locator("#text")).to_have_value(working_text)

    page.get_by_test_id("sidebar-settings").click()
    page.get_by_test_id("sidebar-nav-apps").click()
    page.get_by_test_id("custom-app-card").click()
    expect(
        page.locator("[data-view-id='custom-app:text-lab']")
    ).to_have_attribute("data-tab-group-id", "left")
    expect(frame.locator("#text")).to_have_value(working_text)


def test_inactive_custom_app_reload_is_a_per_tab_action(
    page: Page, installed_custom_app
) -> None:
    """A tab menu can reload an inactive app without navigating away."""
    _open_custom_apps_library(page)
    page.get_by_test_id("custom-app-card").click()
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    frame.locator("#text").fill("reload this inactive app")

    page.get_by_test_id("sidebar-settings").click()
    expect(page.get_by_test_id("settings-page")).to_be_visible()

    desktop = DesktopLayout(page)
    menu = desktop.open_tab_menu("custom-app:text-lab")
    menu.get_by_test_id("tab-context-action-reload").click()

    expect(page.get_by_test_id("settings-page")).to_be_visible()
    expect(desktop.active_view("left")).to_have_attribute(
        "data-view-id", "destination:settings"
    )
    expect(frame.locator("#text")).to_have_value(
        "The simplest useful app should feel like a folder you can open."
    )


def test_custom_app_bridge_selects_chat_without_moving_the_app(
    page: Page, installed_custom_app
) -> None:
    """App bridge commands select retained Chat while leaving placement alone."""
    _open_custom_apps_library(page)
    page.get_by_test_id("custom-app-card").click()
    frame = page.frame_locator('[data-testid="custom-app-frame"]')

    frame.get_by_role("button", name="Open chat").click()
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()
    expect(
        page.locator("[data-view-id='custom-app:text-lab']")
    ).to_have_attribute("data-tab-group-id", "left")
    expect(page.get_by_test_id("desktop-layout")).to_have_attribute(
        "data-split", "false"
    )

    page.get_by_test_id("view-tab-custom-app:text-lab").click()
    working_text = "Bridge compose state"
    frame.locator("#text").fill(working_text)
    frame.get_by_role("button", name="Ask agent about this").click()
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()
    expect(
        page.locator("[data-view-id='custom-app:text-lab']")
    ).to_have_attribute("data-tab-group-id", "left")
    expect(ChatView(page).composer).to_have_value(re.compile(re.escape(working_text)))


def test_custom_app_transitions_when_loading_a_conversation(
    page: Page, installed_custom_app
) -> None:
    """Loading another conversation keeps the Custom App in the right tab group."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(say("conversation to reopen")).wait_streaming()
    conversation_id = page.request.get("/api/conversations/sessions").json()[0][
        "conversation_id"
    ]

    assert page.request.put("/api/settings", data={"custom_apps_enabled": True}).ok
    ChatView(page).goto()
    page.get_by_test_id("sidebar-nav-apps").click()
    page.get_by_test_id("custom-app-card").click()
    DesktopLayout(page).move("custom-app:text-lab", "right")
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    working_text = "State survives conversation loading."
    frame.locator("#text").fill(working_text)

    page.get_by_test_id("sidebar-new-chat").click()
    RecentConversations(page).open_by_id(conversation_id)

    _expect_app_beside_chat(page)
    expect(frame.locator("#text")).to_have_value(working_text)


def test_custom_app_and_workspace_previews_share_the_right_tab_stack(
    page: Page, installed_custom_app
) -> None:
    """Workspace previews and a Custom App switch within one tab group."""
    _open_custom_apps_library(page)
    page.get_by_test_id("custom-app-card").click()
    DesktopLayout(page).move("custom-app:text-lab", "right")
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    working_text = "State survives another tab being selected."
    frame.locator("#text").fill(working_text)

    page.get_by_test_id("view-tab-destination:conversation").click()
    ChatView(page).send(bash('echo "custom-app-view"')).wait_streaming()
    expect(page.get_by_test_id("view-tab-terminal")).to_be_visible()
    expect(page.get_by_test_id("view-tab-custom-app:text-lab")).to_be_visible()
    expect(
        page.get_by_test_id("view-tab-actions-custom-app:text-lab")
    ).to_be_visible()

    page.get_by_test_id("view-tab-terminal").click()
    expect(
        page.locator(
            "[data-view-resource-id='terminal']"
            "[data-tab-group-id='right'][data-visible='true']"
        ).get_by_text("custom-app-view", exact=False).last
    ).to_be_visible()
    expect(page.get_by_test_id("custom-app-frame")).to_have_count(1)
    expect(
        page.get_by_test_id("view-tab-actions-custom-app:text-lab")
    ).to_have_count(0)

    page.get_by_test_id("view-tab-custom-app:text-lab").click()
    expect(frame.locator("#text")).to_have_value(working_text)
    expect(
        page.get_by_test_id("view-tab-actions-custom-app:text-lab")
    ).to_be_visible()


def test_opening_another_custom_app_keeps_both_as_independent_tabs(
    page: Page, installed_two_custom_apps
) -> None:
    """Multiple apps retain independent iframe sessions in one tab group."""
    _open_custom_apps_library(page)
    page.get_by_test_id("custom-app-card").filter(has_text="Text Lab").click()
    expect(page.get_by_test_id("view-tab-custom-app:text-lab")).to_be_visible()
    text_frame = page.frame_locator(
        "[data-view-id='custom-app:text-lab'] [data-testid='custom-app-frame']"
    )
    working_text = "The first app remains mounted."
    text_frame.locator("#text").fill(working_text)

    page.get_by_test_id("sidebar-nav-apps").click()
    page.get_by_test_id("custom-app-card").filter(has_text="Notes Lab").click()

    expect(page.get_by_test_id("view-tab-custom-app:text-lab")).to_be_visible()
    expect(page.get_by_test_id("view-tab-custom-app:notes-lab")).to_be_visible()
    expect(page.get_by_test_id("custom-app-frame")).to_have_count(2)
    expect(
        page.locator("[data-view-id='custom-app:notes-lab']")
    ).to_have_attribute("data-tab-group-id", "left")
    expect(
        page.locator("[data-view-id='custom-app:notes-lab']")
        .get_by_test_id("custom-app-frame")
    ).to_have_attribute(
        "src", "/api/custom-apps/notes-lab/web/"
    )
    expect(
        page.frame_locator(
            "[data-view-id='custom-app:notes-lab'] "
            "[data-testid='custom-app-frame']"
        ).get_by_role(
            "heading", name="Notes Lab"
        )
    ).to_be_visible()

    page.get_by_test_id("view-tab-custom-app:text-lab").click()
    expect(text_frame.locator("#text")).to_have_value(working_text)


def test_right_pane_custom_app_survives_new_conversation_and_closes(
    page: Page, installed_custom_app
) -> None:
    """A right-tab group app survives a new conversation and closes only on request."""
    _open_custom_apps_library(page)

    page.get_by_test_id("custom-app-card").click()
    desktop = DesktopLayout(page)
    desktop.move("custom-app:text-lab", "right")
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    page.get_by_test_id("view-tab-destination:conversation").click()
    _expect_app_beside_chat(page)

    working_text = "Right-tab group state survives a new conversation."
    frame.locator("#text").fill(working_text)
    page.get_by_test_id("sidebar-new-chat").click()

    _expect_app_beside_chat(page)
    expect(frame.locator("#text")).to_have_value(working_text)

    desktop.choose_tab_action("custom-app:text-lab", "close")
    expect(page.get_by_test_id("view-tab-custom-app:text-lab")).not_to_be_visible()
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()


def test_disabling_custom_apps_closes_the_open_app(
    page: Page, installed_custom_app
) -> None:
    """Disabling the feature removes an open app rather than leaving hidden state."""
    _open_custom_apps_library(page)
    page.get_by_test_id("custom-app-card").click()
    DesktopLayout(page).move("custom-app:text-lab", "right")
    expect(page.get_by_test_id("custom-app-frame")).to_have_count(1)

    page.get_by_test_id("sidebar-settings").click()
    page.get_by_test_id("settings-tab-system").click()
    page.get_by_test_id("custom-apps-toggle").click()

    expect(page.get_by_test_id("custom-app-frame")).to_have_count(0)
    expect(page.get_by_test_id("sidebar-nav-apps")).not_to_be_visible()


def test_legacy_home_setting_is_ignored_by_the_tabbed_shell(
    page: Page, installed_custom_app
) -> None:
    """Persisted legacy Home metadata does not create special navigation."""
    assert page.request.put("/api/settings", data={"custom_apps_enabled": True}).ok
    assert page.request.put("/api/custom-apps/home", data={"slug": "text-lab"}).ok

    ChatView(page).goto()
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()
    expect(page.get_by_test_id("sidebar-nav-home")).to_have_count(0)
    expect(page.get_by_test_id("custom-app-frame")).to_have_count(0)

    page.get_by_test_id("sidebar-nav-apps").click()
    page.get_by_test_id("custom-app-card").click()
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()
    expect(page.get_by_test_id("custom-app-home-toggle")).to_have_count(0)
    expect(page.get_by_test_id("chat-title-bar")).not_to_be_visible()
    expect(page.get_by_test_id("view-tab-custom-app:text-lab")).to_be_visible()


def test_custom_app_keeps_file_views_inside_the_app_frame(
    page: Page, installed_custom_app
) -> None:
    """Apps may embed home files, but may not replace their outer document with one."""
    _open_custom_apps_library(page)
    page.get_by_test_id("custom-app-card").click()

    frame_element = page.get_by_test_id("custom-app-frame")
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()

    frame.locator("body").evaluate(
        """body => {
            const fileView = document.createElement('iframe');
            fileView.id = 'file-view';
            fileView.src = '/home/omnideck/custom-app-alpha.txt';
            body.append(fileView);
        }"""
    )
    expect(frame.frame_locator("#file-view").locator("body")).to_contain_text("read from home")
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()

    # Replacing the outer app document is reverted, even for a same-origin file.
    frame_element.evaluate("frame => { frame.src = '/home/omnideck/custom-app-alpha.txt'; }")
    expect(frame_element).to_have_attribute("src", "/api/custom-apps/text-lab/web/")
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()

    # An opaque external document is reverted by the same guard.
    frame_element.evaluate("frame => { frame.src = 'data:text/html,external'; }")
    expect(frame_element).to_have_attribute("src", "/api/custom-apps/text-lab/web/")
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()


def test_custom_app_opens_and_invokes_python(page: Page, installed_custom_app) -> None:
    """The shell lists an installed app, opens its frame, and bridges an action."""
    page.request.put("/api/settings", data={"custom_apps_enabled": False})
    ChatView(page).goto()

    # Apps are controlled by a user setting, not an environment-level feature flag.
    expect(page.get_by_test_id("sidebar-nav-apps")).not_to_be_visible()
    page.get_by_test_id("sidebar-settings").click()
    page.get_by_test_id("settings-tab-system").click()
    custom_apps_toggle = page.get_by_role("switch", name="Apps")
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
    working_text = "This state should survive moving tab groups and a new conversation."
    frame.locator("#text").fill(working_text)
    frame.get_by_role("button", name="Ask agent about this").click()
    expect(page.get_by_test_id("view-tab-custom-app:text-lab")).to_be_visible()
    expect(page.locator("textarea").first).to_have_value(re.compile(re.escape(working_text)))
    expect(frame.locator("#text")).to_have_value(working_text)

    # A new conversation closes workspace resources, not the open Custom App.
    page.get_by_test_id("sidebar-new-chat").click()
    expect(page.get_by_test_id("view-tab-custom-app:text-lab")).to_be_visible()
    expect(frame.locator("#text")).to_have_value(working_text)

    # The app owns its reload command even while its tab is inactive.
    DesktopLayout(page).choose_tab_action("custom-app:text-lab", "reload")
    expect(frame.locator("#text")).to_have_value("The simplest useful app should feel like a folder you can open.")

    # Closing the app removes its view tab and leaves Chat active.
    DesktopLayout(page).choose_tab_action("custom-app:text-lab", "close")
    expect(page.get_by_test_id("view-tab-custom-app:text-lab")).not_to_be_visible()
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()

    # Reopen as a normal tab and maximize the same iframe view.
    page.get_by_test_id("sidebar-nav-apps").click()
    page.get_by_test_id("custom-app-card").click()
    frame = page.frame_locator('[data-testid="custom-app-frame"]')
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()
    maximized_text = "Maximizing preserves this app state."
    frame.locator("#text").fill(maximized_text)
    DesktopLayout(page).maximize("custom-app:text-lab")
    expect(
        page.locator("[data-view-id='custom-app:text-lab']")
    ).to_have_attribute("data-maximized", "true")
    expect(frame.locator("#text")).to_have_value(maximized_text)
    expect(page.get_by_test_id("custom-app-frame")).to_have_count(1)
    page.get_by_test_id("restore-view-custom-app:text-lab").click()
    expect(
        page.locator("[data-view-id='custom-app:text-lab']")
    ).to_have_attribute("data-maximized", "false")

    # Turning the setting back off removes app navigation immediately.
    page.get_by_test_id("sidebar-settings").click()
    page.get_by_test_id("settings-tab-system").click()
    custom_apps_toggle = page.get_by_role("switch", name="Apps")
    page.get_by_test_id("custom-apps-toggle").click()
    expect(custom_apps_toggle).not_to_be_checked()
    expect(page.get_by_test_id("sidebar-nav-apps")).not_to_be_visible()
