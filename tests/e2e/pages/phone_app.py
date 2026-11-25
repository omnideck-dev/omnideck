"""POM for the phone app: the separate chat app small touch screens load."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Browser, Locator, Page, expect

PHONE_SCREEN = {"width": 390, "height": 844}


class PhoneApp:
    """One phone-sized touch browser showing the phone app."""

    def __init__(self, page: Page):
        self.page = page

    @property
    def screen(self) -> Locator:
        """The screen on top of the phone app's screen stack."""
        return self.page.locator('[data-testid="phone-app"] > div:not([hidden])')

    @property
    def chat(self) -> Locator:
        return self.page.get_by_test_id("phone-chat")

    @property
    def composer(self) -> Locator:
        return self.chat.locator("textarea")

    def row(self, conversation_id: str) -> Locator:
        return self.page.locator(
            f'[data-conversation-id="{conversation_id}"] [data-testid="phone-conversation-row"]',
        )

    def swipe_action(self, conversation_id: str, testid: str) -> Locator:
        return self.page.locator(f'[data-conversation-id="{conversation_id}"] [data-testid="{testid}"]')

    def open_chat(self, conversation_id: str) -> "PhoneApp":
        self.row(conversation_id).click()
        expect(self.chat).to_be_visible()
        return self

    def back(self) -> "PhoneApp":
        self.screen.locator("header button").first.click()
        return self

    def swipe(self, conversation_id: str, dx: int) -> "PhoneApp":
        box = self.row(conversation_id).bounding_box()
        assert box is not None
        x = box["x"] + box["width"] / 2
        y = box["y"] + box["height"] / 2
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        for step in range(1, 9):
            self.page.mouse.move(x + dx * step / 8, y)
        self.page.mouse.up()
        return self


@contextmanager
def phone_app(browser: Browser, base_url: str, timeout_ms: int = 5_000) -> Iterator[PhoneApp]:
    """Open the phone app in its own phone-sized touch browser context."""
    context = browser.new_context(
        base_url=base_url,
        extra_http_headers={"X-Requested-With": "XMLHttpRequest"},
        viewport=PHONE_SCREEN,
        screen=PHONE_SCREEN,
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
    )
    try:
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        page.goto("/", timeout=15_000)
        expect(page.get_by_test_id("phone-app")).to_be_visible(timeout=15_000)
        yield PhoneApp(page)
    finally:
        context.close()
