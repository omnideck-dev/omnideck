"""Browser tools work when a document replaces its global eval function."""

from __future__ import annotations

import pytest

from config import load_config
from tools.browser import browse_page, click, execute_javascript, fill_field, read_page, save_page_content, scroll_page

from .._helpers import find_ref


def _fixture_url(servers, document_mode):
    if document_mode == "top":
        return f"{servers.primary}/eval-disabled/page.html"
    origin = servers.secondary if document_mode == "cross-origin" else servers.primary
    return servers.embed(f"{origin}/eval-disabled/page.html")


@pytest.mark.parametrize("document_mode", ["top", "same-origin", "cross-origin"])
async def test_disabled_eval_supports_read_save_and_ref_interactions(
    open_tab, servers, tmp_path, monkeypatch, document_mode,
):
    """Public tools read the selected document and use its rendered refs."""
    monkeypatch.setattr(load_config().virtual_computer, "home_dir", str(tmp_path))
    tab = await open_tab(_fixture_url(servers, document_mode))
    rendered = await browse_page(tab=tab)
    assert "Package checklist" in rendered
    assert "Host page heading" not in rendered
    label = find_ref(rendered, role="textbox", name="Package label")
    assert label is not None

    content = await read_page(tab=tab)
    assert "local record of packages for the household" in content
    assert "Host page heading" not in content
    saved = await save_page_content("packages.md", tab=tab)
    assert "[Saved: packages.md" in saved
    assert "local record of packages for the household" in (tmp_path / "packages.md").read_text()

    filled = await fill_field(label, "Groceries", tab=tab)
    assert "Package label = Groceries" in filled
    record = find_ref(filled, role="button", name="Record package")
    assert record is not None
    clicked = await click(record, tab=tab)
    assert "Recorded package: Groceries" in clicked
    assert "Recording package" not in clicked
    fragile = find_ref(clicked, role="checkbox", name="Mark fragile")
    assert fragile is not None
    checked = await click(fragile, tab=tab)
    assert "Mark fragile (checked)" in checked


@pytest.mark.parametrize("document_mode", ["top", "same-origin", "cross-origin"])
async def test_disabled_eval_javascript_preserves_page_globals_and_does_not_replay(
    open_tab, servers, document_mode,
):
    """Scripts retain their page context without replacing eval or retrying actions."""
    tab = await open_tab(_fixture_url(servers, document_mode))
    expression = await execute_javascript("window.fixtureState.marker", tab=tab)
    assert "[JavaScript: success]" in expression
    assert "page-owned-state" in expression

    identity = await execute_javascript("return window.eval === window.fixtureEvalGuard;", tab=tab)
    assert "[JavaScript: success]" in identity
    assert "true" in identity
    async_result = await execute_javascript(
        "async () => { await Promise.resolve(); return window.fixtureState.marker; }", tab=tab,
    )
    assert "[JavaScript: success]" in async_result
    assert "page-owned-state" in async_result

    failed_action = await execute_javascript(
        "() => { window.fixtureState.actions += 1; throw new Error('eval is disabled'); }", tab=tab,
    )
    assert "[JavaScript: error]" in failed_action
    outcome = await execute_javascript(
        "() => ({ marker: window.fixtureState.marker, actions: window.fixtureState.actions, "
        "guarded: window.eval === window.fixtureEvalGuard })", tab=tab,
    )
    assert '"actions": 1' in outcome
    assert '"guarded": true' in outcome
    assert "page-owned-state" in outcome


async def test_javascript_error_matching_eval_guard_is_not_retried(open_tab, servers):
    """A user script's own error must not trigger a second side effect."""
    tab = await open_tab(f"{servers.primary}/eval-disabled/page.html?guard=0")
    failed_action = await execute_javascript(
        "() => { window.fixtureState.actions += 1; throw new Error('eval is disabled'); }", tab=tab,
    )
    assert "[JavaScript: error]" in failed_action
    outcome = await execute_javascript("window.fixtureState.actions", tab=tab)
    assert "Result: 1" in outcome


@pytest.mark.parametrize("document_mode", ["top", "same-origin", "cross-origin"])
async def test_disabled_eval_scrolls_the_selected_document(open_tab, servers, document_mode):
    """Page-edge scrolling reveals and operates a control below the viewport."""
    tab = await open_tab(_fixture_url(servers, document_mode))
    initial = await browse_page(tab=tab)
    assert find_ref(initial, role="button", name="Confirm shelf") is None
    bottom = await scroll_page("bottom", tab=tab)
    confirm = find_ref(bottom, role="button", name="Confirm shelf")
    assert confirm is not None
    clicked = await click(confirm, tab=tab)
    assert "Shelf review complete." in clicked
    top = await scroll_page("top", tab=tab)
    assert find_ref(top, role="textbox", name="Package label") is not None
