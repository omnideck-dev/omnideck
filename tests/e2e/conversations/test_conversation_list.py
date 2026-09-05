"""E2E conversation management using actual FakeProvider turns and public APIs."""

import time

from playwright.sync_api import Page, expect

from tests.e2e._protocol import say
from tests.e2e._runtime import create_conversation, delete_conversation
from tests.e2e.pages import ChatView, RecentConversations


def test_recent_list_is_visible_on_load(page: Page):
    """The recent-conversations list is present in the expanded sidebar."""
    ChatView(page).goto()
    expect(RecentConversations(page).root).to_be_visible()


def test_conversation_appears_after_real_message(page: Page):
    """A conversation shows up in the recent list after a turn."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(say("yes")).wait_streaming()

    recent = RecentConversations(page)
    expect(recent.items.first).to_be_visible(timeout=10_000)


def test_search_filters_the_recent_list(page: Page):
    """Typing in the search box narrows the list to matching titles."""
    nonce = time.time_ns()
    keep_id = f"e2e_search_keep_{nonce}"
    other_id = f"e2e_search_other_{nonce}"
    create_conversation(keep_id, [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
    ], title=f"FindMe {nonce}")
    create_conversation(other_id, [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
    ], title=f"Unrelated {nonce}")

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.items.first).to_be_visible(timeout=5000)

        recent.search.fill(f"FindMe {nonce}")
        expect(page.get_by_text(f"FindMe {nonce}")).to_be_visible()
        expect(page.get_by_text(f"Unrelated {nonce}")).not_to_be_visible()
    finally:
        delete_conversation(keep_id)
        delete_conversation(other_id)


def test_clear_search_button_resets_the_filter(page: Page):
    """The clear button empties the search box and restores the full list."""
    nonce = time.time_ns()
    keep_id = f"e2e_clear_keep_{nonce}"
    other_id = f"e2e_clear_other_{nonce}"
    create_conversation(keep_id, [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
    ], title=f"FindMe {nonce}")
    create_conversation(other_id, [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
    ], title=f"Unrelated {nonce}")

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.items.first).to_be_visible(timeout=5000)

        # No clear button until there's a query.
        expect(recent.search_clear).not_to_be_visible()

        recent.search.fill(f"FindMe {nonce}")
        expect(page.get_by_text(f"Unrelated {nonce}")).not_to_be_visible()

        recent.search_clear.click()
        expect(recent.search).to_have_value("")
        expect(recent.search_clear).not_to_be_visible()
        expect(page.get_by_text(f"FindMe {nonce}")).to_be_visible()
        expect(page.get_by_text(f"Unrelated {nonce}")).to_be_visible()
    finally:
        delete_conversation(keep_id)
        delete_conversation(other_id)


def test_deleting_active_conversation_opens_a_new_one(page: Page):
    """Deleting the currently open conversation clears the chat into a fresh one."""
    nonce = time.time_ns()
    conv_id = f"e2e_delete_active_{nonce}"
    title = f"DeleteActive {nonce}"
    create_conversation(conv_id, [
        {"role": "user", "content": f"OPEN_MARKER_{nonce}"},
        {"role": "assistant", "content": "I am open."},
    ], title=title)

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.items.first).to_be_visible(timeout=5000)

        # Open it so it becomes the active conversation.
        recent.open_by_id(conv_id)
        user_msgs = page.get_by_test_id("message-user")
        expect(user_msgs.first).to_contain_text(f"OPEN_MARKER_{nonce}", timeout=10_000)

        # Deleting the active conversation starts a fresh, empty one.
        recent.item_by_id(conv_id).delete()
        expect(page.get_by_text(title)).not_to_be_visible()
        expect(page.get_by_test_id("message-user")).to_have_count(0)
    finally:
        delete_conversation(conv_id)


def test_multiple_conversations_listed_in_recency_order(page: Page):
    """Created conversations appear in most-recent-first order."""
    nonce = time.time_ns()
    ids = [f"e2e_order_{i}_{nonce}" for i in range(3)]
    titles = [f"Conv {chr(65 + i)} {nonce}" for i in range(3)]

    for i, (cid, title) in enumerate(zip(ids, titles)):
        create_conversation(cid, [
            {"role": "user", "content": f"msg {i}"},
            {"role": "assistant", "content": f"reply {i}"},
        ], title=title)
        time.sleep(0.2)

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.items.first).to_be_visible(timeout=5000)

        # Restrict the list order to our own conversations — other rows (e.g. a pinned
        # welcome conversation) may sit among them — and assert those appear
        # most-recent-first, i.e. the reverse of creation order.
        created = set(ids)
        mine = [cid for cid in recent.order() if cid in created]
        assert mine == ids[::-1], f"expected newest-first {ids[::-1]}, got {mine}"
    finally:
        for cid in ids:
            delete_conversation(cid)


def test_switch_between_conversations(page: Page):
    """Clicking a row loads that conversation's messages into the chat view."""
    nonce = time.time_ns()
    older_id = f"e2e_switch_old_{nonce}"
    newer_id = f"e2e_switch_new_{nonce}"

    create_conversation(older_id, [
        {"role": "user", "content": f"ALPHA_MARKER_{nonce}"},
        {"role": "assistant", "content": "I see alpha."},
    ], title=f"Alpha Conv {nonce}")

    time.sleep(0.2)

    create_conversation(newer_id, [
        {"role": "user", "content": f"BETA_MARKER_{nonce}"},
        {"role": "assistant", "content": "I see beta."},
    ], title=f"Beta Conv {nonce}")

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.items.first).to_be_visible(timeout=5000)

        # Load the newer conversation by id.
        recent.open_by_id(newer_id)

        user_msgs = page.get_by_test_id("message-user")
        expect(user_msgs.first).to_contain_text(
            f"BETA_MARKER_{nonce}", timeout=10_000
        )
        assistant_msgs = page.get_by_test_id("message-assistant")
        expect(assistant_msgs.first).to_contain_text("I see beta.")

        # Switch to the older conversation by id.
        recent.open_by_id(older_id)
        expect(user_msgs.first).to_contain_text(
            f"ALPHA_MARKER_{nonce}", timeout=10_000
        )
        expect(assistant_msgs.first).to_contain_text("I see alpha.")
    finally:
        delete_conversation(older_id)
        delete_conversation(newer_id)


def test_delete_conversation(page: Page):
    """Deleting a conversation removes it from the list by identity."""
    nonce = time.time_ns()
    keep_id = f"e2e_keep_{nonce}"
    delete_id = f"e2e_delete_{nonce}"
    keep_title = f"KeepMe {nonce}"
    delete_title = f"DeleteMe {nonce}"

    create_conversation(keep_id, [
        {"role": "user", "content": "I should survive"},
        {"role": "assistant", "content": "Noted."},
    ], title=keep_title)

    time.sleep(0.2)

    create_conversation(delete_id, [
        {"role": "user", "content": "I will be deleted"},
        {"role": "assistant", "content": "Goodbye."},
    ], title=delete_title)

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.items.first).to_be_visible(timeout=5000)

        expect(page.get_by_text(delete_title)).to_be_visible()
        expect(page.get_by_text(keep_title)).to_be_visible()

        # Delete one of them by id, not by position.
        recent.item_by_id(delete_id).delete()
        page.wait_for_timeout(1000)

        expect(page.get_by_text(delete_title)).not_to_be_visible()
        expect(page.get_by_text(keep_title)).to_be_visible()
    finally:
        delete_conversation(keep_id)
        delete_conversation(delete_id)
