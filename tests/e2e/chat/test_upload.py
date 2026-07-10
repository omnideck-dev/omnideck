"""E2E tests for chat-input file uploads.

Both tests run the real upload path: the file is base64-encoded into the
/api/chat request, decoded and written to the virtual computer, echoed back in
the user_message event, and served from its stored path. The request is
intercepted only to capture its body, never to answer it — the in-process fake
provider supplies the reply, so no model is involved.
"""

import base64
import json
from pathlib import Path
import time

from playwright.sync_api import Page, Route, expect

from tests.e2e._protocol import say
from tests.e2e.pages import ChatView

_FIXTURE_RED_SQUARE = Path(__file__).resolve().parent.parent / "fixtures" / "red_square.png"


def _capture_chat_request(page: Page) -> dict:
    """Record the outgoing /api/chat body and let the request through.

    The returned dict gains a ``body`` key once the request has gone out.
    """
    captured: dict = {}

    def handler(route: Route) -> None:
        captured["body"] = route.request.post_data
        route.continue_()

    page.route("**/api/chat", handler)
    return captured


def _sole_attachment(captured: dict) -> dict:
    """The one attachment the captured request carried."""
    body = json.loads(captured["body"])
    assert body.get("data"), f"expected data[] in request body, got: {body!r}"
    return body["data"][0]


def test_text_file_upload_round_trip(page: Page, tmp_path):
    """Uploading a text file encodes it into the request and shows an
    attachment chip in the user bubble."""
    # A unique name per run: the backend renames an upload whose name collides
    # with a file already in the uploads directory.
    text_file = tmp_path / f"notes-{time.time_ns()}.txt"
    text_file.write_text("secret contents")
    raw = text_file.read_bytes()

    captured = _capture_chat_request(page)

    chat = ChatView(page).goto().new_conversation()
    chat.attach_file(str(text_file)).send(say("ok"))
    chat.wait_streaming(timeout=10_000)

    attachment = _sole_attachment(captured)
    assert attachment["content_type"] == "text/plain", attachment
    assert attachment["filename"] == text_file.name, attachment
    assert attachment["base64"] == base64.b64encode(raw).decode(), (
        "uploaded base64 doesn't match the original file bytes"
    )

    user_msg = page.get_by_test_id("message-user").last
    chip = user_msg.get_by_test_id("attachment-file")
    expect(chip).to_be_visible(timeout=5_000)


def test_image_upload_round_trip(page: Page, tmp_path):
    """An attached image is base64-encoded into the /api/chat request, stored on
    the virtual computer, and rendered in the user bubble as an <img> served
    from its stored path.

    Does not exercise the vision model — that's a model-quality check, not an
    upload-pipeline check.
    """
    assert _FIXTURE_RED_SQUARE.exists(), f"missing fixture {_FIXTURE_RED_SQUARE}"
    raw = _FIXTURE_RED_SQUARE.read_bytes()
    image = tmp_path / f"red-square-{time.time_ns()}.png"
    image.write_bytes(raw)

    captured = _capture_chat_request(page)

    chat = ChatView(page).goto().new_conversation()
    chat.attach_file(str(image)).send(say("ok"))
    chat.wait_streaming(timeout=10_000)

    # 1. Outgoing request carried the image bytes.
    attachment = _sole_attachment(captured)
    assert attachment["content_type"] == "image/png", attachment
    assert attachment["filename"] == image.name, attachment
    assert attachment["base64"] == base64.b64encode(raw).decode(), (
        "uploaded base64 doesn't match the original file bytes"
    )

    # 2. User bubble renders the stored image. The chip keeps its <img> only
    # while the src loads and swaps in a file-type icon otherwise, so a visible
    # <img> means the backend wrote the upload and serves it back.
    user_msg = page.get_by_test_id("message-user").last
    img = user_msg.get_by_test_id("attachment-image")
    expect(img).to_be_visible(timeout=5_000)

    # 3. The served bytes are the ones we uploaded.
    served = page.request.get(img.get_attribute("src"))
    assert served.ok, f"serving the stored upload failed with {served.status}"
    assert served.body() == raw, "served bytes differ from the uploaded file"
