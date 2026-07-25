"""drag moves the pointer from a source ref to a target ref.

drag is mouse-based (a real mousedown on the source, mousemove, then mouseup on
the target) — not HTML5 drag-and-drop — so the fixture records the "drop" from
those raw mouse events. Source and target are buttons so the walker gives them
refs to pass to drag().
"""

from __future__ import annotations

from tools.browser import drag
from tools.browser import browse_page

from .._helpers import find_ref


async def test_drag_source_to_target(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/drag-drop/page.html")
    view = await browse_page(tab=tab)

    src = find_ref(view, role="button", name="Drag source")
    dst = find_ref(view, role="button", name="Drop target")
    assert src is not None
    assert dst is not None

    result = await drag(src, dst, tab=tab)
    assert "Dropped on target" in result
