"""Explicit role attributes on form elements.

An <input>/<textarea>/<select> is always interactive, so an invalid explicit
role (e.g. role="form" on an <input>) must not hide it — the walker falls back
to the implicit role. A valid interactive explicit role is still honored.
"""

from __future__ import annotations

from tools.browser.interactions import fill_field
from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_invalid_explicit_role_falls_back_to_implicit(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/explicit-role/page.html")
    view = await browse_page(tab=tab)

    # role="form" is invalid on an <input>; it must still be a textbox...
    ref = find_ref(view, role="textbox", name="Main search form")
    assert ref is not None
    # ...and fillable.
    result = await fill_field(ref, "hello", tab=tab)
    assert "Main search form = hello" in result


async def test_valid_explicit_role_preserved(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/explicit-role/page.html")
    view = await browse_page(tab=tab)

    # A valid interactive role on an input is kept, not overwritten.
    assert find_ref(view, role="searchbox", name="Valid search") is not None
