"""E2E tests for the global Artifacts Hub.

Every artifact here is produced through the real pipeline: the FakeProvider
drives the actual ``write_file`` + ``send_file`` tools, which emit a
``file_output`` event that the subscribed index writer records — exactly what
happens when a model sends a file. The hub then reads those entries back over
``/api/artifacts`` (reconciled against disk on each read). No state is seeded
directly, so these exercise the feature end to end.

Filenames carry a per-run nonce so each test finds only its own artifacts even
though the hub shows everything across all conversations.
"""

import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.artifacts._helpers import VC_HOME, delete_file, file_exists, produce, purge
from tests.e2e.pages import ArtifactsHub, ChatView, PreviewPanel


# ── read-only group: one shared pair of produced artifacts ──────────────


@pytest.fixture(scope="module")
def produced(browser, browser_context_args):
    """Produce a markdown + html artifact through send_file; clean up after."""
    nonce = time.time_ns()
    md = f"hub_{nonce}.md"
    html = f"hub_{nonce}.html"
    context = browser.new_context(**browser_context_args)
    page = context.new_page()
    produce(
        page,
        (f"{VC_HOME}/{md}", "# Hub artifact\n\nproduced via send_file"),
        (f"{VC_HOME}/{html}", "<html><body><h1>hub html</h1></body></html>"),
    )
    yield {"md": md, "html": html}
    purge(page, md, html)
    page.close()
    context.close()


def test_sent_file_appears_in_grid(page: Page, produced):
    """A file the agent sends shows up as a card in the hub."""
    hub = ArtifactsHub(page).goto()
    expect(hub.card(produced["md"])).to_be_visible(timeout=5_000)
    expect(hub.card(produced["html"])).to_be_visible()


def test_selecting_artifact_opens_file_surface(page: Page, produced):
    """Selecting a card opens a file surface with the artifact's content."""
    hub = ArtifactsHub(page).goto()
    hub.select(produced["md"])
    expect(hub.preview).to_be_visible(timeout=5_000)
    expect(hub.preview).to_contain_text(produced["md"])
    expect(hub.preview).to_contain_text("Hub artifact")


def test_table_view_lists_artifact(page: Page, produced):
    """Toggling to the table view lists the same artifact as a row."""
    hub = ArtifactsHub(page).goto().show_table()
    expect(hub.row(produced["md"])).to_be_visible(timeout=5_000)


def test_search_filters_to_matching_artifact(page: Page, produced):
    """Searching narrows the list to the matching filename."""
    hub = ArtifactsHub(page).goto()
    hub.search(produced["md"])
    expect(hub.card(produced["md"])).to_be_visible()
    expect(hub.card(produced["html"])).to_have_count(0)


# ── delete: present file, opting into disk deletion ─────────────────────


def test_delete_present_artifact_removes_entry_and_file(page: Page):
    """Deleting a present artifact with the checkbox unlinks the file too."""
    nonce = time.time_ns()
    name = f"hubdel_{nonce}.md"
    produce(page, (f"{VC_HOME}/{name}", "delete me"))
    try:
        hub = ArtifactsHub(page).goto()
        expect(hub.card(name)).to_be_visible(timeout=5_000)

        hub.request_delete(name)
        expect(hub.delete_dialog).to_be_visible()
        hub.confirm_delete(delete_file=True)

        expect(hub.card(name)).to_have_count(0)
        assert not file_exists(name), "file should be unlinked from disk"
        arts = page.request.get("/api/artifacts").json()["artifacts"]
        assert not any(a["filename"] == name for a in arts)
    finally:
        purge(page, name)
        delete_file(name)


# ── missing: file removed behind the hub's back, then pruned ────────────


def test_missing_artifact_can_be_pruned(page: Page):
    """A file deleted on disk reconciles to 'missing' and prunes away."""
    nonce = time.time_ns()
    name = f"hubmiss_{nonce}.md"
    produce(page, (f"{VC_HOME}/{name}", "transient"))
    try:
        # Remove the file out-of-band; the next read reconciles it to missing.
        delete_file(name)

        hub = ArtifactsHub(page).goto()
        card = hub.card(name)
        expect(card).to_be_visible(timeout=5_000)
        expect(card).to_contain_text("missing")

        hub.prune_missing()
        expect(hub.card(name)).to_have_count(0)
    finally:
        purge(page, name)


# ── open in conversation: navigation intent resolves the artifact ──────


def test_open_in_conversation_restores_focused_file(page: Page):
    """Opening an artifact loads its conversation and resolves its file preview.

    The open action carries the artifact ID as navigation intent. Once the source
    conversation loads, the desktop resolves that ID and opens its file in the
    shared dock without pre-writing the conversation's saved preview state.
    """
    nonce = time.time_ns()
    name = f"hubopen_{nonce}.md"
    produce(page, (f"{VC_HOME}/{name}", "# open me\n\nfrom the hub"))
    try:
        # Switch to a new conversation so the artifact's conversation is no
        # longer active — exercises conversation loading plus intent resolution.
        ChatView(page).goto().new_conversation()

        hub = ArtifactsHub(page).goto()
        hub.select(name)
        page.get_by_test_id("artifact-open-conversation").click()

        # The source conversation loads with the artifact file open in the dock.
        expect(PreviewPanel(page).file_tab(name)).to_be_visible(timeout=8_000)
    finally:
        purge(page, name)
        delete_file(name)
