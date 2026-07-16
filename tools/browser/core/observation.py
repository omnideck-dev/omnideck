"""Resolve, stabilize, and snapshot the browser view as one operation."""

from __future__ import annotations

from playwright.async_api import Page, Response

from config import load_config
from tools.browser.core.browser import ActiveView, Browser
from tools.browser.core.page_view import DEFAULT_BUDGET, PageView, build_page_view
from tools.browser.core.waits import SettleTimings, wait_for_page_settle


async def observe_page(
    browser: Browser,
    page: Page,
    response: Response | None,
    *,
    initial_view: ActiveView | None = None,
    settle: bool = True,
    scope: str | None = None,
    budget: int = DEFAULT_BUDGET,
    full_page: bool = False,
) -> tuple[PageView, SettleTimings | None]:
    """Resolve and snapshot an active frame without a lifecycle gap.

    Interaction results settle the active frame first; an explicit browse can
    skip that policy and capture the current state immediately. A navigation can
    replace either observation mid-flight, so re-resolve and retry once when its
    generation changes. Permanent failures still flow into
    ``build_page_view``'s actionable fallback.
    """
    waits = load_config().tools.browser.waits
    view = initial_view
    timings: SettleTimings | None = None
    snapshot: PageView | None = None

    for attempt in range(2):
        if view is None:
            view = await browser.active_view(page=page)

        if view.challenge is not None:
            snapshot = await build_page_view(
                view,
                response,
                scope=scope,
                budget=budget,
                full_page=full_page,
            )
            break

        observed_generation = view.generation
        if settle:
            timings = await wait_for_page_settle(view.frame, waits=waits)
        else:
            timings = None

        view_changed = False
        if settle and not page.is_closed():
            current_view = await browser.active_view(page=page)
            view_changed = (
                current_view.generation != observed_generation
                or current_view.frame is not view.frame
            )
            view = current_view

        settle_failed = timings is not None and timings.error is not None
        if (settle_failed or view_changed) and attempt == 0:
            view = None
            continue

        # A redirect during settling makes the captured response stale. Prefer
        # the live page identity rather than an earlier redirect hop's URL.
        current_response = response
        if current_response is not None and current_response.url != page.url:
            current_response = None

        snapshot = await build_page_view(
            view,
            current_response,
            scope=scope,
            budget=budget,
            full_page=full_page,
        )

        if page.is_closed() or attempt == 1:
            break

        after_snapshot = await browser.active_view(page=page)
        if (
            after_snapshot.generation == view.generation
            and after_snapshot.frame is view.frame
        ):
            break

        # The walker raced another document. Discard both its refs and metadata
        # and observe the replacement generation once.
        view = None
        snapshot = None

    assert snapshot is not None
    return snapshot, timings


__all__ = ["observe_page"]
