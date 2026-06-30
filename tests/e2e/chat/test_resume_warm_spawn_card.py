"""E2E: a warm-resumed conversation should restore its sub-agent spawn card.

Drives a real sub-agent spawn through the fake provider, then reopens the
still-warm conversation from the recent list. The inline spawn card is rebuilt
from the spawn_requested event; the in-memory log retains it, so the warm resume
restores the card the same way a cold disk resume does.

Regression guard for the warm-resume bug where the in-memory log dropped
spawn_requested and the spawn card vanished when a conversation was served from
the cache.
"""

from playwright.sync_api import Page, expect

from tests.e2e._protocol import say, spawn
from tests.e2e.pages import ChatView, RecentConversations


def test_warm_resume_restores_spawn_card(page: Page):
    """Reopening a still-cached conversation should show its sub-agent spawn card."""
    ChatView(page).goto().new_conversation().send(
        # The display name is title-cased per word for the row label, so
        # "alpha_agent" renders as "Alpha Agent".
        spawn(say("done"), name="alpha_agent") + say("done"),
    ).wait_streaming()
    expect(page.get_by_test_id("spawn-card")).to_be_visible(timeout=8_000)

    # Leave the conversation (it stays warm in the backend cache), then reopen
    # the most-recent one — a real warm resume.
    ChatView(page).new_conversation()
    RecentConversations(page).open_top()

    # The transcript should rebuild the inline spawn card from spawn_requested.
    card = page.get_by_test_id("spawn-card")
    expect(card).to_be_visible(timeout=8_000)
    expect(card).to_contain_text("Alpha Agent")
