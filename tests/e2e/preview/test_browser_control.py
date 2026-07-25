"""E2E tests for the browser takeover control plane.

The agent opens the local fixture page (``_browser_fixture``); the test then
takes control and drives the sandboxed browser through the WebSocket side
channel — selection, input forwarding, navigation, tabs, clipboard, file
upload, fullscreen. Each fixture interaction navigates with a query param, so
assertions read the address bar (which the ``nav`` push keeps current).

Selectors are scoped by data-testid via the BrowserControl page object, so they
survive a frontend refactor.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import call_tool, parallel
from tests.e2e.pages import BrowserControl, ChatView
from tests.e2e.preview._browser_fixture import fixture_url, install_fixture, open_fixture

_RED_SQUARE = Path(__file__).resolve().parent.parent / "fixtures" / "red_square.png"

# A cold Chromium launch in the container is the slow path; warm opens are fast.
_OPEN_TIMEOUT = 30_000


@pytest.fixture(scope="module", autouse=True)
def _fixture_page():
    """Push the fixture HTML into the container once for the whole module."""
    install_fixture()


def _open(page: Page, prompt: str) -> tuple[ChatView, BrowserControl]:
    """New conversation, run *prompt*, activate the browser preview, take control."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(prompt).wait_streaming(timeout=_OPEN_TIMEOUT)
    chat.preview.browser_tab.wait_for(state="visible", timeout=10_000)
    chat.preview.select_tab(chat.preview.browser_tab)
    bc = BrowserControl(page).wait_loaded()
    return chat, bc


# ── screencast + tab rail ───────────────────────────────────────────


def test_screencast_renders_and_rail_shows_tabs(page: Page):
    """Opening two tabs renders the screencast and a rail with both tabs.

    Both tabs show their host caption — including the last-opened (non-selected)
    one, whose url/title would otherwise freeze at the about:blank it had the
    instant it was created, before it navigated.
    """
    _, bc = _open(page, open_fixture("click") + open_fixture("input"))
    expect(bc.frame).to_be_visible()
    expect(bc.tab(1)).to_contain_text("localhost")
    expect(bc.tab(2)).to_contain_text("localhost")


def test_selecting_tab_switches_streamed_url(page: Page):
    """Selecting a tab points the screencast at it; the address reflects it."""
    _, bc = _open(page, open_fixture("click") + open_fixture("input"))
    bc.take_control()
    bc.tab(2).click()
    expect(bc.address).to_have_value(re.compile("mode=input"))
    bc.tab(1).click()
    expect(bc.address).to_have_value(re.compile("mode=click"))


def test_concurrent_new_tabs_all_capture(page: Page):
    """Tabs opened concurrently each still get a thumbnail image.

    The three new_tab calls land in one response and run at once (parallel tool
    execution is on), racing for the single foreground slot. A captured tab
    yields an agent screenshot; this guards the losers against blacking out.
    """
    _, bc = _open(page, parallel(
        open_fixture("click"), open_fixture("input"), open_fixture("scroll"),
    ))
    for i in (1, 2, 3):
        expect(bc.tab(i).locator("img")).to_have_attribute(
            "src", re.compile(r"^(data|blob):"), timeout=15_000,
        )


def test_agent_tab_opened_while_previewing_captures(page: Page):
    """A tab the agent opens while the preview is already live still captures.

    Regression of the foreground guard: opening a new tab re-asserted the
    selected tab to the front, backgrounding the just-opened tab before its
    first screenshot, so the capture timed out and the thumbnail rendered
    black. The new tab must open *after* the control session is live for this
    path to be exercised.
    """
    chat, bc = _open(page, open_fixture("idle"))  # one tab, preview live, not engaged
    chat.send(open_fixture("click")).wait_streaming(timeout=_OPEN_TIMEOUT)
    expect(bc.tab(2)).to_be_visible(timeout=10_000)
    bc.tab(1).click()  # keep tab 2 non-selected so its thumb is the agent capture
    expect(bc.tab(2).locator("img")).to_have_attribute(
        "src", re.compile(r"^data:image"), timeout=10_000,
    )


# ── take control gating ─────────────────────────────────────────────


def test_take_control_engages(page: Page):
    """Before engaging there's no address input; taking control reveals it."""
    _, bc = _open(page, open_fixture("idle"))
    expect(bc.address).not_to_be_visible()
    bc.take_control()
    expect(bc.address).to_be_visible()


# ── input forwarding ────────────────────────────────────────────────


def test_click_is_forwarded(page: Page):
    """A click on the view reaches the remote page (it navigates)."""
    _, bc = _open(page, open_fixture("click"))
    bc.take_control()
    bc.click_view()
    expect(bc.address).to_have_value(re.compile("clicked=1"))


