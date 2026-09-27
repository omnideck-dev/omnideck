"""Private supervisor-to-child control over inherited process pipes.

This protocol is deliberately absent from the public broker RPC socket. Stdin
belongs to the spawning supervisor; stdout carries READY followed by framed
acknowledgements. Broker logs must stay on stderr.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from brokering._ready import print_ready
from brokering._rpc import encode_frame, read_frame

GRANT_UPDATE_TIMEOUT = 5.0
CREDENTIAL_UPDATE_TIMEOUT = 30.0


@dataclass
class PreparedBrokerSession:
    """Lifecycle callbacks for a prepared provider-specific broker session.

    The control protocol needs no knowledge of the session's contents. Its
    pending-update ID ensures exactly one activate/discard decision; startup
    callers invoke activate directly. This object does not enforce single use.
    """

    activate: Callable[[], Awaitable[None]]
    discard: Callable[[], Awaitable[None]]


class CredentialRejected(Exception):
    """Definite preparation rejection; the active broker session is unchanged."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


async def credential_command(
    proc: asyncio.subprocess.Process,
    command: str,
    update_id: str,
    credentials: dict[str, str] | None = None,
) -> None:
    """Send one serialized control command; never echo secrets in replies/errors.

    Only a well-formed prepare rejection guarantees no change. Other failures
    are ambiguous and require stopping the child before recovery from disk.
    """
    if proc.stdin is None or proc.stdout is None or proc.returncode is not None:
        raise ConnectionError("broker credential control unavailable")
    request: dict[str, Any] = {"command": command, "id": update_id}
    if credentials is not None:
        request["credentials"] = credentials
    async with asyncio.timeout(CREDENTIAL_UPDATE_TIMEOUT):
        proc.stdin.write(encode_frame(request))
        await proc.stdin.drain()
        response = await read_frame(proc.stdout)
        expected = {"command": command, "id": update_id, "status": "ok"}
        if response == expected:
            return
        if command == "prepare_credentials":
            for code in ("AUTH", "BAD_REQUEST", "UPSTREAM"):
                if response == {**expected, "status": "rejected", "code": code}:
                    raise CredentialRejected(code)
        raise ConnectionError("invalid broker credential acknowledgement")


async def update_broker_grants(proc: asyncio.subprocess.Process, grants: frozenset[str]) -> None:
    """Wait for the running child to install exactly these grants.

    The manager serializes connection mutations. A timeout or invalid reply is
    ambiguous: the caller must stop this child, not retry on the same stream.
    """
    if proc.stdin is None or proc.stdout is None or proc.returncode is not None:
        raise ConnectionError("broker grant control unavailable")
    expected = sorted(grants)
    async with asyncio.timeout(GRANT_UPDATE_TIMEOUT):
        proc.stdin.write(encode_frame({"grants": expected}))
        await proc.stdin.drain()
        response = await read_frame(proc.stdout)
        if response != {"grants": expected}:
            raise ConnectionError("invalid broker grant acknowledgement")


class BrokerControl:
    """One pending session replacement per child, on its private pipes only.

    Credential commands prepare/activate/discard a session via callbacks. The
    broker supplies those callbacks; this layer does not authenticate providers
    or persist credentials. Wire command names still describe credential edits.
    """

    def __init__(
        self,
        replace_grants: Callable[[frozenset[str]], None] | None,
        prepare_session: Callable[[dict[str, str]], Awaitable[PreparedBrokerSession]],
    ) -> None:
        self._replace_grants = replace_grants
        self._prepare_session = prepare_session
        self._pending: tuple[str, PreparedBrokerSession] | None = None

    async def handle(self, frame: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(frame, dict):
            raise ValueError("control message must be an object")
        if set(frame) == {"grants"}:
            grants = frame["grants"]
            if self._pending is not None or self._replace_grants is None:
                raise ValueError("grant update unavailable")
            if not isinstance(grants, list) or any(not isinstance(item, str) for item in grants):
                raise ValueError("grant control requires operation IDs")
            snapshot = frozenset(grants)
            self._replace_grants(snapshot)
            return {"grants": sorted(snapshot)}
        command, update_id = frame.get("command"), frame.get("id")
        if not isinstance(update_id, str) or not update_id:
            raise ValueError("credential control requires an update ID")
        reply = {"command": command, "id": update_id, "status": "ok"}
        if command == "prepare_credentials":
            if self._pending is not None:
                raise ValueError("credential update already pending")
            connection_fields = frame.get("credentials")
            if not isinstance(connection_fields, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in connection_fields.items()
            ):
                raise ValueError("credentials must be string fields")
            try:
                candidate = await self._prepare_session(connection_fields)
            except CredentialRejected as exc:
                return {**reply, "status": "rejected", "code": exc.code}
            except (KeyError, ValueError):
                return {**reply, "status": "rejected", "code": "BAD_REQUEST"}
            except Exception:
                # Upstream errors can contain credentials. Never relay their text.
                return {**reply, "status": "rejected", "code": "UPSTREAM"}
            self._pending = (update_id, candidate)
        elif command in {"activate_credentials", "discard_credentials"}:
            if self._pending is None or self._pending[0] != update_id:
                raise ValueError("no matching prepared credentials")
            _, candidate = self._pending
            self._pending = None
            if command == "activate_credentials":
                await candidate.activate()
            else:
                await candidate.discard()
        else:
            raise ValueError("unknown control command")
        return reply

    async def close(self) -> None:
        if self._replace_grants is not None:
            self._replace_grants(frozenset())
        if self._pending is not None:
            _, candidate = self._pending
            self._pending = None
            await candidate.discard()

    async def receive(self, reader: asyncio.StreamReader) -> None:
        while True:
            reply = await self.handle(await read_frame(reader))
            sys.stdout.buffer.write(encode_frame(reply))
            sys.stdout.buffer.flush()


async def run_with_control(
    serve: Awaitable[None],
    control: BrokerControl,
) -> None:
    """Serve operations and private control; loss of the parent fails closed."""
    reader = asyncio.StreamReader()
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer,
    )
    tasks = []
    try:
        tasks = [asyncio.ensure_future(serve), asyncio.create_task(control.receive(reader))]
        print_ready()
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            await task
    finally:
        transport.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await control.close()
