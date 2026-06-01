"""E2E: resuming a conversation that had a user-uploaded attachment.

Verifies the chat view (apply_compactions=False) does NOT render the
LLM-facing ``[Attached files written to virtual computer]`` block —
that augmentation is only for the model. The user bubble should show
just what the user typed.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import ChatView, RecentConversations

CONV_DIR = "/var/lib/computron/conversations"
VC_UPLOADS = "/home/computron/uploads"
AGENT_ID = "root.computron.1"


def _seed_conv_with_user_attachment(
    conv_id: str,
    *,
    user_text: str,
    filename: str,
    content_type: str = "text/plain",
    file_contents: str = "secret payload",
    title: str | None = None,
) -> None:
    """events.jsonl with one user_message that carries an attachment
    (the augmentation block is *not* persisted on the event — it's a
    derived LLM-only render)."""
    base = datetime.now(UTC)
    def _t(o: int) -> str:
        return (base + timedelta(seconds=o)).isoformat()
    upload_path = f"{VC_UPLOADS}/{filename}"
    events = [
        {"id": f"evt_{conv_id}_started", "type": "agent_started",
         "timestamp": _t(0), "conversation_id": conv_id,
         "agent_id": AGENT_ID, "agent_name": "COMPUTRON",
         "parent_agent_id": None},
        {"id": f"evt_{conv_id}_user", "type": "user_message",
         "timestamp": _t(1), "conversation_id": conv_id,
         "agent_id": AGENT_ID, "agent_name": "COMPUTRON", "depth": 0,
         "content": user_text,
         "attachments": [{
             "filename": filename, "content_type": content_type,
             "path": upload_path,
         }]},
        {"id": f"evt_{conv_id}_iter", "type": "iteration",
         "timestamp": _t(2), "conversation_id": conv_id,
         "agent_id": AGENT_ID, "agent_name": "COMPUTRON",
         "iteration_index": 0,
         "content": "got it.", "thinking": None, "tool_calls": []},
        {"id": f"evt_{conv_id}_completed", "type": "agent_completed",
         "timestamp": _t(3), "conversation_id": conv_id,
         "agent_id": AGENT_ID, "agent_name": "COMPUTRON",
         "status": "success"},
    ]
    events_jsonl = "\n".join(json.dumps(e) for e in events) + "\n"
    meta = json.dumps({"title": title if title is not None else conv_id})
    container_exec(
        "import pathlib\n"
        f"d = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "d.mkdir(parents=True, exist_ok=True)\n"
        f"(d / 'events.jsonl').write_text({events_jsonl!r})\n"
        f"(d / 'metadata.json').write_text({meta!r})\n"
        f"uploads = pathlib.Path('{VC_UPLOADS}')\n"
        "uploads.mkdir(parents=True, exist_ok=True)\n"
        f"(uploads / {filename!r}).write_text({file_contents!r})\n"
    )


def _cleanup(conv_id: str, filename: str) -> None:
    container_exec(
        "import shutil, pathlib\n"
        f"p = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "if p.exists(): shutil.rmtree(p)\n"
        f"u = pathlib.Path('{VC_UPLOADS}/{filename}')\n"
        "if u.exists(): u.unlink()\n"
    )


@pytest.mark.e2e
def test_resume_user_bubble_shows_raw_text_not_attachment_block(page: Page):
    """The chat view shows what the user typed; the augmented LLM block
    (``[Attached files written to virtual computer]…``) stays out of
    the user bubble even though it's present on the LLM-facing view."""
    nonce = time.time_ns()
    conv_id = f"e2e_attach_resume_{nonce}"
    filename = f"upload_{nonce}.txt"
    user_text = f"what is the secret in this file? marker={nonce}"
    _seed_conv_with_user_attachment(
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
