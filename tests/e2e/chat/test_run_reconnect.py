"""Browser coverage for reconnecting to process-owned agent runs."""

from __future__ import annotations

import json
import time

from playwright.sync_api import Page, Route, expect

from tests.e2e._protocol import say, slow
from tests.e2e.pages import ChatView


def _capture_conversation_id(page: Page) -> dict[str, str]:
    captured: dict[str, str] = {}

    def capture(route: Route) -> None:
        body = json.loads(route.request.post_data or "{}")
        captured["id"] = body["conversation_id"]
        route.continue_()

    page.route("**/api/chat", capture)
    return captured


def _wait_for_durable_view(page: Page, captured: dict[str, str]) -> str:
    page.wait_for_function(
        """conversationId => {
            const raw = localStorage.getItem('omnideck_desktop_window_v1');
            return Boolean(raw && raw.includes(conversationId));
        }""",
        arg=captured["id"],
    )
    return captured["id"]


def _cleanup(page: Page, conversation_id: str | None) -> None:
    if not conversation_id:
        return
    page.request.post(f"/api/chat/stop?conversation_id={conversation_id}")
    for _ in range(20):
        resumed = page.request.post(
            f"/api/conversations/sessions/{conversation_id}/resume",
        )
        if not resumed.ok or resumed.json().get("active_run") is None:
            break
        page.wait_for_timeout(100)
    page.request.delete(f"/api/conversations/sessions/{conversation_id}")


def test_refresh_reattaches_and_finishes_the_active_run(page: Page) -> None:
    """Reloading the SPA follows the run and renders its missed tail once."""
    nonce = time.time_ns()
    prefix = f"REFRESH-PREFIX-{nonce}"
    tail = f"REFRESH-TAIL-{nonce}"
    body = f"{prefix} " + ("keep streaming " * 220) + tail
    captured = _capture_conversation_id(page)
    conversation_id = None

    try:
        chat = ChatView(page).goto().new_conversation()
        chat.send(slow() + say(body))
        expect(page.get_by_test_id("entry-content").last).to_contain_text(
            prefix,
            timeout=10_000,
        )
        conversation_id = _wait_for_durable_view(page, captured)

        page.reload()

        expect(page.get_by_test_id("entry-content").last).to_contain_text(
            tail,
            timeout=30_000,
        )
        chat.wait_streaming(timeout=30_000)
        expect(page.get_by_test_id("message-user")).to_have_count(1)
        expect(page.get_by_test_id("message-assistant")).to_have_count(1)

        resumed = page.request.post(
            f"/api/conversations/sessions/{conversation_id}/resume",
        )
        assert resumed.ok
        assert resumed.json()["active_run"] is None
    finally:
        _cleanup(page, conversation_id)


def test_temporary_network_loss_reconnects_without_resending(page: Page) -> None:
    """An offline/online cycle reconnects by run cursor, not another POST."""
    nonce = time.time_ns()
    prefix = f"OFFLINE-PREFIX-{nonce}"
    tail = f"OFFLINE-TAIL-{nonce}"
    body = f"{prefix} " + ("network gap " * 180) + tail
    captured = _capture_conversation_id(page)
    chat_posts = 0
    attach_requests: list[str] = []
    conversation_id = None

    def count_post(request) -> None:
        nonlocal chat_posts
        if request.method == "POST" and request.url.endswith("/api/chat"):
            chat_posts += 1
        if "/api/chat/runs/" in request.url:
            attach_requests.append(request.url)

    page.on("request", count_post)

    try:
        chat = ChatView(page).goto().new_conversation()
        chat.send(say("existing conversation warmup")).wait_streaming()
        chat.send(slow() + say(body))
        expect(page.get_by_test_id("entry-content").last).to_contain_text(
            prefix,
            timeout=10_000,
        )
        conversation_id = captured["id"]

        page.context.set_offline(True)
        expect(page.get_by_test_id("connection-status")).to_contain_text("Offline")
        page.wait_for_timeout(2_000)
        expect(chat.stop_button).to_be_visible()
        page.context.set_offline(False)

        expect(page.get_by_test_id("entry-content").last).to_contain_text(
            tail,
            timeout=30_000,
        )
        chat.wait_streaming(timeout=30_000)
        assert chat_posts == 2
        assert attach_requests, "offline cycle never reattached to the active run"
    finally:
        page.context.set_offline(False)
        _cleanup(page, conversation_id)


def test_offline_composer_keeps_draft_without_queuing_a_run(page: Page) -> None:
    """Offline submission stays in the composer until the user retries online."""
    message = say(f"OFFLINE-DRAFT-{time.time_ns()}")
    captured = _capture_conversation_id(page)
    chat_posts = 0
    conversation_id = None

    def count_posts(request) -> None:
        nonlocal chat_posts
        if request.method == "POST" and request.url.endswith("/api/chat"):
            chat_posts += 1

    page.on("request", count_posts)

    try:
        chat = ChatView(page).goto().new_conversation()
        page.context.set_offline(True)
        expect(page.get_by_test_id("connection-status")).to_have_text("Offline")

        chat.composer.fill(message)
        chat.composer.press("Enter")

        expect(chat.composer).to_have_value(message)
        expect(page.get_by_label("Send message")).to_be_disabled()
        expect(page.get_by_test_id("message-user")).to_have_count(0)
        assert chat_posts == 0

        page.context.set_offline(False)
        expect(page.get_by_test_id("connection-status")).to_be_hidden()
        chat.composer.press("Enter")
        chat.wait_streaming()

        conversation_id = captured["id"]
        assert chat_posts == 1
    finally:
        page.context.set_offline(False)
        _cleanup(page, conversation_id)


def test_completion_before_replay_attach_refetches_the_snapshot(page: Page) -> None:
    """A pruned run between resume and GET is recovered from durable state."""
    nonce = time.time_ns()
    prefix = f"RACE-PREFIX-{nonce}"
    tail = f"RACE-TAIL-{nonce}"
    body = f"{prefix} " + ("finish during attach " * 55) + tail
    captured = _capture_conversation_id(page)
    delayed_attach: list[str] = []
    conversation_id = None

    def delay_attach(route: Route) -> None:
        delayed_attach.append(route.request.url)
        # The fake provider continues in the server process while this browser
        # request waits, making manager pruning deterministic.
        time.sleep(2)
        route.continue_()

    page.route("**/api/chat/runs/**", delay_attach)

    try:
        chat = ChatView(page).goto().new_conversation()
        chat.send(slow() + say(body))
        expect(page.get_by_test_id("entry-content").last).to_contain_text(
            prefix,
            timeout=10_000,
        )
        conversation_id = _wait_for_durable_view(page, captured)

        page.reload()

        expect(page.get_by_test_id("entry-content").last).to_contain_text(
            tail,
            timeout=30_000,
        )
        chat.wait_streaming(timeout=30_000)
        assert delayed_attach, "refresh never attempted to follow the discovered run"
        expect(page.get_by_test_id("message-user")).to_have_count(1)
        expect(page.get_by_test_id("message-assistant")).to_have_count(1)
    finally:
        _cleanup(page, conversation_id)
