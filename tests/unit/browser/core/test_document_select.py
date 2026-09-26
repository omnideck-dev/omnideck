"""Navigation boundaries for trusted keyboard dropdown selection."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame, Page, Request

from browser.core.document import Document


@pytest.mark.parametrize("navigation_key", ["Home", "ArrowDown", "Enter"])
async def test_keyboard_selection_stops_when_selected_frame_navigates(monkeypatch, navigation_key):
    page = Mock(spec=Page)
    frame = Mock(spec=Frame)
    document = Document(frame=frame, page=page)

    async def press(keys):
        if keys == [navigation_key]:
            request = Mock(spec=Request, frame=frame)
            request.is_navigation_request.return_value = True
            page.on.call_args.args[1](request)

    press_mock = AsyncMock(side_effect=press)
    monkeypatch.setattr(document, "press_keys", press_mock)
    handle = Mock(evaluate=AsyncMock())

    assert await document._select_option_with_keyboard(handle, 1) is True
    keys_sent = [call.args[0][0] for call in press_mock.call_args_list]
    assert keys_sent == ["Home", "ArrowDown", "Enter"][: ["Home", "ArrowDown", "Enter"].index(navigation_key) + 1]
    handle.evaluate.assert_not_called()
    page.remove_listener.assert_called_once_with("request", page.on.call_args.args[1])


@pytest.mark.parametrize("verification_error", [False, True])
async def test_unrelated_frame_navigation_does_not_hide_selection_failure(monkeypatch, verification_error):
    page = Mock(spec=Page)
    document = Document(frame=Mock(spec=Frame), page=page)

    async def press(keys):
        if keys == ["Enter"]:
            request = Mock(spec=Request, frame=Mock(spec=Frame))
            request.is_navigation_request.return_value = True
            page.on.call_args.args[1](request)

    monkeypatch.setattr(document, "press_keys", AsyncMock(side_effect=press))
    verify = AsyncMock(return_value=0)
    if verification_error:
        verify.side_effect = PlaywrightError("Execution context was destroyed")

    assert await document._select_option_with_keyboard(Mock(evaluate=verify), 1) is False
    verify.assert_awaited_once()
    page.remove_listener.assert_called_once_with("request", page.on.call_args.args[1])
