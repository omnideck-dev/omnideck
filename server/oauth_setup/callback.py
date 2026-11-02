"""Single-use browser authorization handoff, independent of HTTP and provider SDKs."""

import asyncio
import secrets
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlsplit

_MAX_QUERY_LENGTH = 8192


@dataclass(frozen=True, repr=False)
class AuthorizationResponse:
    code: str
    state: str
    iss: str | None


@dataclass(frozen=True)
class CallbackReply:
    status: int
    message: str


class OAuthCallbackError(Exception):
    """Safe local message; never includes provider text, codes or state."""

    def __init__(self, message: str, *, status: Literal["error", "denied", "expired", "cancelled"] = "error") -> None:
        super().__init__(message)
        self.status = status


class OAuthCallback:
    """One setup attempt, owned by the app-scoped coordinator.

    Each provider adapter calls ``arm`` before presenting its authorize URL
    and consumes ``wait_for_result`` once. Provider-specific protocol checks
    (such as MCP authorization-server issuer validation) stay in the adapter. No credentials or integration records are persisted here.
    """

    def __init__(self, *, redirect_uri: str, timeout: float) -> None:
        self.redirect_uri = redirect_uri
        self._authority = urlsplit(redirect_uri).netloc
        self._path = urlsplit(redirect_uri).path
        self._timeout = timeout
        self._state: str | None = None
        self._armed = False
        self._finished = False
        self._waiting = False
        self._consumed = False
        self._event = asyncio.Event()
        self._timer: asyncio.TimerHandle | None = None
        self._deadline: float | None = None
        self._result: AuthorizationResponse | OAuthCallbackError | None = None

    def arm(self, authorization_url: str) -> None:
        """Bind this attempt to the SDK's state and exact registered redirect.

        This does not validate the remote endpoint or open a browser. Remote
        URL policy belongs to the provider adapter before it presents the URL.
        """
        if self._armed or self._finished:
            raise OAuthCallbackError("This sign-in attempt cannot be started again.")
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
            raise OAuthCallbackError("The sign-in request has an invalid callback configuration.")
        self._state = state[0]
        self._armed = True
        loop = asyncio.get_running_loop()
        self._deadline = loop.time() + self._timeout
        self._timer = loop.call_at(self._deadline, self._expire)

    async def wait_for_result(self) -> AuthorizationResponse:
        """Deliver one result to the SDK; cancellation invalidates this attempt."""
        if not self._armed or self._waiting or self._consumed:
            raise OAuthCallbackError("No sign-in response is available for this attempt.")
        self._waiting = True
        try:
            await self._event.wait()
            result = self._result
            self._result = None
            self._consumed = True
            if isinstance(result, OAuthCallbackError):
                raise result
            if result is None:
                raise OAuthCallbackError("Sign-in was cancelled.", status="cancelled")
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
        self._finish(OAuthCallbackError("Sign-in was cancelled.", status="cancelled"))

    def _expire(self) -> None:
        self._finish(OAuthCallbackError("Sign-in timed out. Start again.", status="expired"))

    def _finish(self, result: AuthorizationResponse | OAuthCallbackError) -> None:
        self._finished = True
        self._state = None
        self._result = result
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._event.set()

    def accept(self, *, authority: str, query_string: str) -> CallbackReply:
        """Accept one well-formed GET without reflecting or logging its query."""
        # Never derive the redirect URI from Host/Forwarded. Require the
        # configured public authority; reverse proxies must preserve Host.
        if authority != self._authority:
            return CallbackReply(400, "Invalid callback address.")
        # Check the deadline as well as the timer: a busy event loop can process
        # a request before an already-due timer callback gets its turn.
        if not self._finished and self._deadline is not None and asyncio.get_running_loop().time() >= self._deadline:
            self._expire()
        if not self._armed or self._finished:
            return CallbackReply(410, "This sign-in attempt is no longer waiting for a response.")
        if len(query_string) > _MAX_QUERY_LENGTH:
            return CallbackReply(400, "Invalid sign-in response.")
        try:
            values = parse_qs(query_string, keep_blank_values=True, max_num_fields=32)
        except ValueError:
            return CallbackReply(400, "Invalid sign-in response.")
        if any(len(value) != 1 for value in values.values()):
            return CallbackReply(400, "Invalid sign-in response.")
        query = {key: value[0] for key, value in values.items()}
        state = query.get("state", "")
        if (
            not state.isascii() or self._state is None
            or not secrets.compare_digest(state, self._state)
        ):
            # Unrelated traffic must not cancel the legitimate browser flow.
            return CallbackReply(400, "Invalid sign-in response.")
        code, error, issuer = query.get("code"), query.get("error"), query.get("iss")
        if (
            ("code" in query) == ("error" in query)
            or not (code or error) or ("iss" in query and not issuer)
        ):
            return CallbackReply(400, "Invalid sign-in response.")
        if error is not None:
            message = "Sign-in was declined." if error == "access_denied" else "The provider could not complete sign-in."
            self._finish(OAuthCallbackError(message, status="denied" if error == "access_denied" else "error"))
            return CallbackReply(200, message + " Return to omnideck.")
        # Do not yield between checking and consuming state: concurrent/replayed
        # callbacks must never release the same code to two exchanges.
        self._finish(AuthorizationResponse(code=code or "", state=state, iss=issuer))
        return CallbackReply(200, "Sign-in response received. Return to omnideck to finish connecting.")

    def matches(self, state: str, path: str) -> bool:
        return (self._state is not None and state.isascii() and path == self._path
                and secrets.compare_digest(state, self._state))
