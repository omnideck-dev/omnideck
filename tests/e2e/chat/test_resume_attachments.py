"""E2E resume uses a real upload and the runtime's persisted user message."""

import base64
import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e._runtime import delete_conversation, resume, run_turn, update_conversation
from tests.e2e.pages import ChatView, RecentConversations


def _create_with_attachment(conv_id, *, user_text, filename, file_contents):
    run_turn(conv_id, user_text, attachments=[{
        "base64": base64.b64encode(file_contents.encode()).decode(),
        "filename": filename, "content_type": "text/plain",
    }])
    update_conversation(conv_id, title=conv_id)
    uploaded = next(e for e in resume(conv_id)["events"] if e["type"] == "user_message")["attachments"]
    assert len(uploaded) == 1 and uploaded[0]["filename"] == filename


def _cleanup(conv_id, filename):
    delete_conversation(conv_id)
    container_exec(f"from pathlib import Path\nPath('/home/computron/uploads/' + {filename!r}).unlink(missing_ok=True)")


@pytest.mark.e2e
def test_resume_user_bubble_shows_raw_text_not_attachment_block(page: Page):
    """The chat view shows what the user typed; the augmented LLM block
    (``[Attached files written to virtual computer]…``) stays out of
    the user bubble even though it's present on the LLM-facing view."""
    nonce = time.time_ns()
    conv_id = f"e2e_attach_resume_{nonce}"
    filename = f"upload_{nonce}.txt"
    user_text = f"what is the secret in this file? marker={nonce}"
    _create_with_attachment(
        conv_id, user_text=user_text, filename=filename,
        file_contents=f"the secret marker is {nonce}",
    )
    try:
        ChatView(page).goto()
        RecentConversations(page).open_by_title(conv_id)
        user_msg = page.get_by_test_id("message-user").first
        expect(user_msg).to_be_visible(timeout=5_000)
        # Raw user text is rendered.
        expect(user_msg).to_contain_text(user_text)
        # The LLM-facing augmentation block is NOT in the chat view.
        expect(user_msg).not_to_contain_text("Attached files written to virtual computer")
        expect(user_msg).not_to_contain_text("/home/computron/uploads/")
    finally:
        _cleanup(conv_id, filename)
