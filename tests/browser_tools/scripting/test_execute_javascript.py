"""execute_javascript accepts expression/return/function forms and captures logs."""

from __future__ import annotations

import asyncio

from tools.browser import execute_javascript


async def test_execute_javascript_expression(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/article/article.html")
    result = await execute_javascript("document.title", tab=tab)
    assert "Hubble Telescope" in result


async def test_execute_javascript_bare_return(open_tab, servers):
    # A top-level `return` is wrapped in a function so it runs (matches the
    # tool's documented contract).
    tab = await open_tab(f"{servers.primary}/article/article.html")
    result = await execute_javascript("return document.title;", tab=tab)
    assert "Hubble Telescope" in result


async def test_execute_javascript_function_and_console(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/article/article.html")
    result = await execute_javascript("() => { console.log('probe-marker'); return 42; }", tab=tab)
    assert "42" in result
    assert "probe-marker" in result


async def test_execute_javascript_syntax_error_is_reported(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/article/article.html")

    result = await execute_javascript("() => {", tab=tab)

    assert "[JavaScript: error]" in result
    assert "execution failed" in result


async def test_execute_javascript_timeout_is_reported_and_page_recovers(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/article/article.html")

    timed_out = await execute_javascript(
        "() => new Promise(resolve => setTimeout(() => resolve('late'), 200))",
        timeout_ms=50,
        tab=tab,
    )

    assert "[JavaScript: error]" in timed_out
    assert "timed out after 50ms" in timed_out
    # Let the page-side promise finish so browser teardown has no remote
    # evaluation still outstanding after the local timeout.
    await asyncio.sleep(0.25)
    assert "Hubble Telescope" in await execute_javascript("document.title", tab=tab)
