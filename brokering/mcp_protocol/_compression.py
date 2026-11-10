"""Streaming HTTP decompression with a bound before allocating decoded output."""

import asyncio
import zlib
from collections.abc import AsyncIterator

import httpx2

from ._errors import MCPFailure, request_failure

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_OUTPUT_CHUNK_BYTES = 64 * 1024


class DecompressedStream(httpx2.AsyncByteStream):
    """Decode a bounded raw stream, including concatenated gzip members.

    HTTP deflate uses the zlib wrapper. Unsupported encodings are rejected by
    the transport rather than passed to HTTPX's unbounded content decoders.
    """

    def __init__(self, stream: httpx2.AsyncByteStream, encoding: str) -> None:
        self._stream = stream
        self._gzip = encoding == "gzip"

    async def __aiter__(self) -> AsyncIterator[bytes]:
        window = zlib.MAX_WBITS | 16 if self._gzip else zlib.MAX_WBITS
        decoder = zlib.decompressobj(window)
        total = 0
        try:
            async for incoming in self._stream:
                while incoming:
                    if decoder.eof:
                        if not self._gzip:
                            raise httpx2.StreamError("Invalid compressed MCP response.")
                        decoder = zlib.decompressobj(window)
                    # One extra byte detects overflow without allocating the
                    # full expansion of an attacker-controlled compressed chunk.
                    output = decoder.decompress(incoming, min(_OUTPUT_CHUNK_BYTES, MAX_RESPONSE_BYTES - total + 1))
                    total += len(output)
                    if total > MAX_RESPONSE_BYTES:
                        raise httpx2.StreamError(str(request_failure(MCPFailure.RESPONSE_SIZE)))
                    incoming = decoder.unused_data if decoder.eof else decoder.unconsumed_tail
                    if output:
                        yield output
                    # Decompression is synchronous; yield between bounded steps
                    # so request deadlines and cancellation can be delivered.
                    await asyncio.sleep(0)
            if not decoder.eof:
                raise httpx2.StreamError("Incomplete compressed MCP response.")
        except zlib.error as exc:
            raise httpx2.StreamError("Invalid compressed MCP response.") from exc

    async def aclose(self) -> None:
        await self._stream.aclose()
