"""E2E: a warm-resumed conversation should restore its inline file blocks.

Produces a file through the real pipeline (the fake provider drives write_file +
send_file), then reopens the still-warm conversation from the recent list. The
inline file block in the transcript is rebuilt from file_output events; the
in-memory log retains those events, so the warm resume restores the block the
same way a cold disk resume does. (The preview *tab*, by contrast, restores from
the saved preview_state path and is covered in the artifacts suite.)

Regression guard for the warm-resume bug where the in-memory log dropped
file_output and previews vanished when a conversation was served from cache.
"""

import time

from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import say, send_file, write_file
from tests.e2e.pages import ChatView, RecentConversations

VC_HOME = "/home/computron"


def test_warm_resume_restores_inline_file_block(page: Page):
    """Reopening a still-cached conversation should show its sent file inline."""
    nonce = time.time_ns()
    name = f"warmblk_{nonce}.md"
    path = f"{VC_HOME}/{name}"
    ChatView(page).goto().new_conversation().send(
        write_file(path, "# warm block") + send_file(path) + say("done"),
    ).wait_streaming()
    try:
        # Capture this conversation's id so we can reopen it by identity, not by
        # list position (a pinned conversation could sit above it).
        conv_id = page.request.get("/api/conversations/sessions").json()[0]["conversation_id"]

        # Leave the conversation (it stays warm in the backend cache), then reopen
        # it by id — a real warm resume.
        ChatView(page).new_conversation()
        RecentConversations(page).open_by_id(conv_id)

        # The transcript should carry the inline file block (the chat Preview button).
        assistant = page.get_by_test_id("message-assistant").last
        expect(assistant).to_be_visible(timeout=8_000)
        expect(assistant.get_by_test_id("file-preview-btn").first).to_be_visible(timeout=8_000)
    finally:
        container_exec(
            "import pathlib\n"
            f"p = pathlib.Path('{path}')\n"
            "if p.exists(): p.unlink()\n"
        )
