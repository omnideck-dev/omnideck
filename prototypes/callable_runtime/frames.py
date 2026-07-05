"""Length-prefixed JSON framing over a local socket.

Same wire shape the integrations broker RPC uses: a 4-byte big-endian length
prefix followed by that many bytes of UTF-8 JSON. The runner uses the blocking
helpers; the parent uses the asyncio helpers on a non-blocking socket.
"""

from __future__ import annotations

import asyncio
import json
import socket
from typing import Any

_LEN = 4
_MAX = 8 * 1024 * 1024  # generous cap for the prototype


def encode(obj: dict[str, Any]) -> bytes:
    body = json.dumps(obj).encode("utf-8")
    if len(body) > _MAX:
        raise ValueError("frame exceeds maximum size")
    return len(body).to_bytes(_LEN, "big") + body


# --- blocking helpers (runner side) ---


def write_frame(sock: socket.socket, obj: dict[str, Any]) -> None:
    sock.sendall(encode(obj))


def read_frame(sock: socket.socket) -> dict[str, Any]:
    header = _recv_exactly(sock, _LEN)
    length = int.from_bytes(header, "big")
    body = _recv_exactly(sock, length)
    return json.loads(body.decode("utf-8"))


def _recv_exactly(sock: socket.socket, n: int) -> bytes:
    chunks = []
    got = 0
    while got < n:
        chunk = sock.recv(n - got)
        if not chunk:
            raise ConnectionError("socket closed mid-frame")
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


# --- asyncio helpers (parent side) ---


async def awrite_frame(
    loop: asyncio.AbstractEventLoop, sock: socket.socket, obj: dict[str, Any]
) -> None:
    await loop.sock_sendall(sock, encode(obj))


async def aread_frame(
    loop: asyncio.AbstractEventLoop, sock: socket.socket
) -> dict[str, Any]:
    header = await _asock_recv_exactly(loop, sock, _LEN)
    length = int.from_bytes(header, "big")
    body = await _asock_recv_exactly(loop, sock, length)
    return json.loads(body.decode("utf-8"))


async def _asock_recv_exactly(
    loop: asyncio.AbstractEventLoop, sock: socket.socket, n: int
) -> bytes:
    chunks = []
    got = 0
    while got < n:
        chunk = await loop.sock_recv(sock, n - got)
        if not chunk:
            raise ConnectionError("socket closed mid-frame")
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)
