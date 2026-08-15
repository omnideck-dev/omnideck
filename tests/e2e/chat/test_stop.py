"""E2E coverage for stopping generation mid-stream.

Uses the fake provider's slow-streaming marker so the reply streams over
several seconds, giving the test a real window to click Stop while tokens
are arriving — then verifies the partial output survives the stop instead
of vanishing.
"""

from __future__ import annotations

import json

from playwright.sync_api import Page, Route, expect

from tests.e2e._protocol import say, slow
from tests.e2e.pages import ChatView

# Long enough to stream for ~7s at the fake's slow pace. The tail marker
# must never appear in the chat: the stop lands long before the end.
_BODY = ("streaming word salad " * 120).strip()
_TAIL = "ZZZTAIL-NEVER-REACHED"


def test_stop_mid_stream_keeps_partial_text(page: Page):
    """Stop persists the partial response and closes one stopped lifecycle."""
    chat = ChatView(page).goto().new_conversation()

    captured_request: dict = {}
    chat_responses = []

    def capture_request(route: Route) -> None:
        captured_request.update(json.loads(route.request.post_data or "{}"))
        route.continue_()

    page.route("**/api/chat", capture_request)
    page.on(
        "response",
        lambda response: chat_responses.append(response)
        if response.request.method == "POST" and response.url.endswith("/api/chat")
        else None,
    )

    chat.send(slow() + say(f"{_BODY} {_TAIL}"))

    # Wait until real streamed text is visible, then stop.
    content = page.get_by_test_id("entry-content").last
    expect(content).to_contain_text("streaming word salad", timeout=10_000)
    chat.stop_button.click()

    chat.wait_streaming()

    # The partial the user watched stream is still there, the tail never
    # arrived, and the composer is back to its idle state.
    expect(content).to_contain_text("streaming word salad")
    expect(content).not_to_contain_text(_TAIL)
    expect(chat.stop_button).not_to_be_visible()

    # The transport closes with exactly one terminal domain event.
    assert len(chat_responses) == 1
    streamed = [json.loads(line) for line in chat_responses[0].text().splitlines() if line.strip()]
    streamed_types = [event["payload"]["type"] for event in streamed]
    assert streamed_types.count("turn_end") == 1
    assert streamed_types[-1] == "turn_end"

    # The canonical stopped lifecycle and partial iteration were persisted,
    # not merely left in transient browser state.
    conversation_id = captured_request["conversation_id"]
    resume = page.request.post(
        f"/api/conversations/sessions/{conversation_id}/resume",
    )
    assert resume.ok, f"resume failed with {resume.status}: {resume.text()}"
    events = resume.json()["events"]
    root_completions = [event for event in events if event["type"] == "agent_completed" and event["depth"] == 0]
    assert len(root_completions) == 1
    assert root_completions[0]["status"] == "stopped"

    partials = [event for event in events if event["type"] == "iteration" and event.get("stopped") is True]
    assert len(partials) == 1
    assert "streaming word salad" in (partials[0].get("content") or "")
    assert _TAIL not in (partials[0].get("content") or "")
