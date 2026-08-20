"""Agent tool: run a configured CLI command through a broker-held credential."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from config import load_config
from integrations import broker_client

logger = logging.getLogger(__name__)


async def run_cli(
    integration_id: str,
    args: list[str],
    cwd: str = "",
    stdin: str | None = None,
    timeout: float | None = None,
) -> str:
    """Run a configured CLI tool with its credential(s) injected automatically.

    The integration owns a fixed binary/script and its secret(s); you
    supply the trailing arguments (never the binary) and, if the
    integration is folder-scoped, a cwd under its allowed folder. The
    secret is injected into the command's environment by the broker — you
    never see it, and any occurrence of it in the command's output comes
    back redacted.

    Args:
        integration_id: Which configured CLI integration to run.
        args: Arguments to pass to the command, e.g. ["--flag", "value"].
        cwd: Working directory, relative to the workspace root — same root
            run_bash_cmd uses. Required if the integration is folder-scoped.
        stdin: Optional text to pipe to the command's stdin.
        timeout: Optional timeout in seconds (capped server-side).

    Returns:
        The command's exit code, stdout, and stderr as text. Any credential
        value that leaked into the output is replaced with "[REDACTED]".
    """
    rpc_args: dict[str, Any] = {"argv": args, "cwd": cwd}
    if stdin is not None:
        rpc_args["stdin"] = stdin
    if timeout is not None:
        rpc_args["timeout"] = timeout

    app_sock = load_config().integrations.app_sock_path
    try:
        result = await broker_client.call(
            integration_id, "run_command", rpc_args, app_sock_path=app_sock,
        )
    except broker_client.IntegrationNotConnected:
        return f"Integration {integration_id!r} is not connected."
    except broker_client.IntegrationPermissionDenied as exc:
        return f"Not permitted: {exc}"
    except broker_client.IntegrationError as exc:
        logger.warning("run_cli(%r, %r) failed: %s", integration_id, args, exc)
        return f"Command through {integration_id!r} failed: {exc}"

    return _format_result(result)


def _format_result(result: dict[str, Any]) -> str:
    """Format the broker's response dict into the plain text the agent reads."""
    exit_code = result.get("exit_code")
    stdout = result.get("stdout") or ""
    stderr = result.get("stderr") or ""

    lines = [f"exit code: {exit_code}"]
    if result.get("truncated"):
        lines.append("(output truncated)")
    if stdout:
        lines.append("--- stdout ---")
        lines.append(stdout)
    if stderr:
        lines.append("--- stderr ---")
        lines.append(stderr)
    return "\n".join(lines)


def build_run_cli_tool(integration_ids: Iterable[str]) -> Callable[..., Any]:
    """Turn-scoped wrapper whose docstring advertises the current IDs."""
    ids = sorted(integration_ids)
    ids_line = ", ".join(repr(i) for i in ids) if ids else "(none registered)"

    async def _run_cli(
        integration_id: str,
        args: list[str],
        cwd: str = "",
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> str:
        return await run_cli(integration_id, args, cwd=cwd, stdin=stdin, timeout=timeout)

    _run_cli.__name__ = run_cli.__name__
    _run_cli.__doc__ = (
        "Run a configured CLI tool with its credential(s) injected "
        "automatically. Each integration owns a fixed binary/script and its "
        "secret(s); you supply the trailing arguments (never the binary) "
        "and, if the integration is folder-scoped, a cwd under its allowed "
        "folder. You never see the secret, and any occurrence of it in "
        f"the command's output comes back redacted. Valid integration IDs: {ids_line}.\n\n"
        "Args:\n"
        "    integration_id: Which configured CLI integration to run.\n"
        "    args: Arguments to pass to the command, e.g. [\"--flag\", \"value\"].\n"
        "    cwd: Working directory, relative to the workspace root — same "
        "root run_bash_cmd uses. Required if the integration is folder-scoped.\n"
        "    stdin: Optional text to pipe to the command's stdin.\n"
        "    timeout: Optional timeout in seconds (capped server-side).\n\n"
        "Returns:\n"
        "    The command's exit code, stdout, and stderr as text. Any "
        'credential value that leaked into the output is replaced with "[REDACTED]".\n'
    )
    return _run_cli
