"""E2E tests for file preview rendering per type.

Asks the agent to create text, markdown, and HTML files, then verifies
each renders correctly with the appropriate controls (source/preview
toggle, fullscreen, download).
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import send_file, write_file
from tests.e2e.pages import ChatView


_TXT = "/home/computron/hello.txt"
_MD = "/home/computron/hello.md"
_HTML = "/home/computron/hello.html"


@pytest.fixture(scope="module")
def file_types_page(browser, browser_context_args):
    """Create text, markdown, and HTML files and open them all as tabs."""
    context = browser.new_context(**browser_context_args)
    page = context.new_page()
    chat = ChatView(page).goto().new_conversation()

    chat.send(
        write_file(_TXT, "hello from text file") + send_file(_TXT)
        + write_file(_MD, "# Hello\n\n- one\n- two") + send_file(_MD)
        + write_file(_HTML, "<html><body><h1>hello</h1></body></html>") + send_file(_HTML)
    ).wait_streaming()

    assert chat.file_preview_btns.count() >= 1, "No file outputs were sent by the agent"
    chat.open_all_file_previews()

    yield page

    page.close()
    context.close()


# ── Text file ───────────────────────────────────────────────────────


def test_text_file_has_source_only(file_types_page: Page):
    """Plain text file should show source-only view (no toggle)."""
    chat = ChatView(file_types_page)
    filename = chat.preview.open_file_tab_by_extension(".txt")
    assert filename, "No .txt file tab found"

    expect(chat.preview.file.source_only).to_be_visible()
    expect(chat.preview.file.toggle).not_to_be_visible()


def test_text_file_renders_content(file_types_page: Page):
    """Text file should render readable content in the source editor."""
    editor = ChatView(file_types_page).preview.file.editor
    expect(editor).to_be_visible()
    expect(editor).to_contain_text("hello")


# ── Markdown file ───────────────────────────────────────────────────


def test_markdown_file_has_toggle(file_types_page: Page):
    """Markdown file should have a source/preview toggle."""
    chat = ChatView(file_types_page)
    filename = chat.preview.open_file_tab_by_extension(".md")
    assert filename, "No .md file tab found"

    expect(chat.preview.file.toggle).to_be_visible()


def test_markdown_source_shows_raw(file_types_page: Page):
    """Source mode shows raw markdown in the editor."""
    chat = ChatView(file_types_page)
    chat.preview.file.view_source()

    editor = chat.preview.file.editor
    expect(editor).to_be_visible()
    text = editor.text_content() or ""
    assert "#" in text or "-" in text or "*" in text, (
        f"Expected raw markdown syntax, got: {text[:200]}"
    )


def test_markdown_preview_shows_rendered(file_types_page: Page):
    """Preview mode shows rendered markdown."""
    chat = ChatView(file_types_page)
    chat.preview.file.view_preview()

    markdown_div = chat.preview.content.locator("[class*='markdownContent']")
    expect(markdown_div).to_be_visible()


# ── HTML file ───────────────────────────────────────────────────────


def test_html_file_has_toggle(file_types_page: Page):
    """HTML file should have a source/preview toggle."""
    chat = ChatView(file_types_page)
    filename = chat.preview.open_file_tab_by_extension(".html")
    assert filename, "No .html file tab found"

    expect(chat.preview.file.toggle).to_be_visible()


def test_html_preview_shows_iframe(file_types_page: Page):
    """HTML preview mode renders an iframe."""
    chat = ChatView(file_types_page)
    chat.preview.file.view_preview()

    iframe = chat.preview.content.locator("iframe")
    expect(iframe).to_be_visible()


def test_html_source_shows_raw(file_types_page: Page):
    """HTML source mode shows raw HTML in the editor."""
    chat = ChatView(file_types_page)
    chat.preview.file.view_source()

    editor = chat.preview.file.editor
    expect(editor).to_be_visible()
    text = editor.text_content() or ""
    assert "<" in text, f"Expected raw HTML tags, got: {text[:200]}"


# ── Fullscreen ──────────────────────────────────────────────────────


def test_fullscreen_opens_and_closes(file_types_page: Page):
    """Clicking fullscreen opens the overlay, Escape closes it."""
    chat = ChatView(file_types_page)
    fullscreen = chat.preview.file.open_fullscreen()

    expect(fullscreen.root).to_be_visible()

    fullscreen.close_with_escape()
    expect(fullscreen.root).not_to_be_visible()


# ── Download ────────────────────────────────────────────────────────


def test_download_button_works(file_types_page: Page):
    """Clicking download should trigger a file download."""
    chat = ChatView(file_types_page)
    with file_types_page.expect_download() as download_info:
        chat.preview.file.download_button().click()

    download = download_info.value
    assert download.suggested_filename, "Download should have a filename"
