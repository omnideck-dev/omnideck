"""E2E test for agent network persistence across turns.

Driven by the fake LLM (MOCK_LLM): turn 1 really spawns one sub-agent
and turn 2 spawns two more. The network view should keep both turns'
agent trees visible — five agents total (two turn roots + three subs).
"""

from playwright.sync_api import Page, expect

from tests.e2e._protocol import say, spawn
from tests.e2e.pages import ChatView, NetworkView


def test_cards_persist_across_turns(page: Page):
    """Cards from turn 1 remain visible after turn 2 adds new agents."""
    chat = ChatView(page).goto().new_conversation()

    # Turn 1: root + research_agent.
    chat.send(
        spawn(say("done"), profile="research_agent", name="research_agent")
    ).wait_streaming()

    network = NetworkView(page)
    expect(network.indicator).to_be_visible(timeout=5000)
    expect(network.indicator).to_contain_text("2 agents")

    # Turn 2: root + code_expert + creative_writer.
    chat.send(
        spawn(say("done"), profile="code_expert", name="code_expert")
        + spawn(say("done"), profile="creative_writer", name="creative_writer")
    ).wait_streaming()

    # Both turns' trees stay visible: turn 1 (root + 1) + turn 2 (root + 2).
    expect(network.indicator).to_contain_text("5 agents")

    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)
    assert network.agent_cards.count() == 5

    # Turn 1 card still present.
    network.card_by_name("Research Agent")
    # Turn 2 cards added.
    network.card_by_name("Code Expert")
    network.card_by_name("Creative Writer")
