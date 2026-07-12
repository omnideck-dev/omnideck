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


def _purge_conversation(conv_id: str) -> None:
    """Remove a seeded conversation from both the active and archived areas.

    Archiving moves the directory, so a test that archives could leave it in
    either place depending on where it stopped; clean up both.
    """
    container_exec(
        "import shutil, pathlib\n"
        f"for p in (pathlib.Path('{CONV_DIR}/{conv_id}'), "
        f"pathlib.Path('{CONV_DIR}/_archived/{conv_id}')):\n"
        "    if p.exists(): shutil.rmtree(p)\n"
    )


def _reset_folders() -> None:
    """Remove the folder registry so a run's folders don't leak between tests."""
    container_exec(
        "import pathlib\n"
        f"p = pathlib.Path('{CONV_DIR}/_folders.json')\n"
        "if p.exists(): p.unlink()\n"
    )


def test_create_folder_shows_a_folder_section(page: Page):
    """Creating a folder via the new-folder button adds a folder section."""
    nonce = time.time_ns()
    folder_name = f"Proj {nonce}"
    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.items.first).to_be_visible(timeout=5000)

        recent.create_folder(folder_name)
        expect(recent.folder_section(folder_name)).to_be_visible(timeout=5000)
    finally:
        _reset_folders()


def test_file_conversation_into_folder_persists(page: Page):
    """Filing a conversation into a folder groups it there and survives reload."""
    nonce = time.time_ns()
    conv_id = f"e2e_folder_{nonce}"
    folder_name = f"Proj {nonce}"
    _seed_conversation(conv_id, [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
    ], title=f"FolderChat {nonce}")

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.item_by_id(conv_id).root).to_be_visible(timeout=5000)

        recent.create_folder(folder_name)
        expect(recent.folder_section(folder_name)).to_be_visible(timeout=5000)

        # File the conversation into the folder; its row gains a folder tag and
        # moves under the folder's section.
        recent.item_by_id(conv_id).move_to_folder(folder_name)
        expect(recent.item_by_id(conv_id).root).not_to_have_attribute(
            "data-folder-id", "", timeout=5000,
        )
        section = recent.folder_section(folder_name)
        expect(section.locator(f'[data-conversation-id="{conv_id}"]')).to_be_visible()

        # Reload: the folder and its membership were persisted server-side.
        page.reload()
        section = recent.folder_section(folder_name)
        expect(section.locator(f'[data-conversation-id="{conv_id}"]')).to_be_visible(timeout=5000)
    finally:
        _purge_conversation(conv_id)
        _reset_folders()


def test_folder_menu_renames_and_deletes(page: Page):
    """A folder can be renamed and deleted from its 3-dot options menu."""
    nonce = time.time_ns()
    name = f"Proj {nonce}"
    renamed = f"Renamed {nonce}"
    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.items.first).to_be_visible(timeout=5000)

        recent.create_folder(name)
        expect(recent.folder_section(name)).to_be_visible(timeout=5000)

        recent.rename_folder(name, renamed)
        expect(recent.folder_section(renamed)).to_be_visible(timeout=5000)
        expect(recent.folder_section(name)).to_have_count(0)

        recent.delete_folder(renamed)
        expect(recent.folder_section(renamed)).to_have_count(0, timeout=5000)
    finally:
        _reset_folders()


def test_moving_pinned_conversation_into_folder_unpins_it(page: Page):
    """Filing a pinned conversation into a folder clears its pinned flag."""
    nonce = time.time_ns()
    conv_id = f"e2e_pinmove_{nonce}"
    folder_name = f"Proj {nonce}"
    _seed_conversation(conv_id, [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
    ], title=f"PinMove {nonce}", pinned=True)

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.item_by_id(conv_id).root).to_have_attribute(
            "data-pinned", "true", timeout=5000,
        )

        recent.create_folder(folder_name)
        recent.item_by_id(conv_id).move_to_folder(folder_name)

        # Filed into the folder and no longer pinned.
        expect(recent.item_by_id(conv_id).root).to_have_attribute(
            "data-pinned", "false", timeout=5000,
        )
        expect(recent.item_by_id(conv_id).root).not_to_have_attribute("data-folder-id", "")
        section = recent.folder_section(folder_name)
        expect(section.locator(f'[data-conversation-id="{conv_id}"]')).to_be_visible()
    finally:
        _purge_conversation(conv_id)
        _reset_folders()


