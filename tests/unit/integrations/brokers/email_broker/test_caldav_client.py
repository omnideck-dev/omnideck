"""Tests for ``brokers/email_broker/_caldav_client.py`` — CalDAV client logic.

Focuses on the two defects that caused ``list_events`` to time out on iCloud:

1. **Missing timeout on DAVClient** — caldav delegates to niquests, which
   enforces a 30-second default read timeout when ``timeout`` is ``None``.
   That is too short for iCloud's CalDAV REPORT (event search + expansion).
   The fix passes an explicit ``timeout=120`` to ``DAVClient``.

2. **Timeout treated as stale connection** — ``requests.exceptions.Timeout``
   was in ``_STALE_CONN_ERRORS``, so a slow REPORT triggered a pointless
   reconnect+retry, doubling the wait before the error surfaced. The fix
   removes ``Timeout`` from that tuple.

Tests use stubs/mocks — no real HTTP or CalDAV server needed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
import requests.exceptions

from integrations.brokers.email_broker._caldav_client import (
    CalDavClient,
    _STALE_CONN_ERRORS,
)


# ── _STALE_CONN_ERRORS ─────────────────────────────────────────────────────


class TestStaleConnErrors:
    """``_STALE_CONN_ERRORS`` should include connection-level errors but
    NOT timeouts. A timeout means the server is slow, not that the
    connection is dead — reconnecting wastes time and doubles the wait."""

    def test_includes_connection_error(self) -> None:
        """``ConnectionError`` (RST, broken pipe, idle close) should trigger
        a reconnect+retry — the connection is genuinely gone."""
        assert requests.exceptions.ConnectionError in _STALE_CONN_ERRORS

    def test_excludes_timeout(self) -> None:
        """``Timeout`` must NOT be in ``_STALE_CONN_ERRORS``. A timeout
        means the server is slow to respond (e.g. iCloud's CalDAV REPORT
        with event expansion), not that the connection is stale. Treating
        it as stale causes a pointless reconnect and doubles the wait."""
        assert requests.exceptions.Timeout not in _STALE_CONN_ERRORS

    def test_includes_protocol_error(self) -> None:
        """``ProtocolError`` (urllib3) indicates a broken HTTP stream —
        reconnecting is the right move."""
        import urllib3.exceptions

        assert urllib3.exceptions.ProtocolError in _STALE_CONN_ERRORS


# ── _blocking_connect passes explicit timeout ─────────────────────────────


class TestBlockingConnectTimeout:
    """``_blocking_connect`` must pass an explicit ``timeout`` to
    ``DAVClient`` so niquests doesn't fall back to its 30-second default
    for read operations (PROPFIND, REPORT)."""

    @patch("integrations.brokers.email_broker._caldav_client.caldav")
    def test_davclient_receives_explicit_timeout(self, mock_caldav: MagicMock) -> None:
        """The ``DAVClient`` constructor must be called with a ``timeout``
        keyword argument that is greater than niquests' 30-second default.
        Without it, iCloud REPORT responses that take 30–60 seconds time out."""
        mock_client = MagicMock()
        mock_principal = MagicMock()
        mock_caldav.DAVClient.return_value = mock_client
        mock_client.principal.return_value = mock_principal

        client = CalDavClient(
            url="https://caldav.icloud.com",
            username="user",
            password="pass",
        )
        client._blocking_connect()

        # DAVClient must have been called with a timeout kwarg.
        call_kwargs = mock_caldav.DAVClient.call_args
        assert "timeout" in call_kwargs.kwargs, (
            "DAVClient must receive an explicit timeout= parameter; "
            "without it niquests defaults to 30s for reads, which is too "
            "short for iCloud's CalDAV REPORT."
        )
        timeout_value = call_kwargs.kwargs["timeout"]
        assert isinstance(timeout_value, int)
        assert timeout_value > 30, (
            f"timeout={timeout_value} must be greater than niquests' "
            "30-second default read timeout to allow slow REPORT responses."
        )

    @patch("integrations.brokers.email_broker._caldav_client.caldav")
    def test_davclient_timeout_is_120(self, mock_caldav: MagicMock) -> None:
        """The specific timeout value should be 120 seconds — generous
        enough for iCloud's slowest REPORT responses while still bounding
        the wait so a truly hung server doesn't block indefinitely."""
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value = mock_client
        mock_client.principal.return_value = MagicMock()

        client = CalDavClient(
            url="https://caldav.icloud.com",
            username="user",
            password="pass",
        )
        client._blocking_connect()

        assert mock_caldav.DAVClient.call_args.kwargs["timeout"] == 120


# ── _with_reconnect does NOT retry on timeout ──────────────────────────────


class TestWithReconnectTimeout:
    """``_with_reconnect`` should NOT catch ``requests.exceptions.Timeout``
    and retry. A timeout means the server is slow — reconnecting doesn't
    help and doubles the wait time before the error surfaces."""

    @pytest.mark.asyncio
    async def test_timeout_propagates_without_reconnect(self) -> None:
        """When the operation raises ``Timeout``, ``_with_reconnect`` must
        let it propagate immediately — no reconnect, no retry. Previously
        the timeout was caught as a stale-connection error, causing a
        reconnect and a second 30-second wait before the error surfaced."""
        client = CalDavClient(
            url="https://caldav.icloud.com",
            username="user",
            password="pass",
        )
        # Simulate a connected client.
        client._client = MagicMock()
        client._principal = MagicMock()

        call_count = 0

        def _op(_client: object, _principal: object) -> object:
            nonlocal call_count
            call_count += 1
            raise requests.exceptions.Timeout("Read timed out")

        with pytest.raises(requests.exceptions.Timeout):
            await asyncio.to_thread(client._with_reconnect, _op)

        # The op should have been called exactly once — no retry.
        assert call_count == 1, (
            "Timeout should propagate immediately without triggering a "
            "reconnect+retry. The op was called "
            f"{call_count} times (expected 1)."
        )

    @pytest.mark.asyncio
    async def test_connection_error_triggers_reconnect_and_retry(self) -> None:
        """``ConnectionError`` (genuinely stale connection) should still
        trigger a reconnect and single retry — that behavior is unchanged."""
        client = CalDavClient(
            url="https://caldav.icloud.com",
            username="user",
            password="pass",
        )
        client._client = MagicMock()
        client._principal = MagicMock()

        call_count = 0

        def _op(_client: object, _principal: object) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise requests.exceptions.ConnectionError("Connection reset")
            return "success"

        with patch.object(client, "_blocking_connect") as mock_reconnect:
            mock_reconnect.return_value = (MagicMock(), MagicMock())
            result = await asyncio.to_thread(client._with_reconnect, _op)

        assert result == "success"
        assert call_count == 2, "Op should be called twice (initial + retry)"
        mock_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connection_error_retry_failure_propagates(self) -> None:
        """If the retry after a ``ConnectionError`` also fails, the second
        error must propagate — ``_with_reconnect`` retries only once."""
        client = CalDavClient(
            url="https://caldav.icloud.com",
            username="user",
            password="pass",
        )
        client._client = MagicMock()
        client._principal = MagicMock()

        def _op(_client: object, _principal: object) -> object:
            raise requests.exceptions.ConnectionError("still broken")

        with patch.object(client, "_blocking_connect") as mock_reconnect:
            mock_reconnect.return_value = (MagicMock(), MagicMock())
            with pytest.raises(requests.exceptions.ConnectionError):
                await asyncio.to_thread(client._with_reconnect, _op)

        # Reconnect called once (for the first ConnectionError).
        mock_reconnect.assert_called_once()