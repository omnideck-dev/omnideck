"""E2E resume of file output produced by actual write_file/send_file tools."""

import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import say, send_file, write_file
from tests.e2e._runtime import api, delete_conversation, resume, run_turn, update_conversation
from tests.e2e.pages import ChatView, PreviewTabGroup, RecentConversations

VC_HOME = "/home/computron"


def _create_conversation_with_files(conv_id, files, *, title=None, preview_state=None):
    prompt = "".join(write_file(f"{VC_HOME}/{f['filename']}", f["content"])
                     + send_file(f"{VC_HOME}/{f['filename']}") for f in files) + say("done")
    run_turn(conv_id, prompt)
    update_conversation(conv_id, title=title or conv_id)
    outputs = [e for e in resume(conv_id)["events"] if e["type"] == "file_output"]
    assert {e["filename"] for e in outputs} == {f["filename"] for f in files}
    if preview_state is not None:
        # Exercise the legacy metadata endpoint; all transcript events still
        # come from execution. Resume must ignore this obsolete placement data.
        response = api().request("PUT", f"/api/conversations/sessions/{conv_id}/preview-state", data=preview_state)
        assert response.status in (200, 204), response.text


def _delete_file(filename):
    container_exec(f"from pathlib import Path\nPath({VC_HOME!r}, {filename!r}).unlink(missing_ok=True)")


@pytest.mark.e2e
def test_resume_renders_file_block_inline_in_chat(page: Page):
    """A file_output from a previous turn shows up as an inline FileOutput block."""
    nonce = time.time_ns()
    conv_id = f"e2e_restore_inline_{nonce}"
    filename = f"report_{nonce}.html"
    _create_conversation_with_files(conv_id, [
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
        delete_conversation(conv_id)
        _delete_file(filename)


@pytest.mark.e2e
def test_resume_ignores_legacy_preview_placement(page: Page):
    """Conversation metadata restores data, never old Browser/Terminal/file tabs."""
    nonce = time.time_ns()
    conv_id = f"e2e_restore_no_tabs_{nonce}"
    file_a = f"a_{nonce}.html"
    file_b = f"b_{nonce}.html"
    _create_conversation_with_files(
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
        delete_conversation(conv_id)
        _delete_file(file_a)
        _delete_file(file_b)
