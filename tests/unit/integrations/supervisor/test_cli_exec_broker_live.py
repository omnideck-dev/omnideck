"""End-to-end test for the CLI-exec broker via a real ``Supervisor`` instance.

Same shape as ``test_supervisor.py``'s email-broker slice: a real
``Supervisor``, a real ``python -m integrations.brokers.exec_broker``
subprocess, real UDS RPC. Fakes only at the boundary — here, a tiny fixture
script stands in for a real CLI tool, the same way ``FakeEmail`` stands in
for a real IMAP/SMTP server in the email test. The ``cli`` catalog entry's
binary and secrets are always user-defined at add-time, so a fixture script
is a faithful stand-in — no real external tool needed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from integrations.supervisor._catalog import DEFAULT_CATALOG
from integrations.supervisor._lifecycle import Supervisor
from tests.unit.integrations.fixtures._host_paths import make_host_paths

_FIXTURE_SCRIPT = '''
import json
import os
import sys

args = sys.argv[1:]
if "--fail" in args:
    print("failing", file=sys.stderr)
    sys.exit(3)
if "--echo" in args:
    var_name = args[args.index("--echo") + 1]
    print(os.environ.get(var_name, ""))
else:
    print(json.dumps(args))
'''


async def _rpc_call(socket_path: Path, verb: str, args: dict[str, Any]) -> dict[str, Any]:
    """Send one length-prefixed JSON frame, read one response, close."""
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    try:
        req = json.dumps({"id": 1, "verb": verb, "args": args}).encode("utf-8")
        writer.write(len(req).to_bytes(4, "big") + req)
        await writer.drain()
        length = int.from_bytes(await reader.readexactly(4), "big")
        body = await reader.readexactly(length)
        return json.loads(body)
    finally:
        writer.close()
        await writer.wait_closed()


def _write_fixture_script(tmp_path: Path) -> Path:
    script = tmp_path / "fake_cli.py"
    script.write_text(_FIXTURE_SCRIPT)
    return script


async def _start_supervisor(tmp_path: Path) -> Supervisor:
    sup = Supervisor(
        vault_dir=tmp_path / "vault",
        app_sock_path=tmp_path / "app.sock",
        sockets_dir=tmp_path / "sockets",
        host_paths=make_host_paths(tmp_path),
        catalog={"cli": DEFAULT_CATALOG["cli"]},
    )
    await sup.start()
    return sup


def _blob(script: Path, *, secret: str = "s3cr3t-abc-123", path_prefix: str | None = None) -> dict:
    return {
        "command": [sys.executable, str(script)],
        "vars": {"FIXTURE_SECRET": secret},
        "path_prefix": path_prefix,
    }


@pytest.mark.asyncio
async def test_cli_add_run_remove(tmp_path: Path) -> None:
    script = _write_fixture_script(tmp_path)
    sup = await _start_supervisor(tmp_path)
    try:
        add_resp = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "cli",
                "user_suffix": "fixture",
                "label": "Fixture CLI",
                "auth_blob": _blob(script),
                "permissions": {"cli": "r"},
            },
        )
        assert "error" not in add_resp, add_resp
        broker_socket = Path(add_resp["result"]["socket"])

        run_resp = await _rpc_call(
            broker_socket, "run_command", {"argv": ["hello", "world"], "cwd": ""},
        )
        assert "error" not in run_resp, run_resp
        assert json.loads(run_resp["result"]["stdout"]) == ["hello", "world"]

        remove_resp = await _rpc_call(
            sup.app_sock_path, "remove", {"id": add_resp["result"]["id"]},
        )
        assert "error" not in remove_resp, remove_resp

        list_resp = await _rpc_call(sup.app_sock_path, "list", {})
        assert add_resp["result"]["id"] not in [i["id"] for i in list_resp["result"]["integrations"]]
    finally:
        await sup.stop()


@pytest.mark.asyncio
async def test_cli_redacts_secret_that_leaks_into_output(tmp_path: Path) -> None:
    script = _write_fixture_script(tmp_path)
    sup = await _start_supervisor(tmp_path)
    try:
        add_resp = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "cli",
                "user_suffix": "leaky",
                "label": "Leaky CLI",
                "auth_blob": _blob(script, secret="s3cr3t-abc-123"),
                "permissions": {"cli": "r"},
            },
        )
        assert "error" not in add_resp, add_resp
        broker_socket = Path(add_resp["result"]["socket"])

        echo_resp = await _rpc_call(
            broker_socket, "run_command", {"argv": ["--echo", "FIXTURE_SECRET"], "cwd": ""},
        )
        assert "error" not in echo_resp, echo_resp
        # The raw secret must never appear anywhere in the RPC response.
        assert "s3cr3t-abc-123" not in json.dumps(echo_resp)
        assert "[REDACTED]" in echo_resp["result"]["stdout"]
    finally:
        await sup.stop()


@pytest.mark.asyncio
async def test_cli_path_prefix_enforced(tmp_path: Path) -> None:
    script = _write_fixture_script(tmp_path)
    (tmp_path / "workspace" / "repo").mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspace" / "other").mkdir(parents=True, exist_ok=True)
    sup = await _start_supervisor(tmp_path)
    try:
        add_resp = await _rpc_call(
            sup.app_sock_path,
            "add",
            {
                "slug": "cli",
                "user_suffix": "scoped",
                "label": "Scoped CLI",
                "auth_blob": _blob(script, path_prefix="repo"),
                "permissions": {"cli": "r"},
            },
        )
        assert "error" not in add_resp, add_resp
        broker_socket = Path(add_resp["result"]["socket"])
        assert add_resp["result"]["path_prefix"] == "repo"

        ok_resp = await _rpc_call(broker_socket, "run_command", {"argv": [], "cwd": "repo"})
        assert "error" not in ok_resp, ok_resp

        denied_resp = await _rpc_call(broker_socket, "run_command", {"argv": [], "cwd": "other"})
        assert denied_resp["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await sup.stop()


@pytest.mark.asyncio
async def test_add_rejects_same_scope_var_name_collision(tmp_path: Path) -> None:
    script = _write_fixture_script(tmp_path)
    sup = await _start_supervisor(tmp_path)
    try:
        first = await _rpc_call(sup.app_sock_path, "add", {
            "slug": "cli", "user_suffix": "a", "label": "A",
            "auth_blob": _blob(script, secret="one"), "permissions": {"cli": "r"},
        })
        assert "error" not in first, first

        second = await _rpc_call(sup.app_sock_path, "add", {
            "slug": "cli", "user_suffix": "b", "label": "B",
            "auth_blob": _blob(script, secret="two"), "permissions": {"cli": "r"},
        })
        assert second.get("error", {}).get("code") == "BAD_REQUEST", second
    finally:
        await sup.stop()


@pytest.mark.asyncio
async def test_add_allows_cross_scope_var_name_shadow(tmp_path: Path) -> None:
    script = _write_fixture_script(tmp_path)
    (tmp_path / "workspace" / "repo").mkdir(parents=True, exist_ok=True)
    sup = await _start_supervisor(tmp_path)
    try:
        global_add = await _rpc_call(sup.app_sock_path, "add", {
            "slug": "cli", "user_suffix": "global", "label": "Global",
            "auth_blob": _blob(script, secret="one"), "permissions": {"cli": "r"},
        })
        assert "error" not in global_add, global_add

        scoped_add = await _rpc_call(sup.app_sock_path, "add", {
            "slug": "cli", "user_suffix": "scoped", "label": "Scoped",
            "auth_blob": _blob(script, secret="two", path_prefix="repo"),
            "permissions": {"cli": "r"},
        })
        assert "error" not in scoped_add, scoped_add
    finally:
        await sup.stop()


@pytest.mark.asyncio
async def test_update_rotates_secret_and_keeps_scope(tmp_path: Path) -> None:
    script = _write_fixture_script(tmp_path)
    (tmp_path / "workspace" / "repo").mkdir(parents=True, exist_ok=True)
    sup = await _start_supervisor(tmp_path)
    try:
        add_resp = await _rpc_call(sup.app_sock_path, "add", {
            "slug": "cli", "user_suffix": "rotate", "label": "Rotate",
            "auth_blob": _blob(script, secret="old-secret", path_prefix="repo"),
            "permissions": {"cli": "r"},
        })
        assert "error" not in add_resp, add_resp
        integration_id = add_resp["result"]["id"]

        update_resp = await _rpc_call(sup.app_sock_path, "update", {
            "id": integration_id,
            "auth_blob": _blob(script, secret="new-secret", path_prefix="repo"),
        })
        assert "error" not in update_resp, update_resp
        assert update_resp["result"]["path_prefix"] == "repo"

        broker_socket = Path(update_resp["result"]["socket"])
        echo_resp = await _rpc_call(
            broker_socket, "run_command", {"argv": ["--echo", "FIXTURE_SECRET"], "cwd": "repo"},
        )
        assert "new-secret" not in json.dumps(echo_resp)
        assert "[REDACTED]" in echo_resp["result"]["stdout"]
    finally:
        await sup.stop()
