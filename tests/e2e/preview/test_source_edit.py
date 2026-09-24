"""E2E: editing a text source in the preview and saving it back to disk.

The preview's source view is an editor. Typing into it marks the file dirty,
and Save PUTs the buffer back to the same file it was opened from. This drives
the whole path — editor → save route → disk — and asserts the new bytes land
in the container.
"""

import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import send_file, write_file
from tests.e2e.pages import ChatView

VC_HOME = "/home/computron"


def _read_container_file(path: str) -> str:
    """Read a file's contents from inside the running container."""
    return container_exec(
        "import pathlib\n"
        f"print(pathlib.Path('{path}').read_text(), end='')\n"
    )


@pytest.fixture
def text_source(page: Page):
    """Produce a plain-text file through the agent pipeline; clean it up after."""
    nonce = time.time_ns()
    name = f"editme_{nonce}.txt"
    path = f"{VC_HOME}/{name}"
    ChatView(page).goto().new_conversation().send(
        write_file(path, "original contents") + send_file(path),
    ).wait_streaming()
    try:
        yield name, path
    finally:
        container_exec(
            "import pathlib\n"
            f"p = pathlib.Path('{path}')\n"
            "if p.exists(): p.unlink()\n"
        )


def test_edit_source_saves_to_disk(page: Page, text_source):
    """Editing the source and clicking Save writes the new bytes to the file."""
    name, path = text_source
    chat = ChatView(page)
    chat.open_all_file_previews()

    opened = chat.preview.open_file_tab_by_extension(".txt")
    assert opened == name, f"expected {name} tab, opened {opened}"

    file = chat.preview.file
    # Source is always edit mode for a plain-text file.
    expect(file.editor).to_be_visible()
    expect(file.editor).to_contain_text("original contents")

    # Save stays inert until the buffer diverges from disk.
    expect(file.save_button).to_be_disabled()

    new_text = "edited in the source editor"
    file.set_source(new_text)
    expect(file.save_button).to_be_enabled()

    file.save()

    # Once the round-trip completes the buffer matches disk again and Save goes
    # inert — a UI signal that the save landed before we read the file back.
    expect(file.save_button).to_be_disabled()
    assert _read_container_file(path) == new_text
