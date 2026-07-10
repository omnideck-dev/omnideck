"""Read the current page as clean text content (markdown)."""

from __future__ import annotations

import logging

from playwright.async_api import Error as PlaywrightError

from tools.browser.core import get_active_view, get_browser
from tools.browser.core._formatting import format_page_header
from tools.browser.core._html import html_to_markdown
from tools.browser.core.exceptions import BrowserToolError

logger = logging.getLogger(__name__)

# Chars per chunk — roughly 5k tokens of markdown, a comfortable single read.
_READ_BUDGET = 20_000

# Non-blank lines of context kept either side of a query match. The markdown
# converter runs unwrapped, so one non-blank line is a whole paragraph. Blank
# lines don't count towards this, otherwise the context is spent on the blank
# separator that follows every block and the match arrives with nothing around it.
_QUERY_CONTEXT_LINES = 1

# Ceiling on passages in a query result, so a common word cannot return the
# whole page back through the search path.
_QUERY_MAX_PASSAGES = 20


def _chunk_bounds(content: str) -> list[tuple[int, int]]:
    """Return the ``[start, end)`` char offsets of each chunk of *content*.

    Boundaries land on line breaks so a chunk never splits a paragraph in
    half.  A single line longer than the budget is hard-split, since there is
    no break to land on.  Always returns at least one chunk.
    """
    budget = _READ_BUDGET
    bounds: list[tuple[int, int]] = []
    start = 0
    pos = 0

    for line in content.splitlines(keepends=True):
        end = pos + len(line)
        if pos > start and end - start > budget:
            bounds.append((start, pos))
            start = pos
        while end - start > budget:
            bounds.append((start, start + budget))
            start += budget
        pos = end

    if start < pos or not bounds:
        bounds.append((start, pos))
    return bounds


def _chunk_of(offset: int, bounds: list[tuple[int, int]]) -> int:
    """Return the 1-indexed chunk holding the char at *offset*."""
    for index, (_, end) in enumerate(bounds, start=1):
        if offset < end:
            return index
    return len(bounds)


def _describe_chunks(chunks: list[int]) -> str:
    """Render chunk numbers as ``chunk 3`` or ``chunks 3, 9 and 14``."""
    if len(chunks) == 1:
        return f"chunk {chunks[0]}"
    head = ", ".join(str(chunk) for chunk in chunks[:-1])
    return f"chunks {head} and {chunks[-1]}"


def _context_span(lines: list[str], index: int) -> range:
    """Return the line span covering *index* plus its context either side.

    Context is counted in non-blank lines, though the blank lines passed over
    on the way out are kept so the markdown keeps its shape.
    """
    lo = index
    taken = 0
    while lo > 0 and taken < _QUERY_CONTEXT_LINES:
        lo -= 1
        if lines[lo].strip():
            taken += 1

    hi = index
    taken = 0
    while hi < len(lines) - 1 and taken < _QUERY_CONTEXT_LINES:
        hi += 1
        if lines[hi].strip():
            taken += 1

    return range(lo, hi + 1)


def _status_line(chunk: int, total_chunks: int, total_chars: int) -> str:
    """Build the orientation line that opens an unfiltered read."""
    line = f"[chunk {chunk}/{total_chunks} · {total_chars:,} chars total]"
    if chunk < total_chunks:
        line += (
            f"\n[Read on with chunk={chunk + 1}, "
            'or jump straight to a passage with query="...".]'
        )
    return line


