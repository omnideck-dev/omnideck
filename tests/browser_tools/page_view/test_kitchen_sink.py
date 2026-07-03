"""Holistic walker selection on a busy page: what it picks and what it drops.

One page mixing every interactive role, images, headings, containers, ARIA
states, and hidden elements — so a walker refactor that changes selection
shows up here.
"""

from __future__ import annotations

from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def _view(browser_session, servers) -> str:
    tab = await browser_session.open(f"{servers.primary}/kitchen-sink/page.html")
    return await browse_page(full_page=True, tab=tab)


async def test_interactive_roles(browser_session, servers):
    view = await _view(browser_session, servers)
    assert find_ref(view, role="link", name="A link") is not None
    assert find_ref(view, role="button", name="A button") is not None
    assert find_ref(view, role="textbox", name="Text input") is not None
    assert find_ref(view, role="searchbox", name="Search input") is not None
    assert find_ref(view, role="spinbutton", name="Number input") is not None
    assert find_ref(view, role="slider", name="Range input") is not None
    assert find_ref(view, role="textbox", name="Text area") is not None
    assert find_ref(view, role="checkbox", name="A checkbox") is not None
    assert find_ref(view, role="radio", name="A radio") is not None
    assert find_ref(view, role="combobox", name="A select") is not None
    assert find_ref(view, role="textbox", name="Editable note") is not None       # contenteditable
    assert find_ref(view, role="switch", name="A switch") is not None
    assert find_ref(view, role="tab", name="A tab") is not None


async def test_role_values_and_states(browser_session, servers):
    view = await _view(browser_session, servers)
    # value + range extents (pixel width is runtime-dependent, so match the prefix)
    assert "[slider] Range input = 5 (range 0-10," in view
    assert "[combobox] A select = One" in view
    # ARIA state annotations
    assert "A checkbox (checked)" in view
    assert "A switch (checked)" in view
    assert "A pressed button (pressed)" in view
    assert "An expanded button (expanded)" in view


async def test_headings_images_and_containers(browser_session, servers):
    view = await _view(browser_session, servers)
    assert "[h1] Kitchen sink" in view
    assert "[h2] Controls" in view
    assert "[img] A diagram" in view
    # table cells and list items are surfaced as text
    assert "Cell A" in view
    assert "Cell B" in view
    assert "Item one" in view
    assert "Item two" in view


async def test_hidden_elements_excluded(browser_session, servers):
    view = await _view(browser_session, servers)
    assert "Hidden by display" not in view       # display:none -> skip subtree
    assert "Hidden by visibility" not in view     # visibility:hidden -> skip self
    assert "Hidden by opacity" not in view        # opacity:0 -> skip self
    assert "Hidden by aria" not in view           # aria-hidden -> skip subtree
