"""Tests for the http broker's verb dispatcher.

The dispatcher is the whole broker — it parses args, attaches auth, rejects
off-host paths, decides whether to inline or spill responses. Tests use a
fake aiohttp ClientSession that records the call and returns a canned
response, because what's under test is the dispatcher, not aiohttp.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from pathlib import Path

import aiohttp
import pytest

from integrations._rpc import RpcError
from integrations.brokers.http_broker._verbs import (
    _INLINE_BODY_CAP,
    VerbDispatcher,
)
from integrations.permissions import Access, Capability


class _StubResponse:
    """Drop-in for the aiohttp response object yielded by ``request()``.

    The real type is a context manager whose body is read via
    ``.content.read(N)``. We mimic that surface and store the canned
    payload, status, and headers.
    """

    def __init__(
        self,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
        payload: bytes = b"",
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self.content = _StubContent(payload)

    async def __aenter__(self) -> _StubResponse:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _StubContent:
    """The ``.content`` attribute on a real response — supports ``read(n)``."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def read(self, n: int) -> bytes:
        return self._payload[:n]


class _StubSession:
    """Fake aiohttp ClientSession capturing the outbound call.

    Tests pre-load ``next_response`` (default: empty 200) and inspect
    ``last_call`` after dispatch to assert on method/URL/headers/body.
    """

    def __init__(self) -> None:
        self.next_response = _StubResponse()
        self.last_call: dict[str, object] | None = None
        self.raise_on_request: BaseException | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        params: object = None,
        headers: object = None,
        data: object = None,
        timeout: object = None,
        allow_redirects: bool = True,
    ) -> _StubResponse:
        self.last_call = {
            "method": method,
            "url": url,
            "params": params,
            "headers": dict(headers) if headers else {},
            "data": data,
            "allow_redirects": allow_redirects,
        }
        if self.raise_on_request is not None:
            raise self.raise_on_request
        return self.next_response


def _make_dispatcher(
    *,
    permissions: dict[Capability, Access] | None = None,
    base_url: str = "https://api.example.com",
    header_name: str = "Authorization",
    header_template: str = "Bearer {token}",
    token: str = "secret-token",  # noqa: S107
    downloads_dir: Path,
    inline_cap: int = _INLINE_BODY_CAP,
    session: _StubSession | None = None,
) -> tuple[VerbDispatcher, _StubSession]:
    sess = session or _StubSession()
    perms = permissions if permissions is not None else {Capability.HTTP: Access.READ_WRITE}
    dispatcher = VerbDispatcher(
        session=sess,  # type: ignore[arg-type]
        base_url=base_url,
        header_name=header_name,
        header_template=header_template,
        token=token,
        permissions=perms,
        downloads_dir=downloads_dir,
        inline_cap=inline_cap,
    )
    return dispatcher, sess


@pytest.mark.asyncio
async def test_unknown_verb_rejected(tmp_path: Path) -> None:
    dispatcher, _ = _make_dispatcher(downloads_dir=tmp_path)
    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch("nope", {})
    assert excinfo.value.code == "BAD_REQUEST"
    assert "unknown verb" in excinfo.value.message


