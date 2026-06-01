"""E2E tests for activity view interactions: instruction toggle + tool-call expand.

These verify behaviors that have unit coverage but are easy to break in
the real rendered DOM (CSS transitions, click handler wiring, real
event-loop ordering with the streaming pipeline).
"""

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.network._sse import _evt, build_jsonl
from tests.e2e.pages import ChatView, NetworkView


# Sub-agent has a multi-line instruction and one tool call with multiple
# arguments — enough to exercise both the instruction toggle and the
# tool-call expand interaction.
INSTRUCTED_AGENT_EVENTS = build_jsonl([
    _evt({"type": "agent_started", "agent_id": "root",
          "agent_name": "computron", "parent_agent_id": None},
         agent_id="root", agent_name="computron"),
    _evt({"type": "user_message", "content": "do the work",
          "attachments": [], "is_nudge": False},
         agent_id="root", agent_name="computron"),
    _evt({"type": "content", "content": "Spawning a helper."},
         agent_id="root", agent_name="computron"),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "Spawning a helper.", "thinking": None,
          "tool_calls": []},
         agent_id="root", agent_name="computron"),
    _evt({"type": "agent_started", "agent_id": "sub1",
          "agent_name": "helper_agent", "parent_agent_id": "root",
          "instruction": "First line summary.\n\nLonger detail that only appears when the instruction is expanded."},
         agent_id="sub1", agent_name="helper_agent", depth=1),
    _evt({"type": "content", "content": "Working on it."},
         agent_id="sub1", agent_name="helper_agent", depth=1),
    _evt({"type": "tool_call", "name": "replace_in_file",
          "arguments": {"path": "config.yaml", "old": "debug: false",
                        "new": "debug: true"}},
         agent_id="sub1", agent_name="helper_agent", depth=1),
    _evt({"type": "content", "content": "Done."},
         agent_id="sub1", agent_name="helper_agent", depth=1),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "Working on it.\nDone.", "thinking": None,
          "tool_calls": [{"id": "tc1", "name": "replace_in_file",
                          "arguments": {"path": "config.yaml",
                                         "old": "debug: false",
                                         "new": "debug: true"}}]},
         agent_id="sub1", agent_name="helper_agent", depth=1),
    _evt({"type": "agent_completed", "agent_id": "sub1",
          "agent_name": "helper_agent", "status": "success"},
         agent_id="sub1", agent_name="helper_agent", depth=1),
    _evt({"type": "content", "content": "Helper finished."},
         agent_id="root", agent_name="computron"),
    _evt({"type": "iteration", "iteration_index": 1,
          "content": "Helper finished.", "thinking": None,
          "tool_calls": []},
         agent_id="root", agent_name="computron"),
    _evt({"type": "agent_completed", "agent_id": "root",
          "agent_name": "computron", "status": "success"},
         agent_id="root", agent_name="computron"),
    _evt({"type": "turn_end"},
         agent_id="root", agent_name="computron"),
])


def _mock_chat_with(body: str):
    def handler(route: Route):
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=body,
        )
    return handler


def _open_helper_activity(page: Page):
    chat = ChatView(page).goto().new_conversation()
    page.route("**/api/chat", _mock_chat_with(INSTRUCTED_AGENT_EVENTS))
    chat.send("test")
    chat.wait_streaming()
    page.wait_for_timeout(200)

    network = NetworkView(page)
    expect(network.indicator).to_be_visible(timeout=5000)
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    activity = network.select_agent(1)
    expect(activity.root).to_be_visible(timeout=5000)
    return activity


@pytest.mark.e2e
def test_activity_view_instruction_starts_collapsed_and_toggles(page: Page):
    """Instruction bar starts collapsed (preview only), click expands the body."""
    activity = _open_helper_activity(page)

    toggle = activity.root.get_by_test_id("instruction-toggle")
    expect(toggle).to_be_visible()
    # Preview shows the first line; full body is not yet rendered.
    expect(toggle).to_contain_text("First line summary")
    expect(activity.root.get_by_test_id("instruction-body")).to_have_count(0)

    toggle.click()
    body = activity.root.get_by_test_id("instruction-body")
    expect(body).to_be_visible()
    expect(body).to_contain_text("First line summary")
    expect(body).to_contain_text("Longer detail")

    # Toggling again collapses
    toggle.click()
    expect(activity.root.get_by_test_id("instruction-body")).to_have_count(0)


@pytest.mark.e2e
def test_activity_view_tool_call_expand(page: Page):
    """Tool-call row is collapsed by default; click reveals all args."""
    activity = _open_helper_activity(page)

    tool_row = activity.root.get_by_test_id("activity-tool-call")
    expect(tool_row).to_be_visible()
    expect(tool_row).to_contain_text("replace_in_file")
    # Collapsed line only shows the first arg, the rest are hidden behind …
    expect(tool_row).to_contain_text("path=")
    expect(tool_row).to_contain_text('"config.yaml"')
    expect(activity.root.get_by_test_id("activity-tool-detail")).to_have_count(0)

    tool_row.click()
    detail = activity.root.get_by_test_id("activity-tool-detail")
    expect(detail).to_be_visible()
    expect(detail).to_contain_text("path")
    expect(detail).to_contain_text('"config.yaml"')
    expect(detail).to_contain_text("old")
    expect(detail).to_contain_text('"debug: false"')
    expect(detail).to_contain_text("new")
    expect(detail).to_contain_text('"debug: true"')

    # Toggling again collapses
    tool_row.click()
    expect(activity.root.get_by_test_id("activity-tool-detail")).to_have_count(0)
