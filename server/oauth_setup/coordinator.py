"""One owner of interactive OAuth tasks, cancellation and supervisor commits."""

import asyncio
import logging
import secrets
import time
from typing import Any
from collections.abc import Awaitable, Callable

from brokering.supervisor_client import SupervisorError
from .callback import OAuthCallback, OAuthCallbackError
from .models import (
    BrowserAuthorization, Commit, NewConnection, OAuthAdapter, Reconnect,
    SetupAttempt, SetupError,
)

logger = logging.getLogger(__name__)
MAX_ACTIVE_ATTEMPTS = 32
INTERACTIVE_TIMEOUT = 600
START_TIMEOUT = 35
TERMINAL_RETENTION = 60


class OAuthSetupCoordinator:
    """App-scoped setup. Providers prepare data; only this owner commits it."""

    def __init__(self, *, commit: Commit, refresh: Callable[[], Awaitable[bool]]) -> None:
        self._commit = commit
        self._refresh = refresh
        self._pending: dict[str, SetupAttempt] = {}
        self._closed = False

    async def start(
        self, adapter: OAuthAdapter, target: NewConnection | Reconnect, *, redirect_uri: str,
    ) -> SetupAttempt:
        self._prune()
        if self._closed:
            raise ValueError("Sign-in is shutting down.")
        if sum(attempt.status in {"pending", "committing"} for attempt in self._pending.values()) >= MAX_ACTIVE_ATTEMPTS:
            raise ValueError("Too many sign-ins in progress. Finish or cancel one before starting another.")
        browser = BrowserAuthorization(OAuthCallback(redirect_uri=redirect_uri, timeout=INTERACTIVE_TIMEOUT))
        pending = SetupAttempt("oauth_" + secrets.token_urlsafe(32), browser)
        self._pending[pending.handle] = pending
        pending.task = asyncio.create_task(self._run(pending, adapter, target), name="oauth-setup")
        try:
            async with asyncio.timeout(START_TIMEOUT):
                await browser.ready.wait()
        except (Exception, asyncio.CancelledError):
            await self.cancel(pending.handle)
            raise
        return pending

    async def _run(self, pending: SetupAttempt, adapter: OAuthAdapter, target: NewConnection | Reconnect) -> None:
        try:
            async with asyncio.timeout(INTERACTIVE_TIMEOUT):
                prepared = await adapter.prepare(pending.browser)
            # No await between preparation and claiming the commit. Cancellation
            # either stops preparation or observes committing and leaves it alone.
            pending.status = "committing"
            pending.browser.ready.set()
            args: dict[str, Any] = {
                "kind": "integration", "auth_blob": prepared.credentials,
                "discovered_operations": [operation.public_dict() for operation in prepared.operations],
            }
            if isinstance(target, Reconnect):
                args["id"] = target.connection_id
                verb = "reconnect"
            else:
                args.update(slug=target.slug, label=target.label, user_suffix=target.user_suffix,
                            operation_grants=list(target.operation_grants))
                verb = "add"
            result = await self._commit(verb, args)
            connection_id = result["id"]
            if not isinstance(connection_id, str) or not connection_id:
                raise ValueError("Invalid supervisor result")
            # A cache reload cannot undo an already committed connection.
            pending.integration_id = connection_id
            pending.status = "success"
            pending.completed_at = time.monotonic()
            try:
                await self._refresh()
            except Exception:
                logger.warning("Connection saved; discovery refresh failed")
        except asyncio.CancelledError:
            pending.status = "cancelled"
            raise
        except OAuthCallbackError as exc:
            pending.status = exc.status
            if pending.status == "error":
                pending.error = {"code": "AUTH", "message": str(exc)}
        except SetupError as exc:
            pending.status = "error"
            pending.error = {"code": exc.code, "message": exc.message}
        except SupervisorError as exc:
            pending.status = "error"
            pending.error = {"code": exc.code, "message": "Could not save the connection. Check access and try again."}
        except TimeoutError:
            if pending.status == "committing":
                # Losing the supervisor reply does not establish whether its
                # transaction completed. Do not expire consent or retry a save.
                pending.status = "error"
                pending.error = {
                    "code": "SAVE_UNCONFIRMED",
                    "message": "Saving the connection timed out. It may have been saved. Check Integrations before starting sign-in again.",
                }
            else:
                pending.status = "expired"
        except OSError:
            pending.status = "error"
            pending.error = {"code": "UNAVAILABLE", "message": "The connection service is unavailable. Try again."}
        except Exception:
            pending.status = "error"
            pending.error = {"code": "AUTH", "message": "Could not connect. Check the sign-in settings and try again."}
        finally:
            pending.completed_at = pending.completed_at or time.monotonic()
            pending.browser.receiver.cancel()
            pending.browser.authorize_url = None
            pending.browser.ready.set()

    def status(self, handle: str) -> SetupAttempt | None:
        self._prune()
        return self._pending.get(handle)

    def callback(self, state: str, path: str) -> OAuthCallback | None:
        return next((attempt.browser.receiver for attempt in self._pending.values()
                     if attempt.browser.receiver.matches(state, path)), None)

    async def cancel(self, handle: str) -> SetupAttempt | None:
        pending = self.status(handle)
        if pending is not None and pending.status == "pending" and pending.task is not None:
            pending.task.cancel()
            await asyncio.gather(pending.task, return_exceptions=True)
        # Committing and terminal outcomes are authoritative, never relabelled.
        return pending

    def _prune(self) -> None:
        cutoff = time.monotonic() - TERMINAL_RETENTION
        self._pending = {handle: attempt for handle, attempt in self._pending.items()
                         if attempt.completed_at is None or attempt.completed_at >= cutoff
                         or (attempt.task is not None and not attempt.task.done())}

    async def close(self) -> None:
        self._closed = True
        tasks = []
        for attempt in self._pending.values():
            if attempt.task is not None:
                tasks.append(attempt.task)
                if attempt.status == "pending":
                    attempt.task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._pending.clear()