@pytest.mark.asyncio
async def test_get_inlines_json_response(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    body = b'{"ok":true}'
    sess.next_response = _StubResponse(
        status=200,
        headers={"Content-Type": "application/json"},
        payload=body,
    )

    result = await dispatcher.dispatch(
        "http_request", {"method": "GET", "path": "/items"},
    )

    assert result == {
        "status": 200,
        "headers": {"Content-Type": "application/json"},
        "content_type": "application/json",
        "size": len(body),
        "body": '{"ok":true}',
        "body_path": None,
    }
    assert sess.last_call is not None
    assert sess.last_call["method"] == "GET"
    assert sess.last_call["url"] == "https://api.example.com/items"
    assert sess.last_call["allow_redirects"] is False


@pytest.mark.asyncio
async def test_read_permission_blocks_post(tmp_path: Path) -> None:
    """``http:read`` lets GET through but PERMISSION_DENIED on POST."""
    dispatcher, sess = _make_dispatcher(
        downloads_dir=tmp_path,
        permissions={Capability.HTTP: Access.READ},
    )

    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch(
            "http_request", {"method": "POST", "path": "/items"},
        )

    assert excinfo.value.code == "PERMISSION_DENIED"
    assert "http:read_write" in excinfo.value.message
    # And the session was never called — gate fires before the upstream.
    assert sess.last_call is None


@pytest.mark.asyncio
async def test_off_capability_blocks_get(tmp_path: Path) -> None:
    dispatcher, _ = _make_dispatcher(
        downloads_dir=tmp_path,
        permissions={Capability.HTTP: Access.OFF},
    )
    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch(
            "http_request", {"method": "GET", "path": "/items"},
        )
    assert excinfo.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_read_permission_allows_head_and_options(tmp_path: Path) -> None:
    """HEAD and OPTIONS are read-side methods; ``http:read`` covers them."""
    dispatcher, sess = _make_dispatcher(
        downloads_dir=tmp_path,
        permissions={Capability.HTTP: Access.READ},
    )
    sess.next_response = _StubResponse(status=204, headers={}, payload=b"")

    for method in ("HEAD", "OPTIONS"):
        result = await dispatcher.dispatch(
            "http_request", {"method": method, "path": "/x"},
        )
        assert result["status"] == 204


@pytest.mark.asyncio
async def test_method_case_normalized(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(status=200, headers={"Content-Type": "text/plain"}, payload=b"ok")
    await dispatcher.dispatch("http_request", {"method": "get", "path": "/"})
    assert sess.last_call is not None
    assert sess.last_call["method"] == "GET"


@pytest.mark.asyncio
async def test_unknown_method_rejected(tmp_path: Path) -> None:
    dispatcher, _ = _make_dispatcher(downloads_dir=tmp_path)
    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch(
            "http_request", {"method": "TRACE", "path": "/"},
        )
    assert excinfo.value.code == "BAD_REQUEST"
    assert "TRACE" in excinfo.value.message


@pytest.mark.asyncio
async def test_path_resolving_to_different_host_rejected(tmp_path: Path) -> None:
    """A protocol-relative path that lands on a different host is the
    main exfil shape this broker exists to prevent."""
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch(
            "http_request", {"method": "GET", "path": "//attacker.com/steal"},
        )
    assert excinfo.value.code == "BAD_REQUEST"
    assert "off the integration's base URL" in excinfo.value.message
    assert sess.last_call is None


@pytest.mark.asyncio
async def test_absolute_url_to_different_host_rejected(tmp_path: Path) -> None:
    dispatcher, _ = _make_dispatcher(downloads_dir=tmp_path)
    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch(
            "http_request",
            {"method": "GET", "path": "https://attacker.com/steal"},
        )
    assert excinfo.value.code == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_scheme_downgrade_rejected(tmp_path: Path) -> None:
    """An ``http://`` path against an ``https://`` base would leak the token in cleartext."""
    dispatcher, _ = _make_dispatcher(
        downloads_dir=tmp_path, base_url="https://api.example.com",
    )
    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch(
            "http_request",
            {"method": "GET", "path": "http://api.example.com/x"},
        )
    assert excinfo.value.code == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_relative_path_resolves_against_base(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(
        downloads_dir=tmp_path, base_url="https://api.example.com/v1",
    )
    sess.next_response = _StubResponse(
        status=200,
        headers={"Content-Type": "text/plain"},
        payload=b"ok",
    )
    await dispatcher.dispatch(
        "http_request", {"method": "GET", "path": "users/42"},
    )
    # urljoin against trailing-slash base keeps the v1 prefix.
    assert sess.last_call is not None
    assert sess.last_call["url"] == "https://api.example.com/v1/users/42"


@pytest.mark.asyncio
async def test_auth_header_attached_and_user_authorization_stripped(
    tmp_path: Path,
) -> None:
    """The integration's auth header always wins; an agent-supplied
    Authorization must not pass through."""
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(
        status=200, headers={"Content-Type": "text/plain"}, payload=b"x",
    )

    await dispatcher.dispatch(
        "http_request",
        {
            "method": "GET",
            "path": "/x",
            "headers": {
                "Authorization": "Bearer attacker-token",
                "Cookie": "session=evil",
                "User-Agent": "my-agent",
            },
        },
    )

    assert sess.last_call is not None
    headers = sess.last_call["headers"]
    assert headers["Authorization"] == "Bearer secret-token"
    assert "Cookie" not in headers
    assert headers["User-Agent"] == "my-agent"


@pytest.mark.asyncio
async def test_custom_header_name_and_template(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(
        downloads_dir=tmp_path,
        header_name="X-Api-Key",
        header_template="{token}",
        token="raw-key",  # noqa: S106
    )
    sess.next_response = _StubResponse(
        status=200, headers={"Content-Type": "text/plain"}, payload=b"x",
    )
    await dispatcher.dispatch(
        "http_request", {"method": "GET", "path": "/x"},
    )
    assert sess.last_call is not None
    assert sess.last_call["headers"]["X-Api-Key"] == "raw-key"


@pytest.mark.asyncio
async def test_user_x_api_key_stripped(tmp_path: Path) -> None:
    """``X-Api-Key`` is in the forbidden list too — an alternate auth header
    name some APIs use, also off-limits to agent override."""
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(
        status=200, headers={"Content-Type": "text/plain"}, payload=b"x",
    )
    await dispatcher.dispatch(
        "http_request",
        {
            "method": "GET",
            "path": "/x",
            "headers": {"X-Api-Key": "attacker"},
        },
    )
    assert sess.last_call is not None
    assert sess.last_call["headers"].get("X-Api-Key") is None or sess.last_call["headers"]["X-Api-Key"] != "attacker"


@pytest.mark.asyncio
async def test_query_dict_with_list_repeats_keys(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(
        status=200, headers={"Content-Type": "text/plain"}, payload=b"x",
    )
    await dispatcher.dispatch(
        "http_request",
        {
            "method": "GET",
            "path": "/x",
            "query": {"tag": ["a", "b"], "q": "hi"},
        },
    )
    assert sess.last_call is not None
    assert sess.last_call["params"] == [("tag", "a"), ("tag", "b"), ("q", "hi")]


@pytest.mark.asyncio
async def test_body_dict_json_encoded(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(
        status=201, headers={"Content-Type": "application/json"}, payload=b"{}",
    )

    await dispatcher.dispatch(
        "http_request",
        {
            "method": "POST",
            "path": "/items",
            "body": {"name": "x", "n": 1},
        },
    )

    assert sess.last_call is not None
    assert json.loads(sess.last_call["data"]) == {"name": "x", "n": 1}
    assert sess.last_call["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_body_string_text_plain(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(status=200, headers={"Content-Type": "text/plain"}, payload=b"ok")

    await dispatcher.dispatch(
        "http_request",
        {"method": "POST", "path": "/x", "body": "hello"},
    )
    assert sess.last_call is not None
    assert sess.last_call["data"] == b"hello"
    assert sess.last_call["headers"]["Content-Type"] == "text/plain; charset=utf-8"


@pytest.mark.asyncio
async def test_user_content_type_overrides_body_default(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(status=200, headers={"Content-Type": "text/plain"}, payload=b"x")

    await dispatcher.dispatch(
        "http_request",
        {
            "method": "POST",
            "path": "/x",
            "body": {"a": 1},
            "headers": {"Content-Type": "application/merge-patch+json"},
        },
    )
    assert sess.last_call is not None
    assert sess.last_call["headers"]["Content-Type"] == "application/merge-patch+json"


@pytest.mark.asyncio
async def test_body_b64_decoded_with_octet_stream_default(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(status=200, headers={"Content-Type": "text/plain"}, payload=b"x")

    payload = b"\x89PNG fake"
    await dispatcher.dispatch(
        "http_request",
        {
            "method": "PUT",
            "path": "/upload",
            "body_b64": base64.b64encode(payload).decode("ascii"),
        },
    )
    assert sess.last_call is not None
    assert sess.last_call["data"] == payload
    assert sess.last_call["headers"]["Content-Type"] == "application/octet-stream"


@pytest.mark.asyncio
async def test_body_b64_with_explicit_content_type(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(status=200, headers={"Content-Type": "text/plain"}, payload=b"x")

    await dispatcher.dispatch(
        "http_request",
        {
            "method": "PUT",
            "path": "/upload",
            "body_b64": base64.b64encode(b"hello").decode("ascii"),
            "body_content_type": "image/png",
        },
    )
    assert sess.last_call is not None
    assert sess.last_call["headers"]["Content-Type"] == "image/png"


@pytest.mark.asyncio
async def test_body_and_body_b64_mutually_exclusive(tmp_path: Path) -> None:
    dispatcher, _ = _make_dispatcher(downloads_dir=tmp_path)
    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch(
            "http_request",
            {
                "method": "POST",
                "path": "/x",
                "body": "hi",
                "body_b64": base64.b64encode(b"y").decode("ascii"),
            },
        )
    assert excinfo.value.code == "BAD_REQUEST"
    assert "mutually exclusive" in excinfo.value.message


@pytest.mark.asyncio
async def test_invalid_base64_rejected(tmp_path: Path) -> None:
    dispatcher, _ = _make_dispatcher(downloads_dir=tmp_path)
    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch(
            "http_request",
            {"method": "POST", "path": "/x", "body_b64": "!!!not-b64!!!"},
        )
    assert excinfo.value.code == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_binary_response_spills_to_disk(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    payload = b"\x89PNG\r\n\x1a\n" + b"x" * 100
    sess.next_response = _StubResponse(
        status=200, headers={"Content-Type": "image/png"}, payload=payload,
    )

    result = await dispatcher.dispatch(
        "http_request", {"method": "GET", "path": "/avatar.png"},
    )

    assert result["body"] is None
    assert result["body_path"] is not None
    assert result["size"] == len(payload)
    assert result["content_type"] == "image/png"

    written = Path(result["body_path"])
    assert written.parent == tmp_path
    assert written.read_bytes() == payload
    assert written.suffix == ".png"


@pytest.mark.asyncio
async def test_large_json_response_spills(tmp_path: Path) -> None:
    """A JSON body bigger than the inline cap spills even though the type
    would otherwise inline."""
    big = b'{"x":"' + b"a" * (_INLINE_BODY_CAP + 1) + b'"}'
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(
        status=200, headers={"Content-Type": "application/json"}, payload=big,
    )

    result = await dispatcher.dispatch(
        "http_request", {"method": "GET", "path": "/big"},
    )

    assert result["body"] is None
    assert result["body_path"] is not None
    assert Path(result["body_path"]).read_bytes() == big


@pytest.mark.asyncio
async def test_text_response_inlined(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(
        status=200,
        headers={"Content-Type": "text/plain; charset=utf-8"},
        payload=b"hello world",
    )
    result = await dispatcher.dispatch(
        "http_request", {"method": "GET", "path": "/hi"},
    )
    assert result["body"] == "hello world"
    assert result["body_path"] is None


@pytest.mark.asyncio
async def test_redirect_returned_not_followed(tmp_path: Path) -> None:
    """3xx responses come back to the agent with the Location header in
    place — the broker never chases them, so a redirect target on a
    different host cannot leak the token."""
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(
        status=302,
        headers={
            "Content-Type": "text/html",
            "Location": "https://api.example.com/v2/items",
        },
        payload=b"",
    )

    result = await dispatcher.dispatch(
        "http_request", {"method": "GET", "path": "/items"},
    )

    assert result["status"] == 302
    assert result["headers"]["Location"] == "https://api.example.com/v2/items"
    assert sess.last_call is not None
    assert sess.last_call["allow_redirects"] is False


@pytest.mark.asyncio
async def test_response_set_cookie_stripped(tmp_path: Path) -> None:
    """Set-Cookie is dropped from the echoed response headers."""
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.next_response = _StubResponse(
        status=200,
        headers={"Content-Type": "text/plain", "Set-Cookie": "x=y"},
        payload=b"ok",
    )
    result = await dispatcher.dispatch(
        "http_request", {"method": "GET", "path": "/x"},
    )
    assert "Set-Cookie" not in result["headers"]
    assert "set-cookie" not in result["headers"]


@pytest.mark.asyncio
async def test_aiohttp_client_error_maps_to_upstream_error(tmp_path: Path) -> None:
    dispatcher, sess = _make_dispatcher(downloads_dir=tmp_path)
    sess.raise_on_request = aiohttp.ClientError("boom")
    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch(
            "http_request", {"method": "GET", "path": "/x"},
        )
    assert excinfo.value.code == "UPSTREAM_ERROR"


@pytest.mark.asyncio
async def test_missing_method_rejected(tmp_path: Path) -> None:
    dispatcher, _ = _make_dispatcher(downloads_dir=tmp_path)
    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch("http_request", {"path": "/x"})
    assert excinfo.value.code == "BAD_REQUEST"
    assert "'method'" in excinfo.value.message


@pytest.mark.asyncio
async def test_missing_path_rejected(tmp_path: Path) -> None:
    dispatcher, _ = _make_dispatcher(downloads_dir=tmp_path)
    with pytest.raises(RpcError) as excinfo:
        await dispatcher.dispatch("http_request", {"method": "GET"})
    assert excinfo.value.code == "BAD_REQUEST"
    assert "'path'" in excinfo.value.message


@pytest.mark.asyncio
async def test_bad_base_url_rejected_at_construction(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="BASE_URL is not absolute"):
        VerbDispatcher(
            session=_StubSession(),  # type: ignore[arg-type]
            base_url="just-a-string",
            header_name="Authorization",
            header_template="Bearer {token}",
            token="x",  # noqa: S106
            permissions={Capability.HTTP: Access.READ_WRITE},
            downloads_dir=tmp_path,
        )
