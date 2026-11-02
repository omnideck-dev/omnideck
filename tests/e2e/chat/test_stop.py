"""E2E coverage for stopping generation mid-stream.

Uses the fake provider's slow-streaming marker so the reply streams over
several seconds, giving the test a real window to click Stop while tokens
are arriving — then verifies the partial output survives the stop instead
of vanishing.
"""

from __future__ import annotations

import json
import re
import time
from uuid import uuid4

from playwright.sync_api import Page, Route, expect

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import bash, say, slow, spawn
from tests.e2e._runtime import agent_profile, delete_conversation
from tests.e2e.pages import ChatView, NetworkView

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


def test_stop_parallel_agents_preserves_all_completions_and_network_status(page: Page):
    """Stagger real shell tools so Stop must wait for the second child's exit."""
    gate = f"/home/omnideck/e2e-parallel-stop-{uuid4().hex}"
    captured_request = {}
    responses = []

    def capture_request(request):
        if request.method == "POST" and request.url.endswith("/api/chat"):
            captured_request.update(request.post_data_json)

    def capture_response(response):
        if response.request.method == "POST" and response.url.endswith("/api/chat"):
            responses.append(response)

    def release(*names):
        container_exec(
            f"from pathlib import Path; p = Path({gate!r}); p.mkdir(exist_ok=True); "
            f"[(p / (name + '-release')).touch() for name in {names!r}]"
        )

    page.on("request", capture_request)
    page.on("response", capture_response)
    try:
        with agent_profile(allow_spawn=False) as profile:
            chat = ChatView(page).goto().new_conversation()
            chat.send("".join(
                spawn(
                    bash(
                        f"mkdir -p {gate}; touch {gate}/{name}-ready; "
                        f"for attempt in {{1..400}}; do test -e {gate}/{name}-release && break; sleep .05; done; "
                        f"test -e {gate}/{name}-release"
                    ) + say("unreachable child"),
                    profile=profile["id"], name=name.upper(),
                )
                for name in ("left", "right")
            ) + say("unreachable root"))

            # These files are synchronization barriers for real shell tools,
            # not fabricated agent events. Both children must be in flight.
            deadline = time.monotonic() + 10
            while container_exec(
                f"from pathlib import Path; print(all((Path({gate!r}) / (n + '-ready')).exists() "
                "for n in ('left', 'right')))"
            ) != "True":
                assert time.monotonic() < deadline, "Both parallel child tools did not start"
                page.wait_for_timeout(100)

            conversation_id = captured_request["conversation_id"]
            chat.stop_button.click()
            release("left")
            page.wait_for_function("""async (id) => {
                const response = await fetch(`/api/conversations/sessions/${id}/resume`, {
                    method: 'POST', headers: {'X-Requested-With': 'XMLHttpRequest'},
                });
                const snapshot = await response.json();
                return snapshot.events.some(e => e.type === 'agent_completed' && e.agent_name === 'LEFT');
            }""", arg=conversation_id)
            snapshot = page.request.post(f"/api/conversations/sessions/{conversation_id}/resume").json()
            assert snapshot["active_run"] is not None, "Parent ended while RIGHT's tool was still active"
            expect(chat.stop_button).to_be_visible()

            release("right")
            chat.wait_streaming()
            assert len(responses) == 1
            streamed = [json.loads(line) for line in responses[0].text().splitlines() if line.strip()]
            starts = [e["payload"] for e in streamed if e["payload"]["type"] == "agent_started"]
            ends = [e["payload"] for e in streamed if e["payload"]["type"] == "agent_completed"]
            assert len(starts) == len(ends) == 3
            assert {e["agent_id"] for e in starts} == {e["agent_id"] for e in ends}
            assert [e["agent_name"] for e in ends[:2]] == ["LEFT", "RIGHT"]
            assert all(e["status"] == "stopped" for e in ends)
            assert [e["seq"] for e in streamed] == list(range(1, len(streamed) + 1))
            assert sum(e["payload"]["type"] == "turn_end" for e in streamed) == 1
            assert streamed[-1]["payload"]["type"] == "turn_end"

            snapshot = page.request.post(f"/api/conversations/sessions/{conversation_id}/resume").json()
            assert snapshot["active_run"] is None
            persisted = [e for e in snapshot["events"] if e["type"] == "agent_completed"]
            assert [(e["agent_id"], e["status"]) for e in persisted] == [
                (e["agent_id"], e["status"]) for e in ends
            ]
            # Check the live UI before reloading: replay must not mask a lost event.
            network = NetworkView(page).open()
            expect(network.agent_cards).to_have_count(3)
            for index in range(3):
                expect(network.card(index).status_dot).to_have_class(re.compile(r".*idle.*"))
    finally:
        release("left", "right")
        if captured_request.get("conversation_id"):
            delete_conversation(captured_request["conversation_id"])
        container_exec(f"import shutil; shutil.rmtree({gate!r}, ignore_errors=True)")
        page.remove_listener("request", capture_request)
        page.remove_listener("response", capture_response)
