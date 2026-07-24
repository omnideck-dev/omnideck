"""E2E tests for restoring workspace-surface state when a conversation is reopened.

Seeds a conversation directly on disk (history + events + metadata) plus
the file the events reference in /home/computron, then loads it from the
recent-conversations list and asserts on what restores.

Covers four scenarios:
    1. File block appears inline in the chat (via _mergeFileOutputs).
    2. The preview tab the user had open re-opens automatically.
    3. The previously active tab is the one selected on restore.
    4. Tabs the user closed before leaving do NOT re-open.
"""

import json
import re
from datetime import UTC, datetime, timedelta
import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import ChatView, PreviewPanel, RecentConversations

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
def test_resume_restores_open_file_tab(page: Page):
    """A file the user had previewed re-opens as a tab in the preview panel."""
    nonce = time.time_ns()
    conv_id = f"e2e_restore_tab_{nonce}"
    filename = f"open_{nonce}.html"
    _seed_conversation_with_files(
        conv_id,
        [{"filename": filename, "content_type": "text/html",
          "content": "<html><body>open me</body></html>"}],
        preview_state={
            # Open files are saved by full path (the file's identity).
            "open_files": [f"{VC_HOME}/{filename}"],
            "active_tab": f"file:{VC_HOME}/{filename}",
            "browser_visible": False,
            "terminal_visible": False,
            "desktop_visible": False,
            "generation_visible": False,
        },
    )

    try:
        ChatView(page).goto()
        # Search-and-open by the nonce-stamped title so the test is
        # robust to recency ordering and exercises search on the way in.
        RecentConversations(page).open_by_title(conv_id)

        panel = PreviewPanel(page)
        expect(panel.file_tab(filename)).to_be_visible(timeout=5_000)
    finally:
        _delete_conversation(conv_id)
        _delete_file(filename)


@pytest.mark.e2e
def test_resume_restores_active_tab_selection(page: Page):
    """When multiple files were open, the previously-active tab is selected."""
    nonce = time.time_ns()
    conv_id = f"e2e_restore_active_{nonce}"
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
            "browser_visible": False,
            "terminal_visible": False,
            "desktop_visible": False,
            "generation_visible": False,
        },
    )

    try:
        ChatView(page).goto()
        # Search-and-open by the nonce-stamped title so the test is
        # robust to recency ordering and exercises search on the way in.
        RecentConversations(page).open_by_title(conv_id)

        panel = PreviewPanel(page)
        expect(panel.file_tab(file_a)).to_be_visible(timeout=5_000)
        expect(panel.file_tab(file_b)).to_be_visible()

        # PreviewPanel adds an "active" class to the selected tab button.
        # CSS-Modules hashes the class name; match on the substring.
        expect(panel.file_tab(file_b)).to_have_class(re.compile(r"tabActive"))
        expect(panel.file_tab(file_a)).not_to_have_class(re.compile(r"tabActive"))
    finally:
        _delete_conversation(conv_id)
        _delete_file(file_a)
        _delete_file(file_b)


@pytest.mark.e2e
def test_resume_does_not_reopen_closed_tabs(page: Page):
    """A file that's in the history but NOT in open_files stays closed on restore."""
    nonce = time.time_ns()
    conv_id = f"e2e_restore_closed_{nonce}"
    open_file = f"keep_{nonce}.html"
    closed_file = f"closed_{nonce}.html"
    _seed_conversation_with_files(
        conv_id,
        [
            {"filename": open_file, "content_type": "text/html",
             "content": "<html><body>keep</body></html>"},
            {"filename": closed_file, "content_type": "text/html",
             "content": "<html><body>closed</body></html>"},
        ],
        preview_state={
            # User had keep_file open, explicitly closed closed_file.
            "open_files": [f"{VC_HOME}/{open_file}"],
            "active_tab": f"file:{VC_HOME}/{open_file}",
            "browser_visible": False,
            "terminal_visible": False,
            "desktop_visible": False,
            "generation_visible": False,
        },
    )

    try:
        ChatView(page).goto()
        # Search-and-open by the nonce-stamped title so the test is
        # robust to recency ordering and exercises search on the way in.
        RecentConversations(page).open_by_title(conv_id)

        panel = PreviewPanel(page)
        expect(panel.file_tab(open_file)).to_be_visible(timeout=5_000)
        # Closed tab does NOT come back, even though the file is in events.
        expect(panel.file_tab(closed_file)).to_have_count(0)
    finally:
        _delete_conversation(conv_id)
        _delete_file(open_file)
        _delete_file(closed_file)
