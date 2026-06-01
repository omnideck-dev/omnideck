"""E2E test for agent card status dot colors.

Verifies that agent cards display the correct status dot classes for
success, error, and running states.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.network._sse import _evt, build_jsonl
from tests.e2e.pages import ChatView, NetworkView


# ── Mock with mixed success/error outcomes ───────────────────────────────

MIXED_STATUS_EVENTS = build_jsonl([
    _evt({"type": "agent_started", "agent_id": "root",
          "agent_name": "computron", "parent_agent_id": None},
         agent_id="root", agent_name="computron"),
    _evt({"type": "user_message", "content": "go",
          "attachments": [], "is_nudge": False},
         agent_id="root", agent_name="computron"),
    _evt({"type": "agent_started", "agent_id": "ok_agent",
          "agent_name": "successful_agent", "parent_agent_id": "root"},
         agent_id="ok_agent", agent_name="successful_agent", depth=1),
    _evt({"type": "agent_started", "agent_id": "fail_agent",
          "agent_name": "failing_agent", "parent_agent_id": "root"},
         agent_id="fail_agent", agent_name="failing_agent", depth=1),
    _evt({"type": "content", "content": "Success."},
         agent_id="ok_agent", agent_name="successful_agent", depth=1),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "Success.", "thinking": None, "tool_calls": []},
         agent_id="ok_agent", agent_name="successful_agent", depth=1),
    _evt({"type": "content", "content": "About to fail."},
         agent_id="fail_agent", agent_name="failing_agent", depth=1),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "About to fail.", "thinking": None, "tool_calls": []},
         agent_id="fail_agent", agent_name="failing_agent", depth=1),
    _evt({"type": "agent_completed", "agent_id": "ok_agent",
          "agent_name": "successful_agent", "status": "success"},
         agent_id="ok_agent", agent_name="successful_agent", depth=1),
    _evt({"type": "agent_completed", "agent_id": "fail_agent",
          "agent_name": "failing_agent", "status": "error"},
         agent_id="fail_agent", agent_name="failing_agent", depth=1),
    _evt({"type": "content", "content": "One failed."},
         agent_id="root", agent_name="computron"),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "One failed.", "thinking": None, "tool_calls": []},
         agent_id="root", agent_name="computron"),
    _evt({"type": "agent_completed", "agent_id": "root",
          "agent_name": "computron", "status": "success"},
         agent_id="root", agent_name="computron"),
    _evt({"type": "turn_end"}, agent_id="root", agent_name="computron"),
])


# ── Mock with agents still running (no turn_end) ────────────────────────
# Uses a streaming HTTP server so Playwright's fetch stays open, keeping
# the stop button visible and agents in "running" state.

RUNNING_EVENTS = build_jsonl([
    _evt({"type": "agent_started", "agent_id": "root",
          "agent_name": "computron", "parent_agent_id": None},
         agent_id="root", agent_name="computron"),
    _evt({"type": "user_message", "content": "do work",
          "attachments": [], "is_nudge": False},
         agent_id="root", agent_name="computron"),
    _evt({"type": "agent_started", "agent_id": "working",
          "agent_name": "working_agent", "parent_agent_id": "root"},
         agent_id="working", agent_name="working_agent", depth=1),
    _evt({"type": "content", "content": "Working..."},
         agent_id="working", agent_name="working_agent", depth=1),
])


class _StreamingHandler(BaseHTTPRequestHandler):
    """Streams RUNNING_EVENTS then blocks until the test signals done."""

    complete_event = threading.Event()

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        self.wfile.write(RUNNING_EVENTS.encode())
        self.wfile.flush()
        # Hold connection open so frontend stays in streaming state
        self.complete_event.wait(timeout=30)
        # Send completion events
        finish = build_jsonl([
            _evt({"type": "agent_completed", "agent_id": "working",
                  "agent_name": "working_agent", "status": "success"},
                 agent_id="working", agent_name="working_agent", depth=1),
            _evt({"type": "agent_completed", "agent_id": "root",
                  "agent_name": "computron", "status": "success"},
                 agent_id="root", agent_name="computron"),
            _evt({"type": "turn_end"},
                 agent_id="root", agent_name="computron"),
        ])
        self.wfile.write(finish.encode())
        self.wfile.flush()

    def log_message(self, *args):
        pass


@pytest.fixture
def streaming_server():
    """Start a local HTTP server that streams events with a pause."""
    _StreamingHandler.complete_event.clear()
    server = HTTPServer(("127.0.0.1", 9199), _StreamingHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield server
    _StreamingHandler.complete_event.set()
    server.shutdown()


# ── Tests ────────────────────────────────────────────────────────────────


def test_error_agent_shows_error_dot(page: Page):
    """A failed agent card displays the 'error' status dot."""
    chat = ChatView(page).goto().new_conversation()

    def mock(route: Route):
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=MIXED_STATUS_EVENTS,
        )

    page.route("**/api/chat", mock)
    chat.send("test")
    chat.wait_streaming()

    network = NetworkView(page)
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    fail_card = network.card_by_name("Failing Agent")
    dot = fail_card.status_dot
    dot_class = dot.get_attribute("class") or ""
    assert "error" in dot_class, f"Expected 'error' in class, got: {dot_class}"


def test_success_agent_shows_complete_dot(page: Page):
    """A successful agent card displays the 'complete' status dot."""
    chat = ChatView(page).goto().new_conversation()

    def mock(route: Route):
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=MIXED_STATUS_EVENTS,
        )

    page.route("**/api/chat", mock)
    chat.send("test")
    chat.wait_streaming()

    network = NetworkView(page)
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    ok_card = network.card_by_name("Successful Agent")
    dot = ok_card.status_dot
    dot_class = dot.get_attribute("class") or ""
    assert "complete" in dot_class, f"Expected 'complete' in class, got: {dot_class}"


def test_running_agent_shows_running_dot(page: Page, streaming_server):
    """An in-progress agent card shows the 'running' (pulsing) status dot."""
    chat = ChatView(page).goto().new_conversation()

    # Route /api/chat to our streaming server that holds the connection open
    def route_to_server(route: Route):
        route.continue_(url="http://127.0.0.1:9199/api/chat")

    page.route("**/api/chat", route_to_server)
    chat.send("test")

    # Don't wait_streaming — the stream is intentionally held open.
    # Wait for the network indicator to appear (sub-agent spawned).
    network = NetworkView(page)
    expect(network.indicator).to_be_visible(timeout=10_000)

    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    working_card = network.card_by_name("Working Agent")
    dot = working_card.status_dot
    dot_class = dot.get_attribute("class") or ""
    assert "running" in dot_class, f"Expected 'running' in class, got: {dot_class}"

    # Signal the server to finish, let the stream complete
    _StreamingHandler.complete_event.set()
    chat.wait_streaming()

    # After completion, dot should transition to 'complete'
    page.wait_for_timeout(500)
    dot_class = dot.get_attribute("class") or ""
    assert "complete" in dot_class, f"Expected 'complete' after finish, got: {dot_class}"
