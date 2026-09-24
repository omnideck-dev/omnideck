"""Tests for the read_page tool and its chunking/search helpers."""

from __future__ import annotations

import pytest

from browser.core.document import Document
from tests.unit.tools.browser.support.playwright_stubs import StubPage
from tools.browser import BrowserToolError
from tools.browser.read import (
    _chunk_bounds,
    _chunk_of,
    _describe_chunks,
    _search,
    read_page,
)


def _make_fake_get_document(page: _ReadContentPage):
    """Build a fake document resolver for read-page unit tests."""

    async def _fake(tool_name: str, *, tab=None):
        from browser.core.exceptions import BrowserToolError as BTE

        if page.url in {"", "about:blank"}:
            raise BTE("No open page to read", tool=tool_name)

        class _Tab:
            id = 1
            url = page.url
            challenge = None

            async def title(self) -> str:
                return await page.title()

        return object(), _Tab(), Document(frame=page, page=page)

    return _fake


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


class _ReadContentPage(StubPage):
    """StubPage extended with HTML content for read_page tests."""

    def __init__(
        self,
        *,
        title: str = "Test Page",
        html: str = "<body><p>Hello world</p></body>",
        url: str = "https://example.test/article",
    ) -> None:
        super().__init__(title=title, body_text="", url=url)
        self._html = html

    async def content(self) -> str:
        return self._html


def _patch_view(monkeypatch: pytest.MonkeyPatch, page: _ReadContentPage) -> None:
    monkeypatch.setattr(
        "tools.browser.read.get_document",
        _make_fake_get_document(page),
    )


# ---------------------------------------------------------------------------
# _chunk_bounds — pure function tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_chunk_bounds_short_content_is_one_chunk() -> None:
    assert _chunk_bounds("hello") == [(0, 5)]


@pytest.mark.unit
def test_chunk_bounds_empty_content_is_one_empty_chunk() -> None:
    assert _chunk_bounds("") == [(0, 0)]


@pytest.mark.unit
def test_chunk_bounds_cover_content_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chunks tile the content with no gap and no overlap."""
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 100)
    content = "\n".join(f"line {i} " + "x" * 40 for i in range(20))

    bounds = _chunk_bounds(content)

    assert bounds[0][0] == 0
    assert bounds[-1][1] == len(content)
    for (_, prev_end), (next_start, _) in zip(bounds, bounds[1:]):
        assert prev_end == next_start
    assert "".join(content[s:e] for s, e in bounds) == content


@pytest.mark.unit
def test_chunk_bounds_break_on_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    """A chunk ends at a line break when the next line would overflow."""
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 30)
    content = "aaaa\nbbbb\ncccc\ndddd\neeee\nffff\ngggg"

    bounds = _chunk_bounds(content)

    assert len(bounds) > 1
    for start, end in bounds[:-1]:
        assert end - start <= 30
        assert content[end - 1] == "\n"


@pytest.mark.unit
def test_chunk_bounds_hard_split_a_long_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single line longer than the budget is split, since there's no break."""
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 10)
    content = "x" * 25

    bounds = _chunk_bounds(content)

    assert bounds == [(0, 10), (10, 20), (20, 25)]


# ---------------------------------------------------------------------------
# _chunk_of and _describe_chunks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_chunk_of_maps_offsets_to_chunks() -> None:
    bounds = [(0, 10), (10, 20), (20, 25)]

    assert _chunk_of(0, bounds) == 1
    assert _chunk_of(9, bounds) == 1
    assert _chunk_of(10, bounds) == 2
    assert _chunk_of(24, bounds) == 3


@pytest.mark.unit
def test_chunk_of_past_end_returns_last_chunk() -> None:
    assert _chunk_of(999, [(0, 10), (10, 20)]) == 2


@pytest.mark.unit
def test_describe_chunks_reads_naturally() -> None:
    assert _describe_chunks([3]) == "chunk 3"
    assert _describe_chunks([3, 9]) == "chunks 3 and 9"
    assert _describe_chunks([3, 9, 14]) == "chunks 3, 9 and 14"


# ---------------------------------------------------------------------------
# _search — pure function tests
# ---------------------------------------------------------------------------


def _search_text(content: str, query: str) -> str:
    text, _ = _search(content, query, _chunk_bounds(content))
    return text


@pytest.mark.unit
def test_search_no_matches_returns_empty() -> None:
    text, capped = _search("Line one\nLine two", "missing", [(0, 17)])
    assert text == ""
    assert capped is False


