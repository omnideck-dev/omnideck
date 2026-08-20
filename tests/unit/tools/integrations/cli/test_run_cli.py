"""Unit tests for the run_cli agent tool.

Same pattern as ``test_call_api.py``: stub ``broker_client.call`` to return
canned shapes (or raise) and assert on the resulting string.
"""

from __future__ import annotations

from typing import Any

import pytest

from integrations import broker_client
from tools.integrations.cli.run_cli import build_run_cli_tool, run_cli


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
async def test_formats_exit_code_and_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_call(
        monkeypatch,
        result={"exit_code": 0, "stdout": "issue list output", "stderr": "", "truncated": False},
    )

    out = await run_cli("gh_work", ["issue", "list"])
    assert "exit code: 0" in out
    assert "issue list output" in out
    assert "stderr" not in out.lower() or "--- stderr ---" not in out


@pytest.mark.asyncio
async def test_includes_stderr_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_call(
        monkeypatch,
        result={"exit_code": 1, "stdout": "", "stderr": "boom", "truncated": False},
    )

    out = await run_cli("gh_work", ["bad-command"])
    assert "exit code: 1" in out
    assert "--- stderr ---" in out
    assert "boom" in out


@pytest.mark.asyncio
async def test_notes_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_call(
        monkeypatch,
        result={"exit_code": 0, "stdout": "partial", "stderr": "", "truncated": True},
    )

    out = await run_cli("gh_work", ["issue", "list"])
    assert "(output truncated)" in out


@pytest.mark.asyncio
async def test_passes_argv_cwd_stdin_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_call(
        monkeypatch,
        result={"exit_code": 0, "stdout": "", "stderr": "", "truncated": False},
    )

    await run_cli("gh_work", ["issue", "list"], cwd="repo", stdin="input", timeout=30)

    assert captured["verb"] == "run_command"
    assert captured["args"]["argv"] == ["issue", "list"]
    assert captured["args"]["cwd"] == "repo"
    assert captured["args"]["stdin"] == "input"
    assert captured["args"]["timeout"] == 30


@pytest.mark.asyncio
async def test_not_connected_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_call(monkeypatch, exc=broker_client.IntegrationNotConnected("nope"))

    out = await run_cli("missing", ["issue", "list"])
    assert "not connected" in out.lower()


@pytest.mark.asyncio
async def test_permission_denied_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_call(monkeypatch, exc=broker_client.IntegrationPermissionDenied("no rw"))

    out = await run_cli("gh_work", ["issue", "list"])
    assert "not permitted" in out.lower()


@pytest.mark.asyncio
async def test_generic_error_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_call(monkeypatch, exc=broker_client.IntegrationError("upstream exploded"))

    out = await run_cli("gh_work", ["issue", "list"])
    assert "failed" in out.lower()


@pytest.mark.asyncio
async def test_build_run_cli_tool_advertises_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_call(
        monkeypatch,
        result={"exit_code": 0, "stdout": "ok", "stderr": "", "truncated": False},
    )

    tool = build_run_cli_tool(["gh_work", "slack_bridge"])
    assert "gh_work" in tool.__doc__
    assert "slack_bridge" in tool.__doc__
    assert tool.__name__ == "run_cli"

    out = await tool("gh_work", ["issue", "list"])
    assert "ok" in out
