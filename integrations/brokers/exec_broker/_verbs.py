"""Verb dispatcher for the generic CLI-exec broker.

The whole surface is one verb, ``run_command``. The handler is where the
safety properties live:

- The binary (and any fixed leading args) is fixed at spawn time from the
  catalog/secret bundle — the agent supplies only the trailing argv, never
  picks or overrides the binary.
- Execution goes through ``asyncio.create_subprocess_exec`` with an argv
  list, never a shell string — agent-supplied arguments can't break out via
  shell metacharacters.
- ``cwd`` is resolved against the broker's workspace root and, if the
  integration is folder-scoped (``PATH_PREFIX`` set at spawn), rejected
  outright when it falls outside that prefix — the authoritative copy of
  the check the tool layer also does before ever placing the RPC call.
- Every literal occurrence of an injected secret value is redacted from
  stdout/stderr before the response is built. This is substring redaction
  only (same limitation as GitHub Actions' log masking) — it catches a
  command that echoes the secret back verbatim, not a re-encoded or
  reformatted copy of it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path
from typing import Any

from integrations._paths import normalize_path_prefix
from integrations._rpc import RpcError
from integrations.permissions import Access, Capability, Permissions

logger = logging.getLogger(__name__)

# Output cap per stream. Generous for typical CLI output but bounded so a
# runaway command can't blow out the agent's context or the broker's memory.
_MAX_OUTPUT_BYTES = 1 * 1024 * 1024

_DEFAULT_TIMEOUT_SECONDS = 60.0
_MAX_TIMEOUT_SECONDS = 300.0

# Secret values shorter than this aren't redacted — a 1-2 character "secret"
# would turn ordinary output into swiss cheese for no security benefit.
_MIN_REDACT_LEN = 6

_REDACTED = "[REDACTED]"

_VERB_REQUIREMENT: dict[str, tuple[Capability, Access]] = {
    "run_command": (Capability.CLI, Access.READ),
}


class VerbDispatcher:
    """Route ``run_command`` RPC calls into a subprocess of the fixed binary."""

    def __init__(
        self,
        *,
        cli_bin: str,
        cli_bin_args: list[str],
        env: dict[str, str],
        secret_values: list[str],
        workspace_root: Path,
        path_prefix: str,
        permissions: Permissions,
        max_output_bytes: int = _MAX_OUTPUT_BYTES,
        default_timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._cli_bin = cli_bin
        self._cli_bin_args = cli_bin_args
        self._env = env
        self._secret_values = [v for v in secret_values if len(v) >= _MIN_REDACT_LEN]
        self._workspace_root = workspace_root.resolve()
        self._path_prefix = normalize_path_prefix(path_prefix)
        self._permissions = permissions
        self._max_output_bytes = max_output_bytes
        self._default_timeout_seconds = default_timeout_seconds

        self._handlers: dict[str, Any] = {
            "run_command": self._handle_run_command,
        }

    async def dispatch(self, verb: str, args: dict[str, Any]) -> dict[str, Any]:
        """Entry point invoked by the RPC layer for every incoming frame."""
        requirement = _VERB_REQUIREMENT.get(verb)
        if requirement is None:
            msg = f"unknown verb: {verb}"
            raise RpcError("BAD_REQUEST", msg)

        cap, min_access = requirement
        granted = self._permissions.get(cap, Access.OFF)
        if granted < min_access:
            msg = (
                f"verb {verb!r} requires {cap.value}:{min_access.name.lower()}, "
                f"but this integration has {cap.value}:{granted.name.lower()}"
            )
            raise RpcError("PERMISSION_DENIED", msg)

        handler = self._handlers[verb]
        return await handler(args)

    async def _handle_run_command(self, args: dict[str, Any]) -> dict[str, Any]:
        argv = _require_argv(args)
        cwd = self._resolve_cwd(args.get("cwd"))
        timeout = _coerce_timeout(args.get("timeout"), self._default_timeout_seconds)
        stdin_text = _coerce_stdin(args.get("stdin"))

        full_argv = [self._cli_bin, *self._cli_bin_args, *argv]
        try:
            proc = await asyncio.create_subprocess_exec(
                *full_argv,
                cwd=str(cwd),
                env=self._env,
                stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Own process group so a timeout can kill descendants too
                # (a forked or backgrounded child would otherwise survive
                # proc.kill(), which only signals the direct child).
                start_new_session=True,
            )
        except OSError as exc:
            raise RpcError("UPSTREAM_ERROR", f"failed to start {self._cli_bin!r}: {exc}") from exc

        stdin_bytes = stdin_text.encode("utf-8") if stdin_text is not None else None
        try:
            # Reading is capped as it streams in (not after a full
            # proc.communicate() buffers everything) so a command that
            # writes gigabytes to stdout can't blow out the broker's
            # memory before truncation ever applies. Bounding this whole
            # gather in one wait_for also covers the case where a
            # backgrounded child inherits the pipe and keeps it open past
            # the parent's exit — communicate()-style EOF-waiting would
            # hang past the timeout in exactly that case.
            _, (stdout_bytes, stdout_truncated), (stderr_bytes, stderr_truncated), _ = await asyncio.wait_for(
                asyncio.gather(
                    _pump_stdin(proc, stdin_bytes),
                    _read_capped(proc.stdout, self._max_output_bytes),
                    _read_capped(proc.stderr, self._max_output_bytes),
                    proc.wait(),
                ),
                timeout=timeout,
            )
        except TimeoutError as exc:
            _kill_process_group(proc)
            await proc.wait()
            raise RpcError("UPSTREAM_TIMEOUT", f"command timed out after {timeout:g}s") from exc

        stdout_text = _decode(stdout_bytes)
        stderr_text = _decode(stderr_bytes)

        return {
            "exit_code": proc.returncode,
            "stdout": _redact(stdout_text, self._secret_values),
            "stderr": _redact(stderr_text, self._secret_values),
            "truncated": stdout_truncated or stderr_truncated,
        }

    def _resolve_cwd(self, raw_cwd: Any) -> Path:
        """Resolve the caller-supplied cwd against the workspace root and enforce scope.

        Rejects anything that resolves outside the workspace root (path
        traversal via ``..`` included) and, if this integration is folder
        scoped, anything outside ``PATH_PREFIX``.
        """
        if raw_cwd is not None and not isinstance(raw_cwd, str):
            raise RpcError("BAD_REQUEST", "'cwd' must be a string")
        relative = (raw_cwd or "").strip("/")
        resolved = (self._workspace_root / relative).resolve()
        if resolved != self._workspace_root and self._workspace_root not in resolved.parents:
            raise RpcError("BAD_REQUEST", "cwd escapes the sandboxed workspace root")

        if self._path_prefix:
            prefix_root = (self._workspace_root / self._path_prefix).resolve()
            if resolved != prefix_root and prefix_root not in resolved.parents:
                raise RpcError(
                    "PERMISSION_DENIED",
                    f"this integration is restricted to {self._path_prefix!r}",
                )
        return resolved


def _require_argv(args: dict[str, Any]) -> list[str]:
    argv = args.get("argv")
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        raise RpcError("BAD_REQUEST", "'argv' must be a list of strings")
    return argv


def _coerce_timeout(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise RpcError("BAD_REQUEST", "'timeout' must be a positive number")
    return min(float(value), _MAX_TIMEOUT_SECONDS)


def _coerce_stdin(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RpcError("BAD_REQUEST", "'stdin' must be a string")
    return value


async def _pump_stdin(proc: asyncio.subprocess.Process, data: bytes | None) -> None:
    """Write ``data`` to the child's stdin (if any was given) and close it.

    Closing stdin even when ``data`` is ``None`` isn't needed here — the
    broker passes ``DEVNULL`` for that case, so ``proc.stdin`` is ``None``
    and there's nothing to do. Runs concurrently with the output readers so
    a child that only starts producing output after reading all of stdin
    can't deadlock against a full pipe.
    """
    if proc.stdin is None:
        return
    if data is not None:
        proc.stdin.write(data)
        try:
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            # Child exited (or closed stdin) before reading everything —
            # not our problem to report, the exit code already says so.
            return
    proc.stdin.close()


async def _read_capped(stream: asyncio.StreamReader | None, cap: int) -> tuple[bytes, bool]:
    """Read ``stream`` to EOF, keeping at most ``cap`` bytes.

    Keeps reading (and discarding) past the cap instead of stopping once
    it's hit — leaving the pipe unread would let its buffer fill up and
    stall the child process. Streams the cap instead of buffering
    everything first (unlike ``Process.communicate()``) so a command that
    writes far more than ``cap`` can't blow out the broker's own memory.
    """
    if stream is None:
        return b"", False
    chunks: list[bytes] = []
    stored = 0
    total = 0
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if stored < cap:
            take = chunk[: cap - stored]
            chunks.append(take)
            stored += len(take)
    return b"".join(chunks), total > cap


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the whole process group started for this subprocess.

    ``proc.kill()`` only signals the direct child; a forked or backgrounded
    descendant that outlived a timed-out command would otherwise survive.
    Relies on the process having been spawned with ``start_new_session=True``
    so its pid doubles as its process-group id.
    """
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _redact(text: str, secret_values: list[str]) -> str:
    for value in secret_values:
        if value in text:
            text = text.replace(value, _REDACTED)
    return text
