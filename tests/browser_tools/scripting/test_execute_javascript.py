"""execute_javascript accepts expression/return/function forms and captures logs."""

from __future__ import annotations

from tools.browser.javascript import execute_javascript


async def test_execute_javascript_expression(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/article/article.html")
    result = await execute_javascript("document.title", tab=tab)
    assert "Hubble Telescope" in result


async def test_execute_javascript_bare_return(browser_session, servers):
    # A top-level `return` is wrapped in a function so it runs (matches the
    # tool's documented contract).
    tab = await browser_session.open(f"{servers.primary}/article/article.html")
    result = await execute_javascript("return document.title;", tab=tab)
    assert "Hubble Telescope" in result


async def test_execute_javascript_function_and_console(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/article/article.html")
    result = await execute_javascript(
        "() => { console.log('probe-marker'); return 42; }", tab=tab
    )
    assert "42" in result
    assert "probe-marker" in result
