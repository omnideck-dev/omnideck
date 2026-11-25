"""The phone app: picked on load for small touch screens, and the chat work it supports."""

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import BASE_URL, DEFAULT_TIMEOUT_MS
from tests.e2e._protocol import say, send_file, write_file
from tests.e2e._runtime import api, delete_conversation
from tests.e2e.pages import ChatView, PhoneApp, phone_app

HOME = "/home/omnideck"


@pytest.fixture
def phone(browser: Browser) -> Iterator[PhoneApp]:
    with phone_app(browser, BASE_URL, DEFAULT_TIMEOUT_MS) as app:
        yield app


def _send(phone: PhoneApp, text: str) -> str:
    phone.composer.fill(text)
    with phone.page.expect_request(lambda req: req.method == "POST" and req.url.endswith("/api/chat")) as started:
        phone.page.get_by_role("button", name="Send message").click()
    return started.value.post_data_json["conversation_id"]


def _start_chat(phone: PhoneApp, text: str) -> str:
    phone.page.get_by_test_id("phone-new-chat").click()
    expect(phone.chat).to_be_visible()
    cid = _send(phone, text)
    ChatView(phone.page).wait_streaming()
    return cid


def test_a_phone_loads_the_phone_app_and_a_desktop_loads_the_full_app(phone: PhoneApp, page: Page):
    expect(phone.page.get_by_test_id("phone-conversation-list")).to_be_visible()

    ChatView(page).goto()
    expect(page.get_by_test_id("sidebar-new-chat")).to_be_visible(timeout=15_000)
    expect(page.get_by_test_id("phone-app")).to_have_count(0)


def test_return_adds_a_line_and_the_send_button_sends(phone: PhoneApp):
    phone.page.get_by_test_id("phone-new-chat").click()
    phone.composer.fill("first line")
    phone.composer.press("Enter")
    expect(phone.composer).to_have_value("first line\n")
    expect(phone.page.get_by_test_id("chat-stop-btn")).to_have_count(0)

    cid = _send(phone, say("PHONE-REPLY"))
    try:
        expect(phone.chat).to_contain_text("PHONE-REPLY", timeout=10_000)
        ChatView(phone.page).wait_streaming()
        phone.back()
        expect(phone.row(cid)).to_be_visible()
    finally:
        delete_conversation(cid)


def test_swiping_a_chat_left_and_tapping_archive_archives_it(phone: PhoneApp):
    cid = _start_chat(phone, say("PHONE-ARCHIVE"))
    try:
        phone.back()
        expect(phone.row(cid)).to_be_visible()

        phone.swipe(cid, -140)
        archive = phone.swipe_action(cid, "phone-swipe-archive")
        expect(archive).to_be_visible()
        archive.click()

        expect(phone.row(cid)).to_have_count(0)
        archived = api().get("/api/conversations/archived").json()
        assert cid in {c["conversation_id"] for c in archived}
    finally:
        delete_conversation(cid)


def test_tapping_a_file_card_opens_the_file_with_one_action(phone: PhoneApp):
    path = f"{HOME}/phone-notes.md"
    cid = _start_chat(phone, write_file(path, "# Phone notes") + send_file(path) + say("done"))
    try:
        card = phone.chat.get_by_text("phone-notes.md", exact=True)
        expect(card).to_be_visible(timeout=10_000)
        expect(phone.chat.get_by_test_id("file-preview-btn")).to_have_count(0)
        expect(phone.chat.get_by_test_id("file-download-btn")).to_have_count(0)
        expect(phone.chat.get_by_test_id("file-download")).to_have_count(1)

        card.click()

        file_screen = phone.page.get_by_test_id("phone-file")
        expect(file_screen).to_be_visible()
        expect(file_screen.get_by_test_id("phone-title")).to_have_text("phone-notes.md")
        expect(file_screen.get_by_test_id("file-download")).to_have_count(1)
        expect(file_screen).to_contain_text("Phone notes")
    finally:
        delete_conversation(cid)


def test_a_chat_started_on_the_desktop_appears_on_an_open_phone(phone: PhoneApp, page: Page):
    chat = ChatView(page).goto()
    chat.new_conversation()
    with page.expect_request(lambda req: req.method == "POST" and req.url.endswith("/api/chat")) as started:
        chat.send(say("FROM-DESKTOP"))
    cid = started.value.post_data_json["conversation_id"]
    try:
        chat.wait_streaming()
        expect(phone.row(cid)).to_be_visible(timeout=10_000)
    finally:
        delete_conversation(cid)
