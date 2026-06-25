"""E2E tests for chat-input file uploads.

Both tests mock the chat endpoint so they verify the upload *pipeline*
deterministically (encoding, request shape, UI rendering) without
depending on a real model.
"""

import base64
import json
from pathlib import Path
import time

from playwright.sync_api import Page, Route, expect

from tests.e2e.pages import ChatView

_FIXTURE_RED_SQUARE = Path(__file__).resolve().parent.parent / "fixtures" / "red_square.png"


def _minimal_chat_response(*, attachments: list[dict] | None = None) -> str:
    """JSONL response with just enough to let the UI finish streaming.

    Mirrors the real backend: a ``user_message`` event is published
    before any model work, carrying the image attachment metadata. The
    FE clears its optimistic pending bubble when this lands.
    """
    user_payload: dict = {
        "type": "user_message", "content": "describe this image",
        "attachments": attachments or [], "is_nudge": False,
    }
    events = [
        {"payload": {"type": "agent_started", "agent_id": "root",
                     "agent_name": "computron", "parent_agent_id": None},
         "agent_id": "root", "agent_name": "computron",
         "timestamp": "2026-05-09T00:00:00+00:00", "depth": 0},
        {"payload": user_payload,
         "agent_id": "root", "agent_name": "computron",
         "timestamp": "2026-05-09T00:00:00+00:00", "depth": 0},
        {"payload": {"type": "content", "content": "ok"},
         "agent_id": "root", "agent_name": "computron",
         "timestamp": "2026-05-09T00:00:00+00:00", "depth": 0},
        {"payload": {"type": "iteration", "iteration_index": 0,
                     "content": "ok", "thinking": None,
                     "tool_calls": []},
         "agent_id": "root", "agent_name": "computron",
         "timestamp": "2026-05-09T00:00:00+00:00", "depth": 0},
        {"payload": {"type": "agent_completed", "agent_id": "root",
                     "agent_name": "computron", "status": "success"},
         "agent_id": "root", "agent_name": "computron",
         "timestamp": "2026-05-09T00:00:00+00:00", "depth": 0},
        {"payload": {"type": "turn_end"},
         "agent_id": "root", "agent_name": "computron",
         "timestamp": "2026-05-09T00:00:00+00:00", "depth": 0},
    ]
    return "".join(json.dumps(e) + "\n" for e in events)


def test_text_file_upload_round_trip(page: Page, tmp_path):
    """Uploading a text file encodes it into the request and shows an
    attachment chip in the user bubble."""
    content = f"secret-{time.time_ns()}"
    text_file = tmp_path / "notes.txt"
    text_file.write_text(content)
    expected_b64 = base64.b64encode(text_file.read_bytes()).decode()

    captured: dict = {}

    def handler(route: Route) -> None:
        captured["body"] = route.request.post_data
        # Mirror production: the backend echoes the uploaded file's
        # metadata in the user_message event, which is what the rebuilt
        # user bubble renders its attachment chip from.
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=_minimal_chat_response(attachments=[{
                "filename": "notes.txt",
                "content_type": "text/plain",
                "path": "/home/computron/uploads/notes.txt",
            }]),
        )

    page.route("**/api/chat", handler)

    chat = ChatView(page).goto().new_conversation()
    chat.attach_file(str(text_file)).send("summarize this file")
    chat.wait_streaming(timeout=10_000)

    body = json.loads(captured["body"])
    assert body.get("data"), f"expected data[] in request body, got: {body!r}"
    attachment = body["data"][0]
    assert attachment["content_type"] == "text/plain", attachment
    assert attachment["filename"] == "notes.txt", attachment
    assert attachment["base64"] == expected_b64, (
        "uploaded base64 doesn't match the original file bytes"
    )

    user_msg = page.get_by_test_id("message-user").last
    chip = user_msg.get_by_test_id("attachment-file")
    expect(chip).to_be_visible(timeout=5_000)


def test_image_upload_round_trip(page: Page):
    """An attached image is base64-encoded into the /api/chat request and
    rendered in the user bubble as a data URL.

    Does not exercise the vision model — that's a model-quality check,
    not an upload-pipeline check.
    """
    assert _FIXTURE_RED_SQUARE.exists(), f"missing fixture {_FIXTURE_RED_SQUARE}"
    expected_b64 = base64.b64encode(_FIXTURE_RED_SQUARE.read_bytes()).decode()

    captured: dict = {}

    def handler(route: Route) -> None:
        captured["body"] = route.request.post_data
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/json"},
            body=_minimal_chat_response(attachments=[{
                "filename": _FIXTURE_RED_SQUARE.name,
                "content_type": "image/png",
                "path": f"/home/computron/uploads/{_FIXTURE_RED_SQUARE.name}",
            }]),
        )

    page.route("**/api/chat", handler)

    chat = ChatView(page).goto().new_conversation()
    chat.attach_file(str(_FIXTURE_RED_SQUARE)).send("describe this image")
    chat.wait_streaming(timeout=10_000)

    # 1. Outgoing request carried the image bytes.
    body = json.loads(captured["body"])
    assert body.get("data"), f"expected data[] in request body, got: {body!r}"
    attachment = body["data"][0]
    assert attachment["content_type"] == "image/png", attachment
    assert attachment["filename"] == _FIXTURE_RED_SQUARE.name, attachment
    assert attachment["base64"] == expected_b64, (
        "uploaded base64 doesn't match the original file bytes"
    )

    # 2. User bubble renders the uploaded image. The path the backend
    # returned points at the container_file_handler route, so the FE
    # uses it directly as the <img src> rather than re-embedding bytes.
    user_msg = page.get_by_test_id("message-user").last
    img = user_msg.locator(f"img[src*='{_FIXTURE_RED_SQUARE.name}']")
    expect(img).to_be_visible(timeout=5_000)
