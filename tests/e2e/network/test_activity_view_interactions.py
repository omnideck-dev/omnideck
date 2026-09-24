"""E2E tests for activity view interactions: instruction toggle + tool-call expand.

Driven by the fake LLM (MOCK_LLM): the root really spawns a helper
sub-agent whose instruction is a multi-line brief and which runs a
write_file tool — so the instruction-collapse and tool-row-expand
widgets render off genuine lifecycle events.

A real sub-agent's instruction is the spawn body, so the prose brief
lives there alongside the directive that makes the sub act.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import spawn, write_file
from tests.e2e.pages import ChatView, NetworkView

_INSTRUCTION = (
    "First line summary.\n\n"
    "Longer detail that only appears when the instruction is expanded."
)


def _open_helper_activity(page: Page):
    chat = ChatView(page).goto().new_conversation()
    # code_expert has the coder skill pre-loaded, so write_file runs
    # without an intervening load_skill step. A relative path keeps the
    # tool row's first arg compact ("config.yaml").
    chat.send(spawn(
        _INSTRUCTION + "\n" + write_file("config.yaml", "debug: true"),
        profile="code_expert",
        name="helper_agent",
    )).wait_streaming()

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
    expect(tool_row).to_contain_text("write_file")
    # Collapsed line only shows the first arg, the rest are hidden behind …
    expect(tool_row).to_contain_text("path=")
    expect(tool_row).to_contain_text('"config.yaml"')
    expect(activity.root.get_by_test_id("activity-tool-detail")).to_have_count(0)

    tool_row.click()
    detail = activity.root.get_by_test_id("activity-tool-detail")
    expect(detail).to_be_visible()
    expect(detail).to_contain_text("path")
    expect(detail).to_contain_text('"config.yaml"')
    expect(detail).to_contain_text("content")
    expect(detail).to_contain_text('"debug: true"')

    # Toggling again collapses
    tool_row.click()
    expect(activity.root.get_by_test_id("activity-tool-detail")).to_have_count(0)
