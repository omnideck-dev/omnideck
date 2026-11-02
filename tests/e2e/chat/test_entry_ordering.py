"""E2E ordering of real model thinking, content, and executed tool calls."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import call_tool, model_script, model_tool, say, spawn
from tests.e2e._runtime import agent_profile
from tests.e2e.pages import ChatView, NetworkView


@pytest.fixture
def coder_profile():
    with agent_profile() as profile:
        yield profile


SINGLE_AGENT_PROMPT = model_script(
    {"thinking": "Planning the approach", "content": "Here is my plan.",
     "tool_calls": [model_tool("run_bash_cmd", cmd="printf proof")]},
    {"thinking": "Reviewing the output", "content": "Done."},
)
CHILD_PROMPT = model_script(
    {"thinking": "Let me figure this out", "content": "Working on it.",
     "tool_calls": [model_tool("run_bash_cmd", cmd="printf child-proof")]},
    {"content": "Work completed."},
)


# ── Chat view ──────────────────────────────────────────────────────────


@pytest.mark.e2e
def test_chat_view_hides_thinking_and_tool_calls(page: Page):
    """Chat view shows only content inline; thinking and tool_calls are
    hidden and viewed via the per-turn activity footer."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(call_tool("load_skill", name="coder") + say("ready")).wait_streaming()
    chat.send(SINGLE_AGENT_PROMPT)
    chat.wait_streaming()
    page.wait_for_timeout(500)

    msg = page.get_by_test_id("message-assistant").last
    expect(msg).to_be_visible(timeout=5000)

    # Only content entries render inline — no thinking, no raw tool_call.
    expect(msg.get_by_test_id("entry-thinking")).to_have_count(0)
    expect(msg.get_by_test_id("entry-tool-call")).to_have_count(0)
    contents = msg.get_by_test_id("entry-content")
    expect(contents).to_have_count(2)
    expect(contents.nth(0)).to_contain_text("Here is my plan.")
    expect(contents.nth(1)).to_contain_text("Done.")


@pytest.mark.e2e
def test_chat_view_activity_footer_reveals_hidden(page: Page):
    """The activity footer summarises the hidden thinking + tool calls
    and reveals them in a panel on click."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(call_tool("load_skill", name="coder") + say("ready")).wait_streaming()
    chat.send(SINGLE_AGENT_PROMPT)
    chat.wait_streaming()
    page.wait_for_timeout(500)

    msg = page.get_by_test_id("message-assistant").last
    expect(msg).to_be_visible(timeout=5000)

    toggle = msg.get_by_test_id("activity-toggle")
    expect(toggle).to_be_visible()
    expect(toggle).to_contain_text("1 tool")
    expect(toggle).to_contain_text("2 thoughts")

    expect(msg.get_by_test_id("activity-panel")).to_have_count(0)
    toggle.click()

    panel = msg.get_by_test_id("activity-panel")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("Planning the approach")
    expect(panel).to_contain_text("Reviewing the output")
    expect(panel).to_contain_text("run_bash_cmd")

    # Toggling again hides the panel
    toggle.click()
    expect(msg.get_by_test_id("activity-panel")).to_have_count(0)


@pytest.mark.e2e
def test_chat_footer_counts_spawn_agent_calls(page: Page):
    """spawn_agent tool calls land in the activity log like any other tool
    call. The footer count and the expanded panel both include them.

    Regression: the streaming path used to filter spawn_agent out of the
    activity log (because the SpawnCard already showed the action), which
    made the chat footer report 0 tools on a spawn-only turn.
    """
    chat = ChatView(page).goto().new_conversation()
    chat.send(spawn(say("done"), name="worker") + say("Worker finished."))
    chat.wait_streaming()
    page.wait_for_timeout(500)

    msg = page.get_by_test_id("message-assistant").last
    expect(msg).to_be_visible(timeout=5000)

    toggle = msg.get_by_test_id("activity-toggle")
    expect(toggle).to_be_visible()
    expect(toggle).to_contain_text("1 tool")

    toggle.click()
    panel = msg.get_by_test_id("activity-panel")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("spawn_agent")
    expect(panel).to_contain_text("worker")


# ── Activity view ──────────────────────────────────────────────────────


@pytest.mark.e2e
def test_activity_view_entry_order(page: Page, coder_profile):
    """Sub-agent activity view shows thinking → content → tool_call → content
    via the ActivityRail's per-type rows."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(spawn(CHILD_PROMPT, profile=coder_profile["id"], name="helper_agent") + say("Helper finished."))
    chat.wait_streaming()
    page.wait_for_timeout(200)

    network = NetworkView(page).show_details()
    expect(network.indicator).to_be_visible(timeout=5000)
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    # Drill into the sub-agent
    activity = network.select_agent(1)
    expect(activity.root).to_be_visible(timeout=5000)

    rows = activity.root.locator(
        "[data-testid='activity-row-thinking'],"
        "[data-testid='activity-row-content'],"
        "[data-testid='activity-row-tool']"
    )
    count = rows.count()
    types = []
    for i in range(count):
        tid = rows.nth(i).get_attribute("data-testid")
        types.append(tid)
    assert types == [
        "activity-row-thinking",
        "activity-row-content",
        "activity-row-tool",
        "activity-row-content",
    ], f"Activity view entries out of order: {types}"

    expect(rows.nth(0)).to_contain_text("Let me figure this out")
    expect(rows.nth(1)).to_contain_text("Working on it.")
    expect(rows.nth(2)).to_contain_text("run_bash_cmd")
    expect(rows.nth(3)).to_contain_text("Work completed.")
