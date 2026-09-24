"""E2E tests for the auto-growing composer and its expand-in-place mode.

The composer auto-grows up to 8 rows as the user types; a corner button then
expands it to fill the chat area *in place* (no modal), and submit or Escape
collapses it back to the inline size. This behaviour is layout-dependent
(``scrollHeight`` / element geometry), so it can only be exercised in a real
browser — jsdom reports zero for all of it, which is why this lives in e2e.
"""

from playwright.sync_api import Page, expect

from tests.e2e.pages import ChatView


def _height(locator) -> float:
    return locator.evaluate("e => e.getBoundingClientRect().height")


def test_auto_grows_and_expands_in_place(page: Page):
    chat = ChatView(page).goto()
    composer = chat.composer
    composer.wait_for(state="visible")
    inline_h = _height(composer)

    # Typing several lines auto-grows the textarea and reveals the control.
    composer.fill("\n".join(f"line {i}" for i in range(1, 6)))
    expect(chat.expand_button).to_be_visible()
    grown_h = _height(composer)
    assert grown_h > inline_h + 20, f"textarea did not grow: {inline_h} -> {grown_h}"

    # Expanding fills the chat area in place — crucially, with no modal/dialog.
    chat.expand_button.click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_role("button", name="Collapse input")).to_be_visible()
    expanded_h = _height(composer)
    assert expanded_h > grown_h + 200, f"composer did not fill the area: {grown_h} -> {expanded_h}"
    assert "line 5" in composer.input_value()

    # Escape collapses back to the inline size without discarding the text.
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Collapse input")).to_have_count(0)
    collapsed_h = _height(composer)
    assert collapsed_h < expanded_h - 200, f"composer did not collapse: {expanded_h} -> {collapsed_h}"
    assert "line 5" in composer.input_value()


def test_submit_collapses_expanded_composer(page: Page):
    chat = ChatView(page).goto()
    composer = chat.composer
    composer.wait_for(state="visible")

    composer.fill("\n".join(f"line {i}" for i in range(1, 6)))
    chat.expand_button.click()
    expect(page.get_by_role("button", name="Collapse input")).to_be_visible()

    # Sending the message returns the composer to its normal inline height.
    composer.press("Enter")
    chat.wait_streaming()
    expect(page.get_by_role("button", name="Collapse input")).to_have_count(0)
    assert composer.input_value() == ""
