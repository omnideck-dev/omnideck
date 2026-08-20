"""Tests for the CLI-exec broker's verb dispatcher.

The dispatcher is the whole broker: it execs a fixed binary with agent-
supplied trailing args (never a shell), enforces folder scope, and redacts
injected secret values from anything the child process prints. Tests spawn
real subprocesses (``/bin/echo``, ``/bin/sh``, ``/bin/sleep``) — what's under
test is the dispatcher's argv construction, cwd/scope enforcement, and
redaction, not the target binary itself.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from integrations._rpc import RpcError
from integrations.brokers.exec_broker._verbs import VerbDispatcher
from integrations.permissions import Access, Capability


def _make_dispatcher(
    *,
    tmp_path: Path,
    cli_bin: str = "/bin/echo",
    cli_bin_args: list[str] | None = None,
    env: dict[str, str] | None = None,
    secret_values: list[str] | None = None,
    path_prefix: str = "",
    permissions: dict[Capability, Access] | None = None,
    max_output_bytes: int = 1024 * 1024,
    default_timeout_seconds: float = 5.0,
) -> VerbDispatcher:
    return VerbDispatcher(
        cli_bin=cli_bin,
        cli_bin_args=cli_bin_args or [],
        env=env or {},
        secret_values=secret_values or [],
        workspace_root=tmp_path,
        path_prefix=path_prefix,
        permissions=permissions if permissions is not None else {Capability.CLI: Access.READ},
        max_output_bytes=max_output_bytes,
        default_timeout_seconds=default_timeout_seconds,
    )


@pytest.mark.asyncio
async def test_run_command_basic(tmp_path: Path) -> None:
    dispatcher = _make_dispatcher(tmp_path=tmp_path)
    result = await dispatcher.dispatch("run_command", {"argv": ["hello", "world"]})
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "hello world"
    assert result["stderr"] == ""
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_run_command_redacts_secret_in_stdout(tmp_path: Path) -> None:
    secret = "s3cr3t-token-value"
    dispatcher = _make_dispatcher(
        tmp_path=tmp_path,
        cli_bin="/bin/sh",
        cli_bin_args=["-c"],
        env={"MY_SECRET": secret},
        secret_values=[secret],
    )
    result = await dispatcher.dispatch(
        "run_command", {"argv": ["echo before $MY_SECRET after"]},
    )
    assert secret not in result["stdout"]
    assert "[REDACTED]" in result["stdout"]
    assert result["stdout"].strip() == "before [REDACTED] after"


@pytest.mark.asyncio
async def test_run_command_redacts_secret_in_stderr(tmp_path: Path) -> None:
    secret = "another-secret-value"
    dispatcher = _make_dispatcher(
        tmp_path=tmp_path,
        cli_bin="/bin/sh",
        cli_bin_args=["-c"],
        env={"MY_SECRET": secret},
        secret_values=[secret],
    )
    result = await dispatcher.dispatch(
        "run_command", {"argv": ["echo $MY_SECRET 1>&2"]},
    )
    assert secret not in result["stderr"]
    assert "[REDACTED]" in result["stderr"]


@pytest.mark.asyncio
async def test_run_command_does_not_redact_short_values(tmp_path: Path) -> None:
    """Secrets shorter than the redaction floor are left alone (avoids swiss-cheesing output)."""
    dispatcher = _make_dispatcher(
        tmp_path=tmp_path,
        cli_bin="/bin/sh",
        cli_bin_args=["-c"],
        env={"MY_SECRET": "ab"},
        secret_values=["ab"],
    )
    result = await dispatcher.dispatch("run_command", {"argv": ["echo has ab in it"]})
    assert "[REDACTED]" not in result["stdout"]
    assert "ab" in result["stdout"]


@pytest.mark.asyncio
async def test_run_command_no_shell_interpretation(tmp_path: Path) -> None:
    """argv is exec'd as an array — shell metacharacters in an arg are literal text."""
    dispatcher = _make_dispatcher(tmp_path=tmp_path)
    payload = "$(rm -rf /tmp/nonexistent); echo pwned"
    result = await dispatcher.dispatch("run_command", {"argv": [payload]})
    assert result["stdout"].strip() == payload


