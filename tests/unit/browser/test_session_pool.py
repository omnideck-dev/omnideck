"""Tests for keyed Browser session ownership and lazy initialization."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from browser.core.browser import Browser
from browser.session_pool import BrowserSessionPool
from tests.unit.tools.browser.support.playwright_stubs import EventEmitterStub


class _FakePage:
    def __init__(self) -> None:
        self._closed = False

    def is_closed(self) -> bool:
        return self._closed

    def on(self, event: str, callback: Any) -> None:
        pass

    async def close(self) -> None:
        self._closed = True


class _FakeContext(EventEmitterStub):
    def __init__(self) -> None:
        super().__init__()
        self.pages: list[_FakePage] = []
        self.browser = MagicMock()
        self._closed = False

    async def new_page(self) -> _FakePage:
        page = _FakePage()
        self.pages.append(page)
        self.emit("page", page)
        return page

    async def storage_state(self) -> dict[str, Any]:
        return {"cookies": [], "origins": []}

    async def close(self) -> None:
        self._closed = True

    async def set_extra_http_headers(self, headers: dict[str, str]) -> None:
        pass

    async def add_init_script(self, script: str) -> None:
        pass


def _browser(context: _FakeContext | None = None) -> Browser:
    browser = Browser(
        context=context or _FakeContext(),
        extra_headers={"Accept-Language": "en"},
    )
    browser._downloads_dir = "/tmp/dl"
    return browser


def _pool_with_host(*browsers: Browser) -> tuple[BrowserSessionPool, MagicMock]:
    pool = BrowserSessionPool()
    host = MagicMock()
    host.create_session = AsyncMock(side_effect=browsers)
    pool._host = host
    return pool, host


async def test_key_reuses_one_session() -> None:
    browser = _browser()
    pool, host = _pool_with_host(browser)

    first = await pool.get_or_create("agent-one")
    second = await pool.get_or_create("agent-one")

    assert first is second
    host.create_session.assert_awaited_once()


async def test_different_keys_get_isolated_sessions() -> None:
    first_browser = _browser()
    second_browser = _browser()
    pool, _host = _pool_with_host(first_browser, second_browser)

    first = await pool.get_or_create("agent-one")
    second = await pool.get_or_create("agent-two")

    assert first is first_browser
    assert second is second_browser


async def test_prepared_state_is_loaded_only_when_session_is_created() -> None:
    browser = _browser()
    pool, host = _pool_with_host(browser)
    load_state = AsyncMock(
        return_value={"cookies": [{"name": "session", "value": "abc"}], "origins": []},
    )

    await pool.prepare("agent-one", load_state)
    load_state.assert_not_awaited()
    await pool.get_or_create("agent-one")

    load_state.assert_awaited_once_with()
    assert host.create_session.await_args.kwargs["storage_state"]["cookies"][0]["value"] == "abc"


async def test_existing_session_does_not_consume_new_initializer() -> None:
    browser = _browser()
    pool, host = _pool_with_host(browser)
    await pool.get_or_create("agent-one")
    load_state = AsyncMock()

    await pool.prepare("agent-one", load_state)
    result = await pool.get_or_create("agent-one")

    assert result is browser
    load_state.assert_not_awaited()
    host.create_session.assert_awaited_once()


async def test_release_closes_session_and_discards_initializer() -> None:
    browser = _browser()
    pool, _host = _pool_with_host(browser)
    await pool.get_or_create("agent-one")
    await pool.prepare("unused", AsyncMock())

    await pool.release("agent-one")
    await pool.release("unused")

    assert browser._closed is True
    assert await pool.get("agent-one") is None
    assert "unused" not in pool._initializers


async def test_replace_keeps_key_and_closes_previous_session() -> None:
    previous = _browser()
    replacement = _browser()
    pool, host = _pool_with_host(previous, replacement)
    await pool.get_or_create("user")

    result = await pool.replace(
        "user",
        storage_state={"cookies": [], "origins": []},
        open_initial_tab=True,
    )

    assert result is replacement
    assert previous._closed is True
    assert len(replacement.tabs()) == 1
    assert host.create_session.await_count == 2
