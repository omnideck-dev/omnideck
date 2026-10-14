"""OAuth 2.0 Authorization Code Flow (loopback redirect) for the app server.

Drives Google's loopback redirect flow on behalf of an Add wizard. Lives
in the app server (not the supervisor) because the OAuth handshake is
pure HTTP plumbing — building authorize URLs, catching redirects,
exchanging codes for tokens.

Lifecycle:

1. UI POSTs ``/api/integrations/oauth/start`` with client credentials, scopes,
   slug, label, and zero operation grants. New connections also supply a user
   suffix; reconnects already have a stable integration ID and omit it.
2. Route handler computes ``redirect_uri`` from the request host and
   calls :meth:`OAuthIntegrationManager.start`. The flow builds an authorize URL with
   a fresh ``state`` token, registers a :class:`PendingOAuthIntegration`, returns
   ``state`` + URL.
3. UI opens that URL in a popup. User signs in, approves scopes.
4. Google redirects the popup to ``redirect_uri`` with ``?code=...&state=...``.
5. The ``/api/integrations/oauth/callback`` route extracts the params,
   calls :meth:`OAuthIntegrationManager.fetch_tokens` to exchange the code, then
   POSTs the resulting auth_blob to the supervisor's ``add`` verb.
6. On supervisor success, the route calls :meth:`OAuthIntegrationManager.mark_success`
   and the UI's poll loop sees ``status=success`` next tick.

State lives in app-server process memory only — restart loses pending
flows, user retries. Records expire after 10 minutes (matches Google's
authorize-URL TTL).
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC
from typing import Literal

from brokering.connection_data import BrokerConnectionData

# Google's token endpoint returns expanded scope URIs (e.g.
# "https://...userinfo.email" instead of the shorthand "email" we
# requested). oauthlib treats any scope difference as an error unless
# this env var is set.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google_auth_oauthlib.flow import Flow
from oauthlib.oauth2.rfc6749.errors import OAuth2Error

logger = logging.getLogger(__name__)


_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"

# Pending records expire after 10 minutes — matching the lifetime of
# Google's authorize URLs. Keeps stale records from accumulating when
# the user closes the popup without authorizing.
_PENDING_TTL_SECONDS = 600
_TOKEN_EXCHANGE_TIMEOUT_SECONDS = 60

# Terminal states must outlive the setup UI's cleanup request, especially when
# success and cancellation cross in flight. They do not need to remain for the
# lifetime of the app server, though; prune them after a generous grace period.
_TERMINAL_RETENTION_SECONDS = 60 * 60


PendingStatus = Literal[
    "pending", "exchanging", "committing", "success", "denied", "expired",
    "cancelled", "error",
]


@dataclass
class PendingOAuthIntegration:
    """One in-flight authorization-code flow.

    ``state`` doubles as the pending-id — it's the CSRF token we give
    Google in the authorize URL, that Google reflects back in the
    redirect, and that keys the in-memory record so the callback can
    match the redirect to its originating request without a second
    secret.

    ``flow`` is the live :class:`Flow` we used to mint the authorize
    URL. We hold onto it so ``fetch_token`` on the callback runs against
    the same client config that produced the URL — Google requires the
    redirect_uri at exchange time to match the one used when authorizing.
    """

    state: str
    slug: str
    user_suffix: str | None
    label: str
    scopes: list[str]
    operation_grants_raw: list[str] | None
    reconnect_id: str | None
    redirect_uri: str
    authorize_url: str
    expires_at: float
    flow: Flow = field(repr=False)
    status: PendingStatus = "pending"
    integration_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    completed_at: float | None = field(default=None, repr=False)


class OAuthIntegrationManager:
    """Owns all in-flight loopback OAuth flows for the app server."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingOAuthIntegration] = {}

    def start(
        self,
        *,
        slug: str,
        user_suffix: str | None,
        label: str,
        client_id: str,
        client_secret: str,
        scopes: list[str],
        operation_grants_raw: list[str] | None,
        reconnect_id: str | None,
        redirect_uri: str,
    ) -> PendingOAuthIntegration:
        """Build the Google authorize URL and register a pending record.

        The UI is responsible for preventing duplicate-id submissions
        (it shows the connected list while the wizard is open). If a
        collision sneaks through, the supervisor's ``add`` verb still
        rejects it at the end — worse UX, but functionally safe.
        """
        self._expire_and_prune()
        if not client_id or not client_secret:
            msg = "client_id and client_secret are required"
            raise ValueError(msg)
        if not scopes:
            msg = "at least one scope is required"
            raise ValueError(msg)
        if not redirect_uri:
            msg = "redirect_uri is required"
            raise ValueError(msg)

        # ``installed`` is the client_config key Google's libraries use
        # for Desktop / installed-app clients (the type we ship with).
        # The "type" name is historical — the same shape covers loopback
        # flow on modern Desktop clients.
        flow = Flow.from_client_config(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": _AUTH_URI,
                    "token_uri": _TOKEN_URI,
                    "redirect_uris": [redirect_uri],
                },
            },
            scopes=list(scopes),
        )
        flow.redirect_uri = redirect_uri

        state = secrets.token_urlsafe(32)
        # ``access_type=offline`` is what tells Google to issue a refresh
        # token alongside the access token; without it the user would have
        # to re-auth every hour. ``prompt=consent`` forces the consent
        # screen even on re-auth so we always get a refresh token (Google
        # sometimes omits it on silent re-grants).
        authorize_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )

        now = time.time()
        pending = PendingOAuthIntegration(
            state=state,
            slug=slug,
            user_suffix=user_suffix,
            label=label,
            scopes=list(scopes),
            operation_grants_raw=(
                list(operation_grants_raw)
                if operation_grants_raw is not None else None
            ),
            reconnect_id=reconnect_id,
            redirect_uri=redirect_uri,
            authorize_url=authorize_url,
            expires_at=now + _PENDING_TTL_SECONDS,
            flow=flow,
        )
        self._pending[state] = pending

        logger.info(
            "started OAuth loopback flow %s for slug=%s suffix=%s "
            "(scopes=%d, expires_in=%ds)",
            state[:8] + "…", slug, user_suffix,
            len(scopes), int(pending.expires_at - now),
        )
        return pending

    def status(self, state: str) -> PendingOAuthIntegration | None:
        """Snapshot the current pending record. Returns ``None`` for
        unknown states. Lazily transitions stale pending records to
        ``expired`` so the UI sees a terminal state instead of polling
        forever after the user closed the popup without authorizing.
        """
        self._expire_and_prune()
        pending = self._pending.get(state)
        if pending is None:
            return None
        return pending

    async def fetch_tokens(
        self,
        *,
        state: str,
        code: str | None,
        error: str | None,
    ) -> BrokerConnectionData | None:
        """Exchange the auth code for tokens, return an ``auth_blob``.

        Returns ``None`` on user denial / library error / unknown state —
        in those cases the pending record is marked terminal here so the
        UI's poll picks up the right shape next tick. The caller forwards
        a non-None return to the supervisor's ``add`` verb and reports
        success back via :meth:`mark_success`.
        """
        pending = self._pending.get(state)
        if pending is None:
            return None
        if pending.status != "pending":
            return None

        if error:
            if error == "access_denied":
                self._mark_terminal(state, "denied")
            else:
                self._mark_error(state, "AUTH", error)
            return None
        if not code:
            self._mark_error(
                state, "BAD_REQUEST",
                "callback missing both code and error",
            )
            return None

        # Claim the provider exchange before yielding to the worker thread.
        # OAuth authorization codes are single-use; without this transition,
        # duplicate browser callbacks could exchange the same code concurrently.
        pending.status = "exchanging"

        # ``flow.fetch_token`` is synchronous (POSTs to Google's token
        # endpoint via requests). Run it on the default executor so the
        # event loop stays responsive while Google takes its time.
        try:
            await asyncio.wait_for(
                asyncio.to_thread(pending.flow.fetch_token, code=code),
                timeout=_TOKEN_EXCHANGE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning("Google token exchange timed out")
            self._mark_error_if_status(
                state,
                "exchanging",
                "UPSTREAM",
                "The provider took too long to complete authorization.",
            )
            return None
        except OAuth2Error as exc:
            logger.warning("Google token exchange failed: %s", exc)
            self._mark_error_if_status(state, "exchanging", "AUTH", str(exc))
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("token exchange unexpected error: %s", exc)
            self._mark_error_if_status(state, "exchanging", "UPSTREAM", str(exc))
            return None

        # The setup modal can be dismissed while Google's token exchange is
        # running in a worker thread. Honor that cancellation before the
        # callback route gets a chance to persist the connection.
        current = self._pending.get(state)
        if current is None or current.status != "exchanging":
            return None

        try:
            return self._build_auth_blob(
                pending.flow,
                fallback_scopes=pending.scopes,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            logger.warning("provider returned an incomplete token response: %s", exc)
            self._mark_error_if_status(
                state,
                "exchanging",
                "AUTH",
                "The provider did not return reusable credentials. Try authorizing again.",
            )
            return None

    def cancel(self, state: str) -> PendingOAuthIntegration | None:
        """Cancel a setup-owned OAuth flow and retain its terminal record.

        Keeping the record lets a late provider callback see that setup was
        cancelled instead of creating an integration after the modal closed.
        A completed flow retains its ``integration_id`` so the UI can delete
        a connection that won the completion/cancellation race.
        """
        self._expire_and_prune()
        pending = self._pending.get(state)
        if pending is None:
            return None
        # Once the callback has started the supervisor transaction, it must
        # run to completion or perform its own rollback. Reporting a local
        # cancellation here would let a reconnect commit while the UI says it
        # was discarded.
        if pending.status == "committing":
            return pending
        if pending.status not in {"denied", "expired", "error"}:
            self._mark_terminal(state, "cancelled")
        return pending

    def begin_commit(self, state: str) -> bool:
        """Claim a pending flow before mutating supervisor-owned state.

        Returns ``False`` when cancellation or another terminal transition
        won the race. A committing flow cannot subsequently be cancelled by
        the UI; the supervisor transaction determines success or rollback.
        """
        pending = self._pending.get(state)
        if pending is None or pending.status != "exchanging":
            return False
        pending.status = "committing"
        return True

    def mark_success(self, state: str, integration_id: str) -> None:
        """Called after the supervisor's ``add`` succeeded. Caller passes
        the new integration_id so :meth:`status` can return it."""
        pending = self._pending.get(state)
        if pending is None:
            return
        if pending.status != "committing":
            return
        pending.status = "success"
        pending.integration_id = integration_id
        pending.completed_at = time.time()
        logger.info(
            "OAuth loopback flow %s succeeded → integration %s",
            state[:8] + "…", integration_id,
        )

    def mark_error(self, state: str, code: str, message: str) -> None:
        """Called when the post-fetch step (supervisor add, etc.) fails."""
        self._mark_error(state, code, message)

    # -- internals -----------------------------------------------------

    @staticmethod
    def _build_auth_blob(flow: Flow, *, fallback_scopes: list[str]) -> BrokerConnectionData:
        """Convert ``Credentials`` to the auth_blob shape the supervisor's ``add`` verb expects."""
        creds = flow.credentials
        # google-auth commonly returns a naive UTC datetime but can also
        # provide an aware value. Normalize both without changing the instant.
        expiry = creds.expiry
        if expiry is not None:
            expiry = (
                expiry.replace(tzinfo=UTC)
                if expiry.tzinfo is None
                else expiry.astimezone(UTC)
            )
        expires_at = (
            int(expiry.timestamp())
            if expiry is not None else 0
        )
        # google-auth keeps requested scopes in ``scopes`` and the token
        # endpoint's actual consent result in ``granted_scopes``. Only fall
        # back when that result is absent, never when it is explicitly empty.
        granted_scopes = getattr(creds, "granted_scopes", None)
        scopes = granted_scopes if granted_scopes is not None else (creds.scopes or fallback_scopes)
        scopes_str = scopes if isinstance(scopes, str) else " ".join(scopes)
        auth_blob = {
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "scopes": scopes_str,
            "expires_at": str(expires_at),
        }
        missing = [
            key
            for key, value in auth_blob.items()
            if not isinstance(value, str) or not value
        ]
        if missing:
            raise ValueError(
                f"token response missing string fields: {', '.join(sorted(missing))}",
            )
        return BrokerConnectionData.from_wire(auth_blob)

    def _mark_terminal(self, state: str, status: PendingStatus) -> None:
        pending = self._pending.get(state)
        if pending is None:
            return
        pending.status = status
        pending.completed_at = time.time()
        logger.info("OAuth loopback flow %s -> %s", state[:8] + "…", status)

    def _mark_error(self, state: str, code: str, message: str) -> None:
        pending = self._pending.get(state)
        if pending is None:
            return
        pending.status = "error"
        pending.error_code = code
        pending.error_message = message
        pending.completed_at = time.time()

    def _mark_error_if_status(
        self,
        state: str,
        expected: PendingStatus,
        code: str,
        message: str,
    ) -> None:
        """Record an exchange error unless cancellation already won the race."""
        pending = self._pending.get(state)
        if pending is not None and pending.status == expected:
            self._mark_error(state, code, message)

    def _expire_and_prune(self) -> None:
        """Expire abandoned flows and discard old terminal records."""
        now = time.time()
        for state, pending in self._pending.items():
            if pending.status == "pending" and now >= pending.expires_at:
                self._mark_terminal(state, "expired")

        cutoff = now - _TERMINAL_RETENTION_SECONDS
        stale = [
            state
            for state, pending in self._pending.items()
            if pending.completed_at is not None and pending.completed_at < cutoff
        ]
        for state in stale:
            del self._pending[state]


__all__ = ["OAuthIntegrationManager", "PendingOAuthIntegration"]
