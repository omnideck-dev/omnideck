"""E2E tests for reopening a conversation with earlier file output.

Seeds a conversation directly on disk (history + events + metadata) plus
the file the events reference in /home/computron. Historical output returns to
the transcript, but legacy conversation preview metadata no longer controls the
desktop and therefore opens no tabs.
"""

import json
from datetime import UTC, datetime, timedelta
import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import ChatView, PreviewTabGroup, RecentConversations

CONV_DIR = "/var/lib/computron/conversations"
VC_HOME = "/home/computron"


def _seed_conversation_with_files(
    conv_id: str,
    files: list[dict],
    *,
    title: str | None = None,
    preview_state: dict | None = None,
) -> None:
    """Seed a conversation + the files its events reference.

    Each ``files`` item: {"filename", "content_type", "content"} (utf-8 text).
    The events.jsonl carries one user + one assistant turn plus a
    file_output per file, bracketed by root agent_started / completed.
    """
    # Use wall-clock timestamps so this seeded conversation sorts above
    # any live-created ones earlier in the session — started_at now
    # reads the first event's timestamp.
    base = datetime.now(UTC)
    def _t(offset: int) -> str:
        return (base + timedelta(seconds=offset)).isoformat()
    events_jsonl_lines = [
        json.dumps({
            "id": f"evt_{conv_id}_started",
            "type": "agent_started",
            "timestamp": _t(0),
            "conversation_id": conv_id,
            "agent_id": "root.computron.1",
            "agent_name": "COMPUTRON",
            "parent_agent_id": None,
        }),
        json.dumps({
            "id": f"evt_{conv_id}_user",
            "type": "user_message",
            "timestamp": _t(1),
            "conversation_id": conv_id,
            "agent_id": "root.computron.1",
            "content": "make me some files",
            "attachments": [],
        }),
        json.dumps({
            "id": f"evt_{conv_id}_iter",
            "type": "iteration",
            "timestamp": _t(2),
            "conversation_id": conv_id,
            "agent_id": "root.computron.1",
            "iteration_index": 0,
            "content": "done",
            "thinking": None,
            "tool_calls": [],
        }),
    ]
    for i, f in enumerate(files, start=3):
        events_jsonl_lines.append(json.dumps({
            "id": f"evt_{conv_id}_file_{i}",
            "type": "file_output",
            "timestamp": _t(i),
            "conversation_id": conv_id,
            "agent_id": "root.computron.1",
            "agent_name": "COMPUTRON",
            "filename": f["filename"],
            "content_type": f["content_type"],
            "path": f"{VC_HOME}/{f['filename']}",
        }))
    events_jsonl_lines.append(json.dumps({
        "id": f"evt_{conv_id}_completed",
        "type": "agent_completed",
        "timestamp": _t(60),
        "conversation_id": conv_id,
        "agent_id": "root.computron.1",
        "agent_name": "COMPUTRON",
        "status": "success",
    }))
    events_jsonl = "\n".join(events_jsonl_lines) + "\n"

    # Default title = conv_id so the recent-list search can find this
    # seed by its unique nonce.
    metadata: dict = {"title": title if title is not None else conv_id}
    if preview_state is not None:
        metadata["preview_state"] = preview_state

    metadata_json = json.dumps(metadata)
    file_payloads = json.dumps(files)

    script = (
        "import json, pathlib\n"
        f"d = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "d.mkdir(parents=True, exist_ok=True)\n"
        f"(d / 'events.jsonl').write_text({events_jsonl!r})\n"
        f"(d / 'metadata.json').write_text({metadata_json!r})\n"
        f"home = pathlib.Path('{VC_HOME}')\n"
        f"for f in json.loads({file_payloads!r}):\n"
        "    (home / f['filename']).write_text(f['content'])\n"
        f"print('{conv_id}')\n"
    )
    container_exec(script)


def _delete_conversation(conv_id: str) -> None:
    container_exec(
        "import shutil, pathlib\n"
        f"p = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "if p.exists(): shutil.rmtree(p)\n"
    )


def _delete_file(filename: str) -> None:
    container_exec(
        "import pathlib\n"
        f"p = pathlib.Path('{VC_HOME}/{filename}')\n"
        "if p.exists(): p.unlink()\n"
    )


@pytest.mark.e2e
def test_resume_renders_file_block_inline_in_chat(page: Page):
    """A file_output from a previous turn shows up as an inline FileOutput block."""
    nonce = time.time_ns()
    conv_id = f"e2e_restore_inline_{nonce}"
    filename = f"report_{nonce}.html"
    _seed_conversation_with_files(conv_id, [
        {"filename": filename, "content_type": "text/html",
         "content": "<html><body>seeded</body></html>"},
    ])

    try:
        ChatView(page).goto()
        # Search-and-open by the nonce-stamped title so the test is
        # robust to recency ordering and exercises search on the way in.
        RecentConversations(page).open_by_title(conv_id)

        # The inline FileOutput block is identified by its Preview button.
        # Scope to the assistant message so we don't false-match a tab.
        assistant = page.get_by_test_id("message-assistant").last
        expect(assistant).to_be_visible(timeout=5_000)
        file_preview_btn = assistant.get_by_test_id("file-preview-btn").first
        expect(file_preview_btn).to_be_visible()
        expect(assistant).to_contain_text(filename)
    finally:
        _delete_conversation(conv_id)
        _delete_file(filename)


@pytest.mark.e2e
def test_resume_ignores_legacy_preview_placement(page: Page):
    """Conversation metadata restores data, never old Browser/Terminal/file tabs."""
    nonce = time.time_ns()
    conv_id = f"e2e_restore_no_tabs_{nonce}"
    file_a = f"a_{nonce}.html"
    file_b = f"b_{nonce}.html"
    _seed_conversation_with_files(
        conv_id,
        [
            {"filename": file_a, "content_type": "text/html",
             "content": "<html><body>a</body></html>"},
            {"filename": file_b, "content_type": "text/html",
             "content": "<html><body>b</body></html>"},
        ],
        preview_state={
            "open_files": [f"{VC_HOME}/{file_a}", f"{VC_HOME}/{file_b}"],
            "active_tab": f"file:{VC_HOME}/{file_b}",
            "browser_visible": True,
            "terminal_visible": True,
            "desktop_visible": False,
            "generation_visible": False,
        },
    )

    try:
        ChatView(page).goto()
        RecentConversations(page).open_by_title(conv_id)

        panel = PreviewTabGroup(page)
        expect(panel.file_tab(file_a)).to_have_count(0)
        expect(panel.file_tab(file_b)).to_have_count(0)
        expect(panel.browser_tab).to_have_count(0)
        expect(panel.terminal_tab).to_have_count(0)

        # The user can still open the historical artifact explicitly.
        page.get_by_test_id("message-assistant").last.get_by_test_id(
            "file-preview-btn"
        ).first.click()
        expect(panel.file_tabs).to_have_count(1)
    finally:
        _delete_conversation(conv_id)
        _delete_file(file_a)
        _delete_file(file_b)