def test_search_shows_flat_list_with_age(page: Page):
    """Searching drops the section headers and stamps each row with an age."""
    nonce = time.time_ns()
    conv_id = f"e2e_search_{nonce}"
    token = f"zqx{nonce}"  # unique so the query matches only this conversation
    _seed_conversation(conv_id, [
        {"role": "user", "content": f"find {token} please"},
    ], title=f"{token} chat")

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.item_by_id(conv_id).root).to_be_visible(timeout=5000)

        recent.search.fill(token)
        # The matching row shows with an inline age, and no section headers remain.
        row = recent.item_by_id(conv_id)
        expect(row.root).to_be_visible(timeout=5000)
        expect(row.root.get_by_test_id("recent-item-age")).to_be_visible()
        expect(page.get_by_test_id("recent-section")).to_have_count(0)
    finally:
        _purge_conversation(conv_id)


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


def test_row_menu_exposes_archive(page: Page):
    """The 3-dot menu offers an Archive action alongside pin/rename/delete."""
    nonce = time.time_ns()
    conv_id = f"e2e_arch_menu_{nonce}"
    _seed_conversation(conv_id, [
        {"role": "user", "content": "x"}, {"role": "assistant", "content": "y"},
    ], title=f"ArchMenu {nonce}")

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.items.first).to_be_visible(timeout=5000)

        recent.item_by_id(conv_id).open_menu()
        expect(page.get_by_test_id("recent-menu-archive")).to_be_visible()

        page.keyboard.press("Escape")
        expect(page.get_by_test_id("recent-menu")).not_to_be_visible()
    finally:
        _purge_conversation(conv_id)


def test_archive_then_restore_round_trip(page: Page):
    """Archiving moves a chat to the Archived shelf; restoring brings it back.

    Both transitions are asserted to survive a reload, proving the archive
    and restore persist server-side rather than only mutating the in-memory
    list.
    """
    nonce = time.time_ns()
    conv_id = f"e2e_archive_{nonce}"
    title = f"ArchiveMe {nonce}"
    _seed_conversation(conv_id, [
        {"role": "user", "content": "first"}, {"role": "assistant", "content": "y"},
    ], title=title)

    try:
        ChatView(page).goto()
        recent = RecentConversations(page)
        expect(recent.item_by_id(conv_id).root).to_be_visible(timeout=5000)

        # Archive: the row leaves the active recents list.
        recent.item_by_id(conv_id).archive()
        expect(recent.item_by_id(conv_id).root).not_to_be_visible()

        # It stays out of the recents after a reload (persisted server-side)...
        page.reload()
        expect(recent.items.first).to_be_visible(timeout=5000)
        expect(recent.item_by_id(conv_id).root).not_to_be_visible()

        # ...and surfaces in the Archived shelf, which loads on expand.
        recent.expand_archived()
        expect(recent.archived_item_by_id(conv_id).root).to_be_visible(timeout=5000)

        # Restore: it returns to the recents and leaves the shelf.
        recent.archived_item_by_id(conv_id).restore()
        expect(recent.archived_item_by_id(conv_id).root).not_to_be_visible()
        expect(recent.item_by_id(conv_id).root).to_be_visible()

        # Restore persisted too: still in the recents after a reload.
        page.reload()
        expect(recent.item_by_id(conv_id).root).to_be_visible(timeout=5000)
    finally:
        _purge_conversation(conv_id)


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
