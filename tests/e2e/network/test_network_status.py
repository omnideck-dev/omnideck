"""E2E test for agent card status dot colors.

Driven by the fake LLM (MOCK_LLM): real sub-agents reach genuine
success / error / running states, so the cards' status dots reflect
actual agent-lifecycle events — no canned event shapes to drift from
the backend.

  - error:   a sub-agent runs a FAIL directive → raises → status "error".
  - success: a sub-agent replies and completes → status "success".
  - running: a sub-agent runs a slow command (sleep) and is observed
             mid-execution → status "running", then "complete".
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, fail, say, spawn
from tests.e2e.pages import ChatView, NetworkView

LLM_TIMEOUT = 180_000


def test_error_agent_shows_error_dot(page: Page):
    """A failed sub-agent card displays the 'error' status dot.

    The sub raises; spawn_agent surfaces that to the root as an error
    tool-result, so the root still completes — only the sub is errored.
    """
    chat = ChatView(page).goto().new_conversation()
    chat.send(
        spawn(fail("boom"), name="failing_agent")
    ).wait_streaming(timeout=LLM_TIMEOUT)

    network = NetworkView(page)
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    fail_card = network.card_by_name("Failing Agent")
    dot_class = fail_card.status_dot.get_attribute("class") or ""
    assert "error" in dot_class, f"Expected 'error' in class, got: {dot_class}"


def test_success_agent_shows_complete_dot(page: Page):
    """A successful sub-agent card displays the 'complete' status dot."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(
        spawn(say("done"), name="successful_agent")
    ).wait_streaming(timeout=LLM_TIMEOUT)

    network = NetworkView(page)
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    ok_card = network.card_by_name("Successful Agent")
    dot_class = ok_card.status_dot.get_attribute("class") or ""
    assert "complete" in dot_class, f"Expected 'complete' in class, got: {dot_class}"


def test_running_agent_shows_running_dot(page: Page):
    """An in-progress sub-agent shows the 'running' dot, then 'complete'.

    The sub runs a slow bash command, so it's genuinely mid-execution
    when we inspect the card; after it finishes the dot transitions.
    """
    chat = ChatView(page).goto().new_conversation()
    # Slow command keeps the sub-agent running long enough to observe.
    chat.send(spawn(bash("sleep 8"), name="working_agent"))

    # Don't wait_streaming yet — observe the running state mid-sleep.
    network = NetworkView(page)
    expect(network.indicator).to_be_visible(timeout=30_000)
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    working_card = network.card_by_name("Working Agent")
    dot = working_card.status_dot
    dot_class = dot.get_attribute("class") or ""
    assert "running" in dot_class, f"Expected 'running' in class, got: {dot_class}"

    # Let the sleep finish; the dot transitions to 'complete'.
    chat.wait_streaming(timeout=LLM_TIMEOUT)
    page.wait_for_timeout(500)
    dot_class = dot.get_attribute("class") or ""
    assert "complete" in dot_class, f"Expected 'complete' after finish, got: {dot_class}"