@pytest.mark.unit
def test_search_returns_match_with_context() -> None:
    content = "\n".join(["alpha", "beta", "gamma", "delta", "epsilon"])
    text = _search_text(content, "gamma")

    assert "gamma" in text
    assert "beta" in text
    assert "delta" in text
    assert "alpha" not in text


@pytest.mark.unit
def test_search_is_case_insensitive() -> None:
    assert "Hello World" in _search_text("Hello World\nfoo\nbye", "hello")


@pytest.mark.unit
def test_search_matches_all_words_in_any_order() -> None:
    """A multi-word query matches a line holding every word, order aside."""
    content = "\n".join(
        [
            "HTTP/2 extended persistent connections by multiplexing requests.",
            "An unrelated line about caching.",
        ]
    )
    text = _search_text(content, "multiplexing HTTP/2")

    assert "HTTP/2 extended persistent connections" in text


@pytest.mark.unit
def test_search_requires_every_word_present() -> None:
    """A line missing one of the query words does not match."""
    content = "\n".join(
        [
            "This line has multiplexing but not the protocol name.",
            "This line has neither term of interest.",
        ]
    )
    text, _ = _search(content, "multiplexing HTTP/2", _chunk_bounds(content))

    assert text == ""


@pytest.mark.unit
def test_search_separates_distant_passages() -> None:
    lines = ["match one", "a", "b", "c", "d", "match two"]
    text = _search_text("\n".join(lines), "match")

    assert "match one" in text
    assert "match two" in text
    assert "\n---\n" in text


@pytest.mark.unit
def test_search_merges_adjacent_matches() -> None:
    text = _search_text("\n".join(["alpha", "match A", "match B", "omega"]), "match")

    assert "match A" in text
    assert "match B" in text
    assert "\n---\n" not in text


@pytest.mark.unit
def test_search_header_reports_count_and_chunks() -> None:
    content = "\n".join(["match first", "a", "b", "c", "d", "e", "match second"])

    text = _search_text(content, "match")

    assert '[Search "match" — 2 match(es) in chunk 1 of 1.]' in text
    assert text.count("(chunk 1)") == 2


@pytest.mark.unit
def test_search_labels_passages_with_their_own_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two matches far apart are reported against different chunks."""
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 30)
    content = "\n".join(["needle a"] + ["pad"] * 20 + ["needle b"])

    text = _search_text(content, "needle")

    assert "(chunk 1)" in text
    assert "\n---\n" in text
    assert "in chunks 1 and " in text


@pytest.mark.unit
def test_search_caps_passages_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """A query matching everything is capped, not returned in full."""
    monkeypatch.setattr("tools.browser.read._QUERY_MAX_PASSAGES", 3)
    lines: list[str] = []
    for i in range(20):
        lines.extend([f"match {i}", "a", "b", "c", "d"])
    content = "\n".join(lines)

    text, capped = _search(content, "match", _chunk_bounds(content))

    assert capped is True
    assert "Showing the first 3." in text
    assert "Narrow the query" in text
    assert text.count("\n---\n") == 2


@pytest.mark.unit
def test_search_uncapped_result_says_nothing_about_narrowing() -> None:
    content = "\n".join(["match one", "a", "b", "c", "d", "match two"])
    text, capped = _search(content, "match", _chunk_bounds(content))

    assert capped is False
    assert "Narrow the query" not in text
    assert "Read a chunk to see any of these matches in full." in text


@pytest.mark.unit
def test_search_respects_the_read_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Passages stop accumulating once the budget is spent."""
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 400)
    lines: list[str] = []
    for i in range(20):
        lines.extend([f"match {i} " + "x" * 200, "a", "b", "c", "d"])
    content = "\n".join(lines)

    text, capped = _search(content, "match", _chunk_bounds(content))

    assert capped is True
    assert len(text) < 2000