@pytest.mark.asyncio
async def test_run_command_cwd_relative_to_workspace_root(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    dispatcher = _make_dispatcher(tmp_path=tmp_path, cli_bin="/bin/pwd")
    result = await dispatcher.dispatch("run_command", {"argv": [], "cwd": "sub"})
    assert result["stdout"].strip() == str((tmp_path / "sub").resolve())


@pytest.mark.asyncio
async def test_run_command_cwd_escaping_workspace_root_rejected(tmp_path: Path) -> None:
    dispatcher = _make_dispatcher(tmp_path=tmp_path)
    with pytest.raises(RpcError) as exc_info:
        await dispatcher.dispatch("run_command", {"argv": [], "cwd": "../../etc"})
    assert exc_info.value.code == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_run_command_path_prefix_rejects_outside_scope(tmp_path: Path) -> None:
    (tmp_path / "repo" / "sub").mkdir(parents=True)
    (tmp_path / "other").mkdir()
    dispatcher = _make_dispatcher(tmp_path=tmp_path, path_prefix="repo")

    with pytest.raises(RpcError) as exc_info:
        await dispatcher.dispatch("run_command", {"argv": [], "cwd": "other"})
    assert exc_info.value.code == "PERMISSION_DENIED"

    with pytest.raises(RpcError) as exc_info2:
        await dispatcher.dispatch("run_command", {"argv": [], "cwd": ""})
    assert exc_info2.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_run_command_path_prefix_allows_scoped_subfolder(tmp_path: Path) -> None:
    (tmp_path / "repo" / "sub").mkdir(parents=True)
    dispatcher = _make_dispatcher(tmp_path=tmp_path, cli_bin="/bin/pwd", path_prefix="repo")
    result = await dispatcher.dispatch("run_command", {"argv": [], "cwd": "repo/sub"})
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_run_command_whitespace_only_path_prefix_normalizes_to_global(tmp_path: Path) -> None:
    """A whitespace-only PATH_PREFIX must not become an unmatchable literal scope.

    Without normalizing whitespace (only slashes), the broker would enforce
    a scope of e.g. three literal spaces — a directory name that can never
    realistically exist, permanently bricking the integration.
    """
    dispatcher = _make_dispatcher(tmp_path=tmp_path, path_prefix="   ")
    result = await dispatcher.dispatch("run_command", {"argv": [], "cwd": ""})
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_run_command_permission_denied_without_capability(tmp_path: Path) -> None:
    dispatcher = _make_dispatcher(tmp_path=tmp_path, permissions={})
    with pytest.raises(RpcError) as exc_info:
        await dispatcher.dispatch("run_command", {"argv": ["hi"]})
    assert exc_info.value.code == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_dispatch_unknown_verb(tmp_path: Path) -> None:
    dispatcher = _make_dispatcher(tmp_path=tmp_path)
    with pytest.raises(RpcError) as exc_info:
        await dispatcher.dispatch("delete_everything", {})
    assert exc_info.value.code == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_run_command_argv_must_be_list_of_strings(tmp_path: Path) -> None:
    dispatcher = _make_dispatcher(tmp_path=tmp_path)
    with pytest.raises(RpcError) as exc_info:
        await dispatcher.dispatch("run_command", {"argv": "not-a-list"})
    assert exc_info.value.code == "BAD_REQUEST"


@pytest.mark.asyncio
async def test_run_command_output_truncated_when_over_cap(tmp_path: Path) -> None:
    dispatcher = _make_dispatcher(
        tmp_path=tmp_path,
        cli_bin="/bin/sh",
        cli_bin_args=["-c"],
        max_output_bytes=8,
    )
    result = await dispatcher.dispatch("run_command", {"argv": ["echo 0123456789abcdef"]})
    assert result["truncated"] is True
    assert len(result["stdout"].encode("utf-8")) <= 8


@pytest.mark.asyncio
async def test_run_command_timeout(tmp_path: Path) -> None:
    dispatcher = _make_dispatcher(
        tmp_path=tmp_path,
        cli_bin="/bin/sleep",
        default_timeout_seconds=0.2,
    )
    with pytest.raises(RpcError) as exc_info:
        await dispatcher.dispatch("run_command", {"argv": ["5"]})
    assert exc_info.value.code == "UPSTREAM_TIMEOUT"


@pytest.mark.asyncio
async def test_run_command_timeout_kills_backgrounded_descendants(tmp_path: Path) -> None:
    """A timeout must kill the whole process group, not just the direct child.

    The shell backgrounds a subshell (its own process, same process group)
    that would write ``marker`` after a short sleep, then blocks in the
    foreground well past the timeout. If only the direct child got killed
    (``proc.kill()``), the backgrounded subshell would survive and still
    write the marker after the dispatch call returns.
    """
    marker = tmp_path / "marker"
    dispatcher = _make_dispatcher(
        tmp_path=tmp_path,
        cli_bin="/bin/sh",
        cli_bin_args=["-c"],
        default_timeout_seconds=0.3,
    )
    script = f"(sleep 1 && touch {marker}) & sleep 5"
    with pytest.raises(RpcError) as exc_info:
        await dispatcher.dispatch("run_command", {"argv": [script]})
    assert exc_info.value.code == "UPSTREAM_TIMEOUT"

    await asyncio.sleep(1.5)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_run_command_nonexistent_binary_raises_upstream_error(tmp_path: Path) -> None:
    dispatcher = _make_dispatcher(tmp_path=tmp_path, cli_bin="/no/such/binary")
    with pytest.raises(RpcError) as exc_info:
        await dispatcher.dispatch("run_command", {"argv": []})
    assert exc_info.value.code == "UPSTREAM_ERROR"


@pytest.mark.asyncio
async def test_run_command_stdin_piped(tmp_path: Path) -> None:
    dispatcher = _make_dispatcher(tmp_path=tmp_path, cli_bin="/bin/cat")
    result = await dispatcher.dispatch("run_command", {"argv": [], "stdin": "piped text"})
    assert result["stdout"] == "piped text"
