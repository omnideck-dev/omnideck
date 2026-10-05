"""Single-use browser callback receiver for interactive MCP OAuth setup.

The main app routes use one receiver per setup with a trusted, published
loopback origin. The standalone listener helper is for host-local consumers
and fixtures; it cannot expose a container's unpublished loopback port.
The MCP SDK owns PKCE, issuer validation and token exchange. This module only
delivers a state-matched browser response to that SDK invocation.
"""

from __future__ import annotations

import asyncio
import math
import secrets
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

from aiohttp import web
from mcp.client.auth import AuthorizationCodeResult, OAuthFlowError


CALLBACK_PATH = "/api/integrations/mcp/oauth/callback"
_MAX_QUERY_LENGTH = 8192
_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
}


class MCPOAuthCallbackError(OAuthFlowError):
    """A safe local error; never includes provider text, codes, or OAuth state."""


class MCPOAuthCallback:
    """One setup attempt, owned by the setup coordinator or standalone listener.

    The SDK redirect handler calls ``arm`` before presenting its authorize URL
    to the user, then uses ``wait_for_result`` as its callback handler. The SDK
    checks the returned issuer against discovered metadata before exchanging
    the code. No credentials or integration records are persisted here.
    """

    def __init__(self, *, port: int, timeout: float) -> None:
        self.redirect_uri = f"http://localhost:{port}{CALLBACK_PATH}"
        self._authority = f"localhost:{port}"
        self._timeout = timeout
        self._state: str | None = None
        self._armed = False
        self._finished = False
        self._waiting = False
        self._consumed = False
        self._event = asyncio.Event()
        self._timer: asyncio.TimerHandle | None = None
        self._deadline: float | None = None
        self._result: AuthorizationCodeResult | MCPOAuthCallbackError | None = None

    def arm(self, authorization_url: str) -> None:
        """Bind this attempt to the SDK's state and exact registered redirect.

        This does not validate the remote endpoint or open a browser. Remote
        URL policy belongs to the OAuth coordinator before it presents the URL.
        """
        if self._armed or self._finished:
            raise MCPOAuthCallbackError("This sign-in attempt cannot be started again.")
        try:
            query = parse_qs(urlsplit(authorization_url).query, keep_blank_values=True, max_num_fields=32)
            state = query.get("state", [])
            valid = (
                len(state) == 1 and 32 <= len(state[0]) <= 512
                and state[0].isascii()
                and query.get("redirect_uri") == [self.redirect_uri]
                and query.get("response_type") == ["code"]
                and query.get("code_challenge_method") == ["S256"]
                and len(query.get("code_challenge", [])) == 1
                and bool(query["code_challenge"][0])
            )
        except ValueError:
            valid = False
        if not valid:
            raise MCPOAuthCallbackError("The sign-in request has an invalid callback configuration.")
        self._state = state[0]
        self._armed = True
        loop = asyncio.get_running_loop()
        self._deadline = loop.time() + self._timeout
        self._timer = loop.call_at(self._deadline, self._expire)

    async def wait_for_result(self) -> AuthorizationCodeResult:
        """Deliver one result to the SDK; cancellation invalidates this attempt."""
        if not self._armed or self._waiting or self._consumed:
            raise MCPOAuthCallbackError("No sign-in response is available for this attempt.")
        self._waiting = True
        try:
            await self._event.wait()
            result = self._result
            self._result = None
            self._consumed = True
            if isinstance(result, MCPOAuthCallbackError):
                raise result
            if result is None:
                raise MCPOAuthCallbackError("Sign-in was cancelled.")
            return result
        except asyncio.CancelledError:
            self.cancel()
            raise
        finally:
            self._waiting = False

    def cancel(self) -> None:
        """Discard an undelivered code and wake the waiter on setup close.

        Once delivered, cancellation of exchange/commit belongs to the owning
        coordinator. Closing this listener cannot roll back a token exchange.
        """
        self._finish(MCPOAuthCallbackError("Sign-in was cancelled."))

    def _expire(self) -> None:
        self._finish(MCPOAuthCallbackError("Sign-in timed out. Start again."))

    def _finish(self, result: AuthorizationCodeResult | MCPOAuthCallbackError) -> None:
        self._finished = True
        self._state = None
        self._result = result
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._event.set()

    async def handle_callback(self, request: web.Request) -> web.Response:
        """Accept one well-formed GET without reflecting or logging its query."""
        # Never derive the redirect URI from Host/Forwarded. Checking Host also
        # prevents a DNS-rebinding origin from addressing this loopback listener.
        if request.headers.get("Host") != self._authority:
            return self._response(400, "Invalid callback address.")
        # Check the deadline as well as the timer: a busy event loop can process
        # a request before an already-due timer callback gets its turn.
        if not self._finished and self._deadline is not None and asyncio.get_running_loop().time() >= self._deadline:
            self._expire()
        if not self._armed or self._finished:
            return self._response(410, "This sign-in attempt is no longer waiting for a response.")
        if len(request.query_string) > _MAX_QUERY_LENGTH:
            return self._response(400, "Invalid sign-in response.")
        query = request.query
        if any(len(query.getall(key)) != 1 for key in query):
            return self._response(400, "Invalid sign-in response.")
        state = query.get("state", "")
        if (
            not state.isascii() or self._state is None
            or not secrets.compare_digest(state, self._state)
        ):
            # Unrelated traffic must not cancel the legitimate browser flow.
            return self._response(400, "Invalid sign-in response.")
        code, error, issuer = query.get("code"), query.get("error"), query.get("iss")
        if (
            ("code" in query) == ("error" in query)
            or not (code or error) or ("iss" in query and not issuer)
        ):
            return self._response(400, "Invalid sign-in response.")
        if error is not None:
            message = "Sign-in was declined." if error == "access_denied" else "The provider could not complete sign-in."
            self._finish(MCPOAuthCallbackError(message))
            return self._response(200, message + " Return to omnideck.")
        # Do not yield between checking and consuming state: concurrent/replayed
        # callbacks must never release the same code to two exchanges.
        self._finish(AuthorizationCodeResult(code=code, state=state, iss=issuer))
        return self._response(200, "Sign-in response received. Return to omnideck to finish connecting.")

    @staticmethod
    def _response(status: int, text: str) -> web.Response:
        return web.Response(status=status, text=text, headers=_RESPONSE_HEADERS)


@asynccontextmanager
async def listen_for_mcp_oauth(*, port: int = 0, timeout: float = 600) -> AsyncIterator[MCPOAuthCallback]:
    """Bind a host-local listener for one explicitly initiated setup attempt.

    Port zero is useful for tests/providers accepting ephemeral loopback ports.
    Pre-registered clients such as Slack supply their configured fixed port.
    An occupied port fails; it never silently changes the registered redirect.
    The owner must close the context when setup ends or is cancelled.
    """
    if not 0 <= port <= 65535 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("A valid loopback port and positive finite timeout are required.")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))
        sock.setblocking(False)
        callback = MCPOAuthCallback(port=sock.getsockname()[1], timeout=timeout)
        app = web.Application(client_max_size=1024)
        app.router.add_get(CALLBACK_PATH, callback.handle_callback, allow_head=False)
        # aiohttp's default access log includes the query (code and state).
        # This dedicated app must never enable it or inherit the main app's log.
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=1)
        try:
            await runner.setup()
            await web.SockSite(runner, sock).start()
            yield callback
        finally:
            callback.cancel()
            await runner.cleanup()