# ---------------------------------------------------------------------------
# read_page — async integration tests with stubbed browser
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_returns_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """read_page returns a formatted string with converted markdown content."""
    _patch_view(
        monkeypatch,
        _ReadContentPage(
            title="My Article",
            html="<body><h1>Title</h1><p>Some content here.</p></body>",
            url="https://example.test/article",
        ),
    )

    result = await read_page(tab="1")

    assert "My Article" in result
    assert "https://example.test/article" in result
    assert "Title" in result
    assert "Some content here" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_returns_whole_body_not_just_the_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Content outside a thin <article> is still returned."""
    _patch_view(
        monkeypatch,
        _ReadContentPage(
            html=(
                "<body>"
                "<article><h1>Just the headline</h1></article>"
                "<main><p>The real content of the page lives here.</p></main>"
                "</body>"
            )
        ),
    )

    result = await read_page(tab="1")

    assert "Just the headline" in result
    assert "The real content of the page lives here." in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_single_chunk_reports_one_of_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_view(monkeypatch, _ReadContentPage(html="<body><p>Short</p></body>"))

    result = await read_page(tab="1")

    assert "[chunk 1/1 · 5 chars total]" in result
    assert "Read on with chunk=" not in result
    assert "truncated" not in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_long_content_is_chunked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Content longer than the budget reports more chunks and truncation."""
    long_body = "<p>" + ("word " * 10000) + "</p>"
    _patch_view(monkeypatch, _ReadContentPage(html=f"<body>{long_body}</body>"))

    result = await read_page(tab="1")

    assert "[chunk 1/3" in result
    assert "Read on with chunk=2" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_chunk_two_differs_from_chunk_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paragraphs = "".join(f"<p>Paragraph number {i} with unique content.</p>" for i in range(2000))
    _patch_view(monkeypatch, _ReadContentPage(html=f"<body>{paragraphs}</body>"))

    first = await read_page(chunk=1, tab="1")
    second = await read_page(chunk=2, tab="1")

    assert "[chunk 1/" in first
    assert "[chunk 2/" in second
    assert first != second


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_chunk_past_end_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_view(monkeypatch, _ReadContentPage(html="<body><p>Short</p></body>"))

    with pytest.raises(BrowserToolError, match="past the end"):
        await read_page(chunk=99, tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_chunk_zero_raises() -> None:
    with pytest.raises(BrowserToolError, match="chunk must be 1"):
        await read_page(chunk=0, tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_query_filters_content(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_view(
        monkeypatch,
        _ReadContentPage(
            html=(
                "<body>"
                "<p>Introduction paragraph</p>"
                "<p>The pricing plan costs $10/month.</p>"
                "<p>Another unrelated paragraph about features.</p>"
                "<p>See pricing details below.</p>"
                "</body>"
            )
        ),
    )

    result = await read_page(query="pricing", tab="1")

    assert '[Search "pricing"' in result
    assert "pricing" in result.lower()
    assert "(chunk 1)" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_query_searches_beyond_the_first_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A match late in a long page is found and located, not missed."""
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 200)
    filler = "".join(f"<p>Filler paragraph {i}.</p>" for i in range(40))
    _patch_view(
        monkeypatch,
        _ReadContentPage(html=f"<body>{filler}<p>The secret token.</p></body>"),
    )

    result = await read_page(query="secret token", tab="1")

    assert "The secret token." in result
    assert '[Search "secret token" — 1 match(es) in chunk ' in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_query_ignores_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    """query searches the whole page regardless of the chunk argument."""
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 200)
    filler = "".join(f"<p>Filler paragraph {i}.</p>" for i in range(40))
    _patch_view(
        monkeypatch,
        _ReadContentPage(html=f"<body>{filler}<p>The secret token.</p></body>"),
    )

    from_first = await read_page(chunk=1, query="secret token", tab="1")
    from_third = await read_page(chunk=3, query="secret token", tab="1")

    assert from_first == from_third


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_query_no_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_view(monkeypatch, _ReadContentPage(html="<body><p>Hello world</p></body>"))

    result = await read_page(query="nonexistent", tab="1")

    assert "no matches on this page" in result
    assert "1 chunks" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_no_browser_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from browser.core.exceptions import BrowserToolError as BTE

    async def _raise(tool_name: str, *, tab=None):
        raise BTE("No open page to read", tool=tool_name)

    monkeypatch.setattr("tools.browser.read.get_document", _raise)

    with pytest.raises(BrowserToolError, match="No open page"):
        await read_page(tab="1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_page_header_is_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """The header is one line: page, url, tab. No viewport, no empty status."""
    _patch_view(monkeypatch, _ReadContentPage(html="<body><p>Content</p></body>"))

    result = await read_page(tab="1")

    first_line = result.splitlines()[0]
    assert first_line.startswith("[Page: ")
    assert first_line.endswith("| tab=1]")
    assert "Viewport:" not in result
    # No dangling empty status slot between the url and the tab segment.
    assert " |  |" not in first_line
