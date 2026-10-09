"""Settling uses the selected document and reports bounded phase outcomes."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from browser.core.settling import _settle_frame
from config import BrowserWaitConfig


@pytest.mark.parametrize("use_page", [False, True])
async def test_settling_evaluates_all_phases_in_the_selected_main_frame(monkeypatch, use_page):
    frame = MagicMock(spec=Frame)
    frame.wait_for_load_state = AsyncMock()
    page = MagicMock(spec=Page)
    page.main_frame = frame
    evaluate = AsyncMock(side_effect=[None, True, None])
    monkeypatch.setattr("browser.core.settling.evaluate_frame", evaluate)
    waits = BrowserWaitConfig()

    timings = await _settle_frame(page if use_page else frame, waits=waits)

    frame.wait_for_load_state.assert_awaited_once_with("load", timeout=waits.load_timeout_ms)
    assert evaluate.await_count == 3
    assert all(call.args[0] is frame for call in evaluate.await_args_list)
    frame.evaluate.assert_not_called()
    frame.wait_for_function.assert_not_called()
    assert not timings.dom_quiet_timed_out
    assert timings.error is None


async def test_dom_deadline_marks_timeout_and_still_waits_for_animations(monkeypatch):
    frame = MagicMock(spec=Frame)
    frame.wait_for_load_state = AsyncMock()
    evaluate = AsyncMock(side_effect=[None, False, None])
    monkeypatch.setattr("browser.core.settling.evaluate_frame", evaluate)

    timings = await _settle_frame(frame, waits=BrowserWaitConfig())

    assert timings.dom_quiet_timed_out
    assert evaluate.await_count == 3
    assert timings.error is None


async def test_load_timeout_does_not_skip_rendering_settle_phases(monkeypatch):
    frame = MagicMock(spec=Frame)
    frame.wait_for_load_state = AsyncMock(side_effect=PlaywrightTimeoutError("load timed out"))
    evaluate = AsyncMock(side_effect=[None, True, None])
    monkeypatch.setattr("browser.core.settling.evaluate_frame", evaluate)

    timings = await _settle_frame(frame, waits=BrowserWaitConfig())

    assert timings.load_timed_out
    assert evaluate.await_count == 3
    assert timings.error is None


async def test_document_replacement_ends_settling_with_its_error(monkeypatch):
    frame = MagicMock(spec=Frame)
    frame.wait_for_load_state = AsyncMock()
    evaluate = AsyncMock(side_effect=PlaywrightError("Execution context was destroyed"))
    monkeypatch.setattr("browser.core.settling.evaluate_frame", evaluate)

    timings = await _settle_frame(frame, waits=BrowserWaitConfig())

    assert timings.error == "Execution context was destroyed"
    assert evaluate.await_count == 1
