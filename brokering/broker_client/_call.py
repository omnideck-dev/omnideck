"""The ``call()`` entry point — how app-server code invokes integration operations.

Two RPC hops in one call:

1. Resolve: ask the supervisor's ``app.sock`` for the broker's UDS path given
   an integration id.
2. Invoke: send the canonical operation ID in the broker RPC's ``verb`` field.

Each hop uses the same length-prefixed JSON framing the supervisor and
brokers serve. Errors from either hop are mapped to the exception hierarchy
in ``_errors.py``.

The client intentionally resolves on every invocation and uses one UDS
connection per hop. The supervisor's runtime state can change asynchronously
(credential failure, crash recovery, removal), so avoiding a socket cache keeps
the resolve response authoritative and prevents calls through stale paths.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from brokering._rpc import RpcError, read_frame, write_frame
from brokering.broker_client._errors import (
    IntegrationAuthFailed,
    IntegrationError,
    IntegrationNotConnected,
    IntegrationPermissionDenied,
)


async def call(
    connection_id: str,
    operation_id: str,
    args: dict[str, Any],
    *,
    app_sock_path: Path | str,
) -> Any:
    """Invoke ``operation_id`` on the broker for ``connection_id``.

    Args:
        connection_id: The integration the tool handler is operating on
            (e.g. ``"gmail_personal"``).
        operation_id: Canonical operation ID (e.g. ``"email.mailboxes.list"``).
        args: Arguments for the operation; passed through verbatim to the broker.
        app_sock_path: Path to the supervisor's ``app.sock``. Required —
            the caller knows where it lives (env var in production, fixture
            in tests).

    Returns:
        Whatever the broker returned in its ``result`` field. The shape
        depends on the verb.

    Raises:
        IntegrationNotConnected: supervisor doesn't know about this integration.
        IntegrationAuthFailed: broker returned ``AUTH``.
        IntegrationPermissionDenied: broker returned ``PERMISSION_DENIED``.
        IntegrationError: any other protocol-level or broker-side failure.
    """
    # --- Hop 1: resolve connection_id -> broker socket via the supervisor.
    resolve_response = await _rpc_one_shot(
        app_sock_path,
        {"id": 1, "verb": "resolve", "args": {"id": connection_id}},
    )
    if "error" in resolve_response:
        error = resolve_response["error"]
        code = error.get("code", "")
        message = error.get("message", "")
        if code == "NOT_FOUND":
            raise IntegrationNotConnected(
                f"integration {connection_id!r}: {message or 'not registered'}",
            )
        if code == "AUTH":
            raise IntegrationAuthFailed(
                f"integration {connection_id!r}: {message or 'credentials rejected'}",
            )
        if code == "UNAVAILABLE":
            raise IntegrationError(
                f"integration {connection_id!r}: {message or 'not running'}",
            )
        # The supervisor raised something else — treat as a generic integration
        # error; callers can special-case later if we start growing varieties.
        raise IntegrationError(
            f"resolve for {connection_id!r} failed: {code}: {message}",
        )

    broker_socket = Path(resolve_response["result"]["socket"])

    # --- Hop 2: call the broker directly.
    broker_response = await _rpc_one_shot(
        broker_socket,
        {"id": 1, "verb": operation_id, "args": args},
    )
    if "error" in broker_response:
        error = broker_response["error"]
        code = error.get("code", "")
        message = error.get("message", "")
        if code == "AUTH":
            raise IntegrationAuthFailed(f"{connection_id} {operation_id}: {message}")
        if code == "PERMISSION_DENIED":
            raise IntegrationPermissionDenied(f"{connection_id} {operation_id}: {message}")
        raise IntegrationError(
            f"{connection_id} {operation_id} -> {code}: {message}",
        )

    return broker_response["result"]


async def _rpc_one_shot(
    socket_path: Path | str, frame: dict[str, Any],
) -> dict[str, Any]:
    """Open a UDS, send one frame, read one frame, close.

    Wraps the framing helpers in ``brokering._rpc`` so the two hops above
    aren't repeating the same 8 lines of connection plumbing.
    """
    try:
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
    except OSError as exc:
        raise IntegrationError(
            f"could not connect to integration service at {socket_path}: {exc}",
        ) from exc
    try:
        await write_frame(writer, frame)
        try:
            return await read_frame(reader)
        except RpcError as exc:
            # A malformed response from the broker / supervisor is a protocol
            # bug on their side; surface as a generic error rather than letting
            # an RpcError (which is meant for server-side use) bubble into
            # caller code.
            raise IntegrationError(
                f"malformed response from {socket_path}: {exc.code}: {exc.message}",
            ) from exc
    finally:
        writer.close()
        await writer.wait_closed()
