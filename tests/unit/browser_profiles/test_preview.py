from unittest.mock import AsyncMock, MagicMock

from browser_profiles import _preview


async def test_preview_state_is_consumed_once_for_the_same_browser():
    _preview.reset_browser_state_previews()
    browser = MagicMock()
    browser.capture_storage_state = AsyncMock(return_value={"cookies": [], "origins": []})

    token, captured = await _preview.capture_browser_state_preview(browser, scope="user")

    assert (
        _preview.consume_browser_state_preview(
            token,
            scope="user",
            browser=browser,
        )
        == captured
    )
    assert (
        _preview.consume_browser_state_preview(
            token,
            scope="user",
            browser=browser,
        )
        is None
    )


async def test_preview_cannot_cross_browser_or_conversation_scope():
    _preview.reset_browser_state_previews()
    browser = MagicMock()
    browser.capture_storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    token, _captured = await _preview.capture_browser_state_preview(
        browser,
        scope="conversation:one",
    )

    assert (
        _preview.consume_browser_state_preview(
            token,
            scope="conversation:two",
            browser=browser,
        )
        is None
    )
