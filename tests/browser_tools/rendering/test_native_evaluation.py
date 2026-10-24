"""Native evaluation preserves document identity, scope, and cancellation."""

import asyncio

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from browser.core.evaluation import evaluate_frame


@pytest.fixture
async def native_page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox"])
        try:
            page = await browser.new_page()
            await page.set_content("<html><body>Native evaluation fixture</body></html>")
            await page.evaluate("() => { window.eval = () => { throw new Error('eval is disabled'); }; }")
            yield page
        finally:
            await browser.close()


async def test_native_evaluation_has_fresh_lexical_scope_and_preserves_promises(native_page):
    frame = native_page.main_frame
    assert await evaluate_frame(frame, "const temporary = 1; temporary") == 1
    assert await evaluate_frame(frame, "const temporary = 2; temporary") == 2
    assert await evaluate_frame(frame, "let temporary = 3; temporary") == 3
    assert await evaluate_frame(frame, "typeof temporary") == "undefined"
    with pytest.raises(PlaywrightError, match="ReferenceError"):
        await evaluate_frame(frame, "/* retained directive */ 'use strict'; accidentalGlobal = 1")
    assert await evaluate_frame(frame, "typeof accidentalGlobal") == "undefined"
    assert await evaluate_frame(frame, "async value => { await Promise.resolve(); return value; }", {"n": 4}) == {
        "n": 4
    }
    assert await evaluate_frame(frame, "Promise.resolve({n: 5})") == {"n": 5}
    assert await evaluate_frame(frame, "Promise.resolve(() => { window.accidentalCall = true; })") is None
    assert await evaluate_frame(frame, "window.accidentalCall === undefined") is True
    with pytest.raises(PlaywrightError, match="eval is disabled"):
        await native_page.evaluate("1")


async def test_native_evaluation_resolves_identical_iframes_after_navigation(native_page):
    await native_page.set_content('<iframe srcdoc="<p>same</p>"></iframe><iframe srcdoc="<p>same</p>"></iframe>')
    frames = native_page.main_frame.child_frames
    assert len(frames) == 2
    for index, frame in enumerate(frames):
        await evaluate_frame(
            frame, "value => { window.frameValue = value; window.eval = () => { throw Error('disabled'); }; }", index
        )
    assert [await evaluate_frame(frame, "window.frameValue") for frame in frames] == [0, 1]
    await frames[0].goto("about:blank")
    assert await evaluate_frame(frames[0], "typeof window.frameValue") == "undefined"
    assert await evaluate_frame(frames[1], "window.frameValue") == 1
    for frame in native_page.frames:
        assert (
            await evaluate_frame(
                frame,
                "Array.from(document.documentElement.attributes).some(a => a.name.startsWith('data-omnideck-context-'))",
            )
            is False
        )


async def test_native_evaluation_infinite_loop_cancellation_is_bounded(native_page, monkeypatch):
    monkeypatch.setattr("browser.core.evaluation._CLEANUP_TIMEOUT_SECONDS", 0.05)
    session = await native_page.context.new_cdp_session(native_page)
    started = asyncio.get_running_loop().time()
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(evaluate_frame(native_page.main_frame, "while (true) {}"), timeout=0.1)
        assert asyncio.get_running_loop().time() - started < 1.5
    finally:
        await asyncio.wait_for(session.send("Runtime.terminateExecution"), timeout=2)
        await session.detach()
