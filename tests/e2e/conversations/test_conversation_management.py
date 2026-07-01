"""E2E tests for sidebar chat management: the 3-dot menu, renaming, pinning.

Seeds conversations directly in the container for speed/determinism, then
drives the per-row context menu to rename, pin, and unpin them. Renames and
pins are asserted to survive a reload, proving they persist server-side.
"""

import json
import time
from datetime import UTC, datetime, timedelta

from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import ChatView, RecentConversations

CONV_DIR = "/var/lib/computron/conversations"


def _seed_conversation(
    conv_id: str,
    messages: list[dict],
    *,
    title: str = "",
    pinned: bool = False,
) -> str:
    """Create a conversation on disk inside the container.

    Writes an events.jsonl (the store's source of truth) — an agent_started
    anchor plus a user_message per user message — so the conversation is
    recognized and reports the right first message / started_at.
    """
    # started_at = first event timestamp, which the sidebar sorts on. Use a
    # current time so the seeded conversation lands at the top of the list
    # (the tests operate on item(0)); a fixed past date would sink it below
    # other conversations the shared e2e container has accumulated.
    base = datetime.now(UTC)
    events: list[dict] = [{
        "id": f"evt_{conv_id}_started", "type": "agent_started",
        "timestamp": base.isoformat(), "conversation_id": conv_id,
        "agent_id": "root.test.1", "agent_name": "TEST",
        "parent_agent_id": None, "depth": 0,
    }]
    n = 0
    for m in messages:
        if m.get("role") != "user":
            continue
        n += 1
        events.append({
            "id": f"evt_{conv_id}_{n}", "type": "user_message",
            "timestamp": (base + timedelta(seconds=n)).isoformat(),
            "conversation_id": conv_id, "agent_id": "root.test.1",
            "agent_name": "TEST", "depth": 0,
            "content": m.get("content", ""), "attachments": [],
        })
    events_jsonl = "\n".join(json.dumps(e) for e in events) + "\n"
    script = (
        "import pathlib\n"
        f"d = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "d.mkdir(parents=True, exist_ok=True)\n"
        f"(d / 'events.jsonl').write_text({events_jsonl!r})\n"
    )
    meta: dict = {}
    if title:
        meta["title"] = title
    if pinned:
        meta["pinned"] = True
    if meta:
        script += f"(d / 'metadata.json').write_text({json.dumps(meta)!r})\n"
    script += f"print('{conv_id}')\n"
    return container_exec(script)


def _delete_conversation(conv_id: str) -> None:
    """Remove a seeded conversation from the container."""
    container_exec(
        "import shutil, pathlib\n"
        f"p = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "if p.exists(): shutil.rmtree(p)\n"
    )


def test_row_menu_exposes_pin_rename_delete(page: Page):
    """The 3-dot menu opens with Pin, Rename, and Delete actions."""
    nonce = time.time_ns()
    conv_id = f"e2e_menu_{nonce}"
    _seed_conversation(conv_id, [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
    ], title=f"MenuChat {nonce}")

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.items.first).to_be_visible(timeout=5000)

        recent.item_by_id(conv_id).open_menu()
        expect(page.get_by_test_id("recent-menu-pin")).to_have_text("Pin")
        expect(page.get_by_test_id("recent-menu-rename")).to_be_visible()
        expect(page.get_by_test_id("recent-menu-delete")).to_be_visible()

        # Clicking outside closes the menu.
        page.keyboard.press("Escape")
        expect(page.get_by_test_id("recent-menu")).not_to_be_visible()
    finally:
        _delete_conversation(conv_id)


def test_rename_conversation_persists(page: Page):
    """Renaming via the menu updates the row and survives a reload."""
    nonce = time.time_ns()
    conv_id = f"e2e_rename_{nonce}"
    old_title = f"OldName {nonce}"
    new_title = f"NewName {nonce}"
    _seed_conversation(conv_id, [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
    ], title=old_title)

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(page.get_by_text(old_title)).to_be_visible(timeout=5000)

        recent.item_by_id(conv_id).rename(new_title)
        expect(page.get_by_text(new_title)).to_be_visible()
        expect(page.get_by_text(old_title)).not_to_be_visible()

        # Reload: the new title was persisted server-side.
        page.reload()
        expect(page.get_by_text(new_title)).to_be_visible(timeout=5000)
    finally:
        _delete_conversation(conv_id)


def test_rename_blank_reverts_to_first_message(page: Page):
    """Saving an empty rename falls back to the first message, not a blank row."""
    nonce = time.time_ns()
    conv_id = f"e2e_rename_blank_{nonce}"
    first_message = f"first prompt {nonce}"
    _seed_conversation(conv_id, [
        {"role": "user", "content": first_message},
        {"role": "assistant", "content": "ok"},
    ], title=f"Titled {nonce}")

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(page.get_by_text(f"Titled {nonce}")).to_be_visible(timeout=5000)

        recent.item_by_id(conv_id).open_menu()
        page.get_by_test_id("recent-menu-rename").click()
        field = page.get_by_test_id("recent-rename-input")
        field.fill("")
        page.get_by_test_id("recent-rename-save").click()

        expect(page.get_by_text(first_message)).to_be_visible()
        expect(page.get_by_text(f"Titled {nonce}")).not_to_be_visible()
    finally:
        _delete_conversation(conv_id)


def test_pin_conversation_marks_row_pinned(page: Page):
    """Pinning marks the row pinned and survives a reload.

    Asserts the pinned state of this conversation's own row (via data-pinned)
    rather than the global Pinned section, so it's unaffected by any other
    pinned conversation that may already exist.
    """
    nonce = time.time_ns()
    conv_id = f"e2e_pin_{nonce}"
    title = f"PinMe {nonce}"
    _seed_conversation(conv_id, [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
    ], title=title)

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.item_by_id(conv_id).root).to_have_attribute("data-pinned", "false", timeout=5000)

        recent.item_by_id(conv_id).toggle_pin()
        expect(recent.item_by_id(conv_id).root).to_have_attribute("data-pinned", "true")

        # Reload: the pin was persisted server-side.
        page.reload()
        expect(recent.item_by_id(conv_id).root).to_have_attribute("data-pinned", "true", timeout=5000)
    finally:
        _delete_conversation(conv_id)


def test_unpin_conversation_clears_row_pin(page: Page):
    """Unpinning a pinned chat clears its row's pinned state."""
    nonce = time.time_ns()
    conv_id = f"e2e_unpin_{nonce}"
    title = f"UnpinMe {nonce}"
    _seed_conversation(conv_id, [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
    ], title=title, pinned=True)

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.item_by_id(conv_id).root).to_have_attribute("data-pinned", "true", timeout=5000)

        # The menu reads "Unpin" for an already-pinned chat.
        recent.item_by_id(conv_id).open_menu()
        expect(page.get_by_test_id("recent-menu-pin")).to_have_text("Unpin")
        page.get_by_test_id("recent-menu-pin").click()

        expect(recent.item_by_id(conv_id).root).to_have_attribute("data-pinned", "false")
    finally:
        _delete_conversation(conv_id)
