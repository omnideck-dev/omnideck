"""Small helpers for asserting against browse_page/click/fill_field output.

The tools render each interactive element as a ``[ref] [role] name`` line
(optionally with a ``= value`` or ``(checked)`` suffix). Tests need the ref
number to feed back into ``click``/``fill_field``, so parse it out by role
and name substring rather than hard-coding ref numbers (which shift as the
page changes).
"""

from __future__ import annotations

import re

_LINE = re.compile(r"\[(\d+)\]\s+\[([a-z]+)\]\s*(.*)")


def page_body(view: str) -> str:
    """Return the rendered body of a page view, minus the header lines.

    The ``[Page: ...]`` and ``[Viewport: ...]`` lines carry a random port and the
    live scroll position, so a test that pins the exact text the agent sees would
    be flaky on them. Everything else is what the agent actually reads.
    """
    kept = [
        line
        for line in view.splitlines()
        if not line.startswith("[Page:") and not line.startswith("[Viewport:")
    ]
    return "\n".join(kept).strip()


def find_ref(view: str, *, role: str | None = None, name: str | None = None) -> str | None:
    """Return the ref of the first element matching *role* and *name*.

    *name* matches as a case-insensitive substring of the rendered name.
    Returns ``None`` when nothing matches.
    """
    for raw in view.splitlines():
        match = _LINE.match(raw.strip())
        if match is None:
            continue
        ref, matched_role, matched_name = match.groups()
        if role is not None and matched_role != role:
            continue
        if name is not None and name.lower() not in matched_name.lower():
            continue
        return ref
    return None
