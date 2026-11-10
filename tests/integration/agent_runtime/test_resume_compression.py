"""Exercise response compression across HTTP, runtime history, and persistence."""

import gzip
import json
import threading
import zlib

import pytest
from aiohttp import web
from aiohttp.compression_utils import ZLibBackendWrapper

from server._agent_runtime import AGENT_RUNTIME_KEY
from server._conversation_routes import register_conversation_routes

from ._support import reply


_RESUME_PATH = "/api/conversations/sessions/contract/resume"


@pytest.fixture
async def resume_http(harness, aiohttp_client):
    harness.profile()
    harness.provider.plan("leaf", reply("Saved answer: résumé 🧭\n" * 4000))
    await harness.run(message="Keep the full answer when reopening this conversation.")
    app = web.Application()
    app[AGENT_RUNTIME_KEY] = harness.manager
    register_conversation_routes(app)
    client = await aiohttp_client(app, auto_decompress=False, skip_auto_headers={"Accept-Encoding"})
    response = await client.post(_RESUME_PATH, headers={"Accept-Encoding": "identity"})
    assert response.status == 200
    plain = await response.read()
    assert len(plain) > 64 * 1024
    return client, plain


@pytest.mark.parametrize(
    ("accept_encoding", "expected_encoding"),
    [
        (None, None),
        ("", None),
        ("identity", None),
        ("gzip", "gzip"),
        ("deflate", "deflate"),
        ("gzip, deflate, br", "gzip"),
        ("gzip;q=0, deflate;q=1", "deflate"),
        ("gzip;q=0, deflate;q=0", None),
        ("gzip;q=0.4, identity;q=0.9", None),
        ("gzip;q=0.9, identity;q=0.4", "gzip"),
        ("*;q=0.5", "gzip"),
        ("gzip;q=0, *;q=1", "deflate"),
        ("br", None),
        ("GZIP;Q=1", "gzip"),
        ("gzip;q=invalid", None),
    ],
)
async def test_resume_http_negotiates_compression_without_changing_history(
    resume_http, accept_encoding, expected_encoding,
):
    """The transmitted encoding follows client preferences and preserves every byte."""
    client, plain = resume_http
    headers = {} if accept_encoding is None else {"Accept-Encoding": accept_encoding}
    response = await client.post(_RESUME_PATH, headers=headers)
    body = await response.read()

    assert response.status == 200
    assert response.headers.get("Content-Encoding") == expected_encoding
    assert response.headers["Vary"] == "Accept-Encoding"
    assert response.headers["Content-Type"] == "application/json; charset=utf-8"
    assert int(response.headers["Content-Length"]) == len(body)
    if expected_encoding:
        assert len(body) < len(plain) / 2
        body = gzip.decompress(body) if expected_encoding == "gzip" else zlib.decompress(body)
    assert body == plain
    assert "messages" not in json.loads(body)


@pytest.mark.parametrize("accept_encoding", ["*;q=0", "br, identity;q=0"])
async def test_resume_http_rejects_excluded_representations(resume_http, accept_encoding):
    """An explicit refusal of all supported representations gets a 406 response."""
    client, _plain = resume_http
    response = await client.post(_RESUME_PATH, headers={"Accept-Encoding": accept_encoding})
    assert response.status == 406
    assert "Content-Encoding" not in response.headers
    assert response.headers["Vary"] == "Accept-Encoding"


async def test_resume_http_combines_encoding_header_fields(resume_http):
    """Separate header fields retain exclusions when choosing the response coding."""
    client, plain = resume_http
    response = await client.post(_RESUME_PATH, headers=[
        ("Accept-Encoding", "gzip;q=0"),
        ("Accept-Encoding", "deflate"),
    ])
    assert response.status == 200
    assert response.headers["Content-Encoding"] == "deflate"
    assert zlib.decompress(await response.read()) == plain


async def test_large_resume_compression_runs_off_event_loop(resume_http, monkeypatch):
    """Real compression of a large history runs outside the HTTP event-loop thread."""
    client, plain = resume_http
    event_loop_thread = threading.get_ident()
    compression_threads = []
    original_factory = ZLibBackendWrapper.compressobj

    def observe_compressor(backend, *args, **kwargs):
        compressor = original_factory(backend, *args, **kwargs)

        class ObservedCompressor:
            def compress(self, data):
                compression_threads.append(threading.get_ident())
                return compressor.compress(data)

            def flush(self, *args, **kwargs):
                return compressor.flush(*args, **kwargs)

        return ObservedCompressor()

    monkeypatch.setattr(ZLibBackendWrapper, "compressobj", observe_compressor)
    response = await client.post(_RESUME_PATH, headers={"Accept-Encoding": "gzip"})
    assert response.status == 200
    assert gzip.decompress(await response.read()) == plain
    assert compression_threads
    assert event_loop_thread not in compression_threads