def test_typing_and_enter_are_forwarded(page: Page):
    """Typing fills a remote input; Enter submits it."""
    _, bc = _open(page, open_fixture("input"))
    bc.take_control()
    bc.type_text("hello")
    bc.press("Enter")
    expect(bc.address).to_have_value(re.compile("got=hello"))


def test_view_keeps_focus_after_switching_tabs(page: Page):
    """The view keeps keyboard focus after switching tabs during takeover.

    Clicking a rail thumbnail moves focus to the thumbnail button; the view's
    key listener only fires while the view holds focus, so without restoring
    it, keystrokes stop reaching the page until control is toggled off and on.
    Asserting the view is the active element directly verifies the refocus.
    """
    _, bc = _open(page, open_fixture("input") + open_fixture("input"))
    bc.take_control()  # sticky selection has tab 1 selected
    bc.tab(2).click()  # switch to a different tab — focus would land on the button
    view_focused = page.evaluate(
        "() => document.activeElement?.getAttribute('data-testid') === 'browser-viewport'",
    )
    assert view_focused, "view lost keyboard focus after switching tabs"


def test_scroll_is_forwarded(page: Page):
    """A wheel over the view scrolls the remote page."""
    _, bc = _open(page, open_fixture("scroll"))
    bc.take_control()
    bc.scroll(600)
    expect(bc.address).to_have_value(re.compile("scrolled=1"))


# ── navigation ──────────────────────────────────────────────────────


def test_address_bar_goto(page: Page):
    """Typing a URL in the address bar navigates the remote page."""
    _, bc = _open(page, open_fixture("idle"))
    bc.take_control()
    bc.goto(fixture_url("idle") + "&via=goto")
    expect(bc.address).to_have_value(re.compile("via=goto"))


def test_typing_after_address_bar_nav_without_clicking(page: Page):
    """After an address-bar navigation the page is immediately typeable.

    Regression: committing the address bar blurred focus to the document body,
    so the view's key listener (bound to the view element) stopped
    receiving keystrokes until the user clicked the view. The goto must hand
    focus back to the view. The input fixture autofocuses its field, so
    typing here — with no view click — only lands if the view holds focus.
    """
    _, bc = _open(page, open_fixture("idle"))
    bc.take_control()
    bc.goto(fixture_url("input"))
    expect(bc.address).to_have_value(re.compile("mode=input"))
    page.keyboard.type("hello")  # no view click first — relies on the refocus
    page.keyboard.press("Enter")
    expect(bc.address).to_have_value(re.compile("got=hello"))


def test_back_and_forward(page: Page):
    """History back/forward move the remote page through its history."""
    _, bc = _open(page, open_fixture("click"))
    bc.take_control()
    bc.click_view()
    expect(bc.address).to_have_value(re.compile("clicked=1"))
    bc.nav_btn("back").click()
    expect(bc.address).not_to_have_value(re.compile("clicked=1"))
    bc.nav_btn("forward").click()
    expect(bc.address).to_have_value(re.compile("clicked=1"))


# ── tab controls ────────────────────────────────────────────────────


def test_new_tab_button_opens_and_follows(page: Page):
    """The new-tab button opens a blank tab and (engaged) selects it."""
    _, bc = _open(page, open_fixture("idle"))
    bc.take_control()
    bc.new_tab_btn.click()
    expect(bc.tab(2)).to_be_visible()


def test_takeover_tab_thumbnail_survives_deselection(page: Page):
    """A tab opened during takeover keeps its thumbnail after being deselected.

    Only the selected tab is streamed live, and a takeover-opened tab has no
    agent screenshot — so without caching the last frame per tab, the tab blanks
    out the instant another is selected. Asserting tab 2 has a frame *before*
    opening tab 3 guarantees it was streamed; it must still have one after.
    """
    _, bc = _open(page, open_fixture("idle"))
    bc.take_control()
    bc.new_tab_btn.click()  # tab 2 (about:blank) — engaged selection follows it
    expect(bc.tab(2)).to_be_visible()
    expect(bc.tab(2).locator("img")).to_have_attribute(
        "src", re.compile(r"^blob:"), timeout=10_000,
    )
    bc.new_tab_btn.click()  # tab 3 — now selected; tab 2 is deselected
    expect(bc.tab(3)).to_be_visible()
    # tab 2 is deselected with no agent screenshot — its cached frame must hold.
    expect(bc.tab(2).locator("img")).to_have_attribute(
        "src", re.compile(r"^blob:"), timeout=10_000,
    )


