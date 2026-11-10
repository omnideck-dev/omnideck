"""Public-tool regressions from the October browser issue sweep."""

from __future__ import annotations

import pytest

from tools.browser import browse_page, click, execute_javascript, fill_field

from .._helpers import find_ref, page_body


async def test_adopted_cross_realm_widgets_remain_interactive(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/rendering-regressions/cross-realm.html")
    assert "true" in await execute_javascript("document.body.dataset.crossRealm", tab=tab)
    view = await browse_page(tab=tab)
    assert "document rendering failed" not in view
    for name in ("Original control", "Adopted control", "Adopted shadow control"):
        assert find_ref(view, role="button", name=name) is not None
    assert find_ref(view, role="textbox", name="Passenger") is not None
    ref = find_ref(view, role="button", name="Adopted control")
    assert "Widget activated" in await click(ref, tab=tab)


@pytest.mark.parametrize("full_page", [False, True])
async def test_hidden_dialog_subtrees_never_produce_refs(open_tab, servers, full_page):
    tab = await open_tab(f"{servers.primary}/rendering-regressions/hidden.html")
    view = await browse_page(full_page=full_page, tab=tab)
    assert "Hidden " not in page_body(view)
    assert find_ref(view, role="button", name="Visible control") is not None
    assert find_ref(view, role="button", name="Visibility restored control") is not None
    assert (find_ref(view, role="button", name="Offscreen control") is not None) == full_page
    scoped = await browse_page(full_page=True, scope="Hidden display section", tab=tab)
    assert "not found, showing full page" in scoped


async def test_single_character_content_survives_all_walk_paths(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/rendering-regressions/text.html")
    lines = page_body(await browse_page(tab=tab)).splitlines()
    assert "[h1] A" in lines
    for text in ("B", "C", "D", "E", "0", "✓", "日", "F"):
        assert text in [line.strip() for line in lines], text


async def test_contenteditable_values_are_visible_before_and_after_fill(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/rendering-regressions/text.html")
    view = await browse_page(tab=tab)
    assert "Notes = hello world" in view
    assert "First line" in view and "Second line" in view
    assert "Regular input = input value" in view
    ref = find_ref(view, role="textbox", name="Notes")
    filled = await fill_field(ref, "Updated notes", tab=tab)
    assert "Notes = Updated notes" in filled
    assert "Notes = Updated notes" in await browse_page(tab=tab)


@pytest.mark.parametrize("section", ["Alpha", "Beta", "Gamma", "Delta"])
async def test_scope_preserves_heading_controls_and_subsections(open_tab, servers, section):
    tab = await open_tab(f"{servers.primary}/rendering-regressions/headings.html")
    view = await browse_page(full_page=True, scope=f"{section} Section", tab=tab)
    assert "not found" not in view
    assert find_ref(view, role="button", name=f"{section} body") is not None
    assert find_ref(view, role="button", name="Outside body") is None
    for other in {"Alpha", "Beta", "Gamma", "Delta"} - {section}:
        assert find_ref(view, role="button", name=f"{other} body") is None
    if section == "Alpha":
        assert find_ref(view, role="link", name="Link for Alpha Section") is not None
        assert find_ref(view, role="button", name="Nested body") is not None
    if section == "Beta":
        assert find_ref(view, role="link", name="Beta Section") is not None
    if section == "Gamma":
        assert find_ref(view, role="button", name="Inline gamma control") is not None


async def test_scrolled_sticky_section_can_be_scoped_and_clicked(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/rendering-regressions/sticky.html")
    await execute_javascript("window.scrollTo(0, 1000)", tab=tab)
    view = await browse_page(full_page=True, scope="Persistent section", tab=tab)
    assert "not found" not in view
    assert find_ref(view, role="button", name="Next action") is None
    ref = find_ref(view, role="button", name="Sticky action")
    assert ref is not None
    assert "Sticky action completed" in await click(ref, tab=tab)


async def test_consent_banner_with_hidden_chrome_does_not_hide_page(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/rendering-regressions/consent.html")
    view = await browse_page(tab=tab)
    assert "[Modal dialog open" not in view
    assert find_ref(view, role="button", name="Accept cookies") is not None
    ref = find_ref(view, role="button", name="Show forecast")
    assert ref is not None
    assert "Forecast opened" in await click(ref, tab=tab)


async def test_empty_pointer_overlay_does_not_erase_page_snapshot(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/rendering-regressions/empty-overlay.html")
    view = await browse_page(tab=tab)
    assert "[Modal dialog open" not in view
    assert "Today's stories" in view
    assert find_ref(view, role="button", name="Read story") is not None
