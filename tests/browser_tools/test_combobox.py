"""A role="combobox" container must expose its inner <input>.

Autocomplete widgets (React Autosuggest, Downshift, MUI Autocomplete) put
role="combobox" on a container div and keep the real text field as an inner
<input>. That inner input needs its own ref, otherwise fill_field resolves the
ref to the div and rejects it (it's not an input/textarea/contenteditable).
"""

from __future__ import annotations

from tools.browser.interactions import fill_field
from tools.browser.snapshot_tool import browse_page

from ._helpers import find_ref


async def test_combobox_container_exposes_inner_input(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/combobox/search.html")
    view = await browse_page(tab=tab)

    # The inner input is exposed as a textbox with its own ref...
    assert find_ref(view, role="textbox", name="Search the catalog") is not None
    # ...and the non-fillable container div is not emitted as a separate node.
    assert find_ref(view, role="combobox") is None


async def test_fill_field_types_into_combobox_input(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/combobox/search.html")
    view = await browse_page(tab=tab)

    ref = find_ref(view, role="textbox", name="Search the catalog")
    assert ref is not None
    result = await fill_field(ref, "Dune", tab=tab)
    assert "Search the catalog = Dune" in result
