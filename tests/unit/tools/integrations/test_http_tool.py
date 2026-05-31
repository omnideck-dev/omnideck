"""Unit tests for the http_request agent tool.

Same pattern as ``test_drive_tools.py``: stub ``broker_client.call`` to
return canned shapes (or raise) and assert on the resulting string.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from integrations import broker_client
from tools.integrations.http.request import build_http_request_tool, http_request


def _patch_call(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: Any = None,
    exc: Exception | None = None,
) -> dict[str, Any]:
    """Patch broker_client.call, capturing the args dict it receives."""
    captured: dict[str, Any] = {}

    async def _fake(
        integration_id: str, verb: str, args: dict, *, app_sock_path: str,
    ) -> Any:
        captured["integration_id"] = integration_id
        captured["verb"] = verb
        captured["args"] = args
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(broker_client, "call", _fake)
    return captured


@pytest.mark.asyncio
async def test_inline_json_response_formatted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_call(
        monkeypatch,
        result={
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "content_type": "application/json",
            "size": 11,
            "body": '{"ok":true}',
            "body_path": None,
        },
    )

    out = await http_request("linear", "GET", "/issues")
    assert out.startswith("200 (11 bytes, content-type: application/json)")
    assert '{"ok":true}' in out


@pytest.mark.asyncio
async def test_spilled_response_reports_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_call(
        monkeypatch,
        result={
            "status": 200,
            "headers": {"Content-Type": "image/png"},
            "content_type": "image/png",
            "size": 4096,
            "body": None,
            "body_path": "/home/computron/downloads/http_linear_abc.png",
        },
    )

    out = await http_request("linear", "GET", "/avatar.png")
    assert "4096 bytes" in out
    assert "image/png" in out
    assert "body written to /home/computron/downloads/http_linear_abc.png" in out


@pytest.mark.asyncio
async def test_redirect_surfaces_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_call(
        monkeypatch,
        result={
            "status": 302,
            "headers": {"Content-Type": "text/html", "Location": "/v2/issues"},
            "content_type": "text/html",
            "size": 0,
            "body": "",
            "body_path": None,
        },
    )
    out = await http_request("linear", "GET", "/issues")
    assert "302" in out
    assert "location: /v2/issues" in out


@pytest.mark.asyncio
async def test_method_and_path_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_call(
        monkeypatch,
        result={
            "status": 204, "headers": {}, "content_type": "",
            "size": 0, "body": "", "body_path": None,
        },
    )
    await http_request("linear", "delete", "/issues/42")
    assert captured["verb"] == "http_request"
    assert captured["integration_id"] == "linear"
    assert captured["args"]["method"] == "delete"
    assert captured["args"]["path"] == "/issues/42"


@pytest.mark.asyncio
async def test_query_and_headers_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_call(
        monkeypatch,
        result={
            "status": 200, "headers": {}, "content_type": "text/plain",
            "size": 2, "body": "ok", "body_path": None,
        },
    )
    await http_request(
        "linear", "GET", "/issues",
        query={"tag": ["a", "b"]},
        headers={"X-Trace-Id": "abc"},
    )
    assert captured["args"]["query"] == {"tag": ["a", "b"]}
    assert captured["args"]["headers"] == {"X-Trace-Id": "abc"}


@pytest.mark.asyncio
async def test_body_dict_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_call(
        monkeypatch,
        result={
            "status": 201, "headers": {}, "content_type": "application/json",
            "size": 2, "body": "{}", "body_path": None,
        },
    )
    await http_request("linear", "POST", "/issues", body={"title": "x"})
    assert captured["args"]["body"] == {"title": "x"}


@pytest.mark.asyncio
async def test_file_path_encodes_base64_and_guesses_content_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    payload = b"\x89PNG fake png"
    f = tmp_path / "img.png"
    f.write_bytes(payload)

    captured = _patch_call(
        monkeypatch,
        result={
            "status": 200, "headers": {}, "content_type": "text/plain",
            "size": 2, "body": "ok", "body_path": None,
        },
    )

    await http_request("linear", "PUT", "/upload", file_path=str(f))
    args = captured["args"]
    assert "body" not in args
    assert base64.b64decode(args["body_b64"]) == payload
    assert args["body_content_type"] == "image/png"


@pytest.mark.asyncio
async def test_file_path_unknown_extension_falls_back_to_octet_stream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    f = tmp_path / "data.weird"
    f.write_bytes(b"abc")

    captured = _patch_call(
        monkeypatch,
        result={
            "status": 200, "headers": {}, "content_type": "text/plain",
            "size": 2, "body": "ok", "body_path": None,
        },
    )

    await http_request("linear", "PUT", "/upload", file_path=str(f))
    assert captured["args"]["body_content_type"] == "application/octet-stream"


@pytest.mark.asyncio
async def test_body_and_file_path_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # broker should not be called when both are set.
    _patch_call(monkeypatch, result=None)
    out = await http_request(
        "linear", "POST", "/x", body="hi", file_path="/etc/hostname",
    )
    assert "Cannot set both" in out


@pytest.mark.asyncio
async def test_missing_file_reports_clearly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _patch_call(monkeypatch, result=None)
    out = await http_request(
        "linear", "PUT", "/upload", file_path=str(tmp_path / "missing.bin"),
    )
    assert "Cannot read file" in out
    assert "missing.bin" in out


@pytest.mark.asyncio
async def test_not_connected_maps_to_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_call(monkeypatch, exc=broker_client.IntegrationNotConnected("nope"))
    out = await http_request("linear", "GET", "/")
    assert "not connected" in out


@pytest.mark.asyncio
async def test_write_denied_explains_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_call(monkeypatch, exc=broker_client.IntegrationWriteDenied("denied"))
    out = await http_request("linear", "POST", "/issues")
    assert "read-only" in out
    assert "'POST'" in out


@pytest.mark.asyncio
async def test_generic_integration_error_surfaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_call(monkeypatch, exc=broker_client.IntegrationError("upstream 500"))
    out = await http_request("linear", "GET", "/")
    assert "failed" in out.lower()
    assert "upstream 500" in out


def test_build_tool_docstring_lists_ids() -> None:
    tool = build_http_request_tool(["linear", "notion"])
    assert tool.__name__ == "http_request"
    assert tool.__doc__ is not None
    assert "'linear'" in tool.__doc__
    assert "'notion'" in tool.__doc__


def test_build_tool_docstring_handles_empty_ids() -> None:
    tool = build_http_request_tool([])
    assert tool.__doc__ is not None
    assert "(none registered)" in tool.__doc__