def test_page_title_prefers_real_title_else_untitled(page: Page):
    """The title row shows the page's real title when it has one, else 'Untitled'.

    The row always renders (constant height) so the preview doesn't shift as
    titled and untitled pages alternate. The fixture sets ``<title>bfix</title>``;
    a fresh about:blank tab has none.
    """
    _, bc = _open(page, open_fixture("idle"))
    bc.take_control()
    expect(bc.page_title).to_have_text("bfix")
    bc.new_tab_btn.click()  # about:blank — no title
    expect(bc.page_title).to_have_text("Untitled")


def test_close_tab_button_removes_it(page: Page):
    """Closing a tab from the rail removes it."""
    _, bc = _open(page, open_fixture("click") + open_fixture("input"))
    bc.take_control()
    expect(bc.tab(2)).to_be_visible()
    bc.tab_close(2).click()
    expect(bc.tab(2)).not_to_be_visible()


def test_agent_closing_previewed_tab_recovers(page: Page):
    """If the agent closes the tab being previewed, the view falls back to a survivor.

    The agent and the user never drive at once, but the agent can close tabs in
    a later turn. Closing the streamed tab must re-point the view, not blank it.
    """
    chat, bc = _open(page, open_fixture("click") + open_fixture("input"))
    bc.tab(2).click()  # preview tab 2
    expect(bc.frame).to_be_visible()
    chat.send(call_tool("close_tab", tab="2")).wait_streaming(timeout=_OPEN_TIMEOUT)
    expect(bc.tab(2)).not_to_be_visible()
    expect(bc.frame).to_be_visible()  # recovered to the surviving tab


def test_turn_start_disengages_control(page: Page):
    """Starting an agent turn while engaged drops control (canControl=!isStreaming).

    The address input is only present while engaged, so it disappearing confirms
    control was released.
    """
    chat, bc = _open(page, open_fixture("idle"))
    bc.take_control()
    expect(bc.address).to_be_visible()
    chat.send(open_fixture("input"))  # start a turn; don't wait for it
    expect(bc.address).not_to_be_visible(timeout=10_000)


def test_clicking_link_opens_new_tab(page: Page):
    """A target=_blank link the user clicks opens a new tab in the rail."""
    _, bc = _open(page, open_fixture("link"))
    bc.take_control()
    bc.click_view()
    expect(bc.tab(2)).to_be_visible(timeout=10_000)


# ── fullscreen ──────────────────────────────────────────────────────


def test_fullscreen_round_trip(page: Page):
    """Maximizing and restoring preserves the same browser view."""
    _, bc = _open(page, open_fixture("idle"))
    host = bc.root.locator("xpath=ancestor::*[@data-view-id][1]")
    bc.fullscreen_btn.click()
    expect(host).to_have_attribute("data-maximized", "true")
    expect(bc.view).to_be_visible()

    page.get_by_test_id("restore-view-browser").click()
    expect(host).to_have_attribute("data-maximized", "false")
    expect(bc.view).to_be_visible()


# ── clipboard bridge ────────────────────────────────────────────────


def test_copy_from_remote_to_host(page: Page):
    """Ctrl+C copies the remote selection to the host clipboard."""
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    _, bc = _open(page, open_fixture("copy"))
    bc.take_control()
    bc.press("Control+C")
    # Poll the host clipboard (the copy crosses the WS asynchronously).
    got = ""
    for _ in range(20):
        got = page.evaluate("navigator.clipboard.readText()")
        if "COPYME" in got:
            break
        page.wait_for_timeout(250)
    assert "COPYME" in got, f"host clipboard was {got!r}"


def test_paste_from_host_to_remote(page: Page):
    """A host-clipboard paste over the view inserts into the focused field."""
    _, bc = _open(page, open_fixture("input"))
    bc.take_control()
    bc.click_view()  # focus the remote input
    # Playwright can't reliably trigger a real OS paste in headless, so dispatch
    # the paste event the view listens for, carrying the host clipboard text.
    page.evaluate(
        """() => {
          const el = document.querySelector(
            '[data-testid="browser-preview"] [data-testid="browser-viewport"]');
          const dt = new DataTransfer(); dt.setData('text/plain', 'PASTED');
          el.dispatchEvent(new ClipboardEvent(
            'paste', {clipboardData: dt, bubbles: true, cancelable: true}));
        }"""
    )
    bc.press("Enter")
    expect(bc.address).to_have_value(re.compile("got=PASTED"))


# ── file upload ─────────────────────────────────────────────────────


def test_file_upload_from_host(page: Page):
    """A remote file dialog is fulfilled with a file picked on the host."""
    assert _RED_SQUARE.exists()
    _, bc = _open(page, open_fixture("file"))
    bc.take_control()
    with page.expect_file_chooser() as fc:
        bc.click_view()  # clicks the remote file input → host picker opens
    fc.value.set_files(str(_RED_SQUARE))
    expect(bc.address).to_have_value(re.compile("got=red_square.png"))