def _search(
    content: str, query: str, bounds: list[tuple[int, int]]
) -> tuple[str, bool]:
    """Search *content* for *query* and return ``(text, capped)``.

    *text* holds the matching passages, each carrying a line of context either
    side, separated by ``---`` and labeled with the chunk it came from.  It is
    empty when nothing matched.  *capped* is True when passages were dropped to
    stay inside the budget, which is the agent's cue to narrow the query.

    A line matches when every whitespace-separated word of *query* appears in
    it, in any order.  So a multi-word query finds the words co-occurring in a
    passage rather than only as one exact contiguous phrase, which is what an
    agent typing a natural phrase almost always means.
    """
    terms = query.lower().split()
    lines = content.split("\n")

    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    hits: set[int] = set()
    matched: set[int] = set()
    for index, line in enumerate(lines):
        low = line.lower()
        if terms and all(term in low for term in terms):
            hits.add(index)
            matched.update(_context_span(lines, index))

    if not matched:
        return "", False

    # Walk the matched line numbers in order, cutting them into runs of
    # consecutive lines. Each run becomes one passage.
    ordered = sorted(matched)
    runs: list[list[int]] = []
    current = [ordered[0]]
    for index in ordered[1:]:
        if index > current[-1] + 1:
            runs.append(current)
            current = [index]
        else:
            current.append(index)
    runs.append(current)

    # A passage is labeled with the chunk holding its first matching line, not
    # its first line. The leading context can start a chunk earlier than the
    # match, and pointing the agent there would send it to the wrong place.
    passages: list[tuple[str, int]] = []
    for run in runs:
        body = [i for i in run if lines[i].strip()]
        if not body:
            continue
        text = "\n".join(lines[i] for i in range(body[0], body[-1] + 1))
        first_hit = min(i for i in run if i in hits)
        passages.append((text, _chunk_of(offsets[first_hit], bounds)))

    if not passages:
        return "", False

    shown: list[tuple[str, int]] = []
    used = 0
    for text, chunk in passages:
        over_budget = used + len(text) > _READ_BUDGET
        if shown and (len(shown) >= _QUERY_MAX_PASSAGES or over_budget):
            break
        shown.append((text, chunk))
        used += len(text) + len("\n---\n")

    where = _describe_chunks(sorted({chunk for _, chunk in shown}))
    header = (
        f'[Search "{query}" — {len(passages)} match(es) in {where} '
        f"of {len(bounds)}.]"
    )
    capped = len(shown) < len(passages)
    if capped:
        header += (
            f"\n[Showing the first {len(shown)}. Narrow the query, "
            "or read a chunk to see a match in full.]"
        )
    else:
        header += "\n[Read a chunk to see any of these matches in full.]"

    body = "\n---\n".join(f"{text}\n(chunk {chunk})" for text, chunk in shown)
    return f"{header}\n\n{body}", capped


async def read_page(
    chunk: int = 1,
    query: str | None = None,
    *,
    tab: str,
) -> str:
    """Read the current page as markdown.

    Returns the page converted to markdown in full — nothing is selected away,
    so no content is silently dropped.  A long page is split into fixed-size
    chunks, and the result opens with the chunk you are on and how many exist.

    On a multi-chunk page, start with ``query``.  Chunk 1 is usually the top of
    the page, which is navigation, language links, and other boilerplate, not
    the content you came for.  ``query`` searches the whole page and jumps you
    straight to the matching passages, each labeled with the chunk it sits in;
    read ``chunk=N`` afterwards only if you need more of the surroundings than
    the passage showed.  Read from chunk 1 sequentially when the page is a
    single chunk, or when you are surveying a page you know nothing about and
    can't yet name what to search for.

    Use this tool when you need to READ text: articles, docs, search results.
    To find clickable elements instead, use ``browse_page()``.  To grep or
    post-process a very large page offline, use ``save_page_content()``.

    Args:
        chunk: Which chunk to return (1-indexed, default 1).  Ignored when
            ``query`` is given.
        query: Words to search for (case-insensitive).  A passage matches when
            it contains all the words, in any order, so a natural phrase works
            without guessing the exact wording.  Returns the matching passages
            rather than a chunk.  Example: ``read_page(query="refund policy")``
            to jump to refunds on a long page without reading all of it.
        tab: Stable tab ID to read — the ID shown in the snapshot
            header (e.g. ``tab="3"``).

    Returns:
        The page header line, a chunk or search status line, and the markdown.

    Raises:
        BrowserToolError: If there is no open page, or ``chunk`` is past the
            end of the page.
    """
    if chunk < 1:
        raise BrowserToolError("chunk must be 1 or greater", tool="read_page")

    browser, view = await get_active_view("read_page", tab=tab)
    header = format_page_header(
        title=view.title,
        url=view.url,
        tab_id=browser.tab_id_of(view.page),
    )

    # A blocked view has no readable text in the browser; return only the banner
    # (which routes the agent to fetch_url) and skip the read entirely.
    if view.challenge:
        return f"{header}\n\n{view.challenge.banner}"

    try:
        raw_html: str = await view.frame.content()
    except PlaywrightError as exc:
        logger.exception("Failed to read page content")
        raise BrowserToolError(
            "Failed to read page content", tool="read_page"
        ) from exc

    full_content = html_to_markdown(raw_html).strip()
    bounds = _chunk_bounds(full_content)

    if query:
        content, _ = _search(full_content, query, bounds)
        if not content:
            content = (
                f'[Search "{query}" — no matches on this page '
                f"({len(full_content):,} chars, {len(bounds)} chunks).]"
            )
    else:
        if chunk > len(bounds):
            raise BrowserToolError(
                f"chunk {chunk} is past the end of the page, "
                f"which has {len(bounds)}",
                tool="read_page",
            )
        start, end = bounds[chunk - 1]
        status = _status_line(chunk, len(bounds), len(full_content))
        content = f"{status}\n\n{full_content[start:end]}"

    return f"{header}\n\n{content}"


__all__ = ["read_page"]
