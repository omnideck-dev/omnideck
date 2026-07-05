"""Prototype callable runtime: registry, invoke_callable, call-graph limits.

Proves the reentrant invocation loop from callable-runtime.md:
  - core callables run in-process (python_import),
  - local callables run as subprocess runners over a parent-managed RPC channel,
  - a running callable reaches declared dependencies back through the parent,
  - the parent enforces declared-dependency, recursion, depth, and fanout limits,
  - args and results are schema-validated at the callable boundary.

Deliberately stubbed vs the design doc: package-dependency environments (uses
the current interpreter, no installs), OS-level sandboxing, on-disk run logs,
user-initiated cancellation, and the apps/app-router layer.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
import frames  # noqa: E402
from validate import SchemaError, validate  # noqa: E402

# Limits transcribed from callable-runtime.md "Call Graph Limits".
MAX_DEPTH = 8
MAX_CHILD_CALLS_PER_ROOT = 64
MAX_CONCURRENT_RUNNERS_PER_ROOT = 8
MAX_GLOBAL_RUNNERS = 32

_HERE = Path(__file__).parent
_RUNNER = str(_HERE / "runner.py")


class CallableError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclasses.dataclass
class Registry:
    """Resolves ``id@version`` to a loaded manifest and its package directory."""

    by_ref: dict[str, tuple[dict, Path]]

    @classmethod
    def load(cls, root: Path) -> "Registry":
        by_ref: dict[str, tuple[dict, Path]] = {}
        for manifest_path in sorted(root.rglob("manifest.json")):
            manifest = json.loads(manifest_path.read_text())
            ref = f"{manifest['id']}@{manifest['version']}"
            by_ref[ref] = (manifest, manifest_path.parent)
        return cls(by_ref)

    def resolve(self, ref: str) -> tuple[dict, Path]:
        if ref not in self.by_ref:
            raise CallableError("CALLABLE_NOT_FOUND", f"no callable {ref}")
        return self.by_ref[ref]


@dataclasses.dataclass
class RootState:
    """Per-top-level-invocation counters shared down the whole call tree."""

    root_call_id: str
    child_calls: int = 0
    active_runners: int = 0


@dataclasses.dataclass
class GlobalState:
    """Process-wide counters and an in-memory event log (stands in for run logs)."""

    active_runners: int = 0
    events: list[dict] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Context:
    caller: str                    # "agent" or the invoking callable ref
    caller_manifest: dict | None   # None for the agent / top level
    call_stack: tuple[str, ...]    # ancestor refs, not including the target
    root: RootState


def _check_caller_allowed(ctx: Context, ref: str, scope: str) -> None:
    if ctx.caller_manifest is None:
        # Top-level agent caller may invoke core or local callables directly.
        if scope in ("core", "local"):
            return
        raise CallableError("CALLER_NOT_ALLOWED", f"agent may not invoke {scope} callable {ref}")
    # A running callable may only invoke refs it declared as dependencies.
    if ref not in ctx.caller_manifest.get("callable_dependencies", []):
        raise CallableError("UNDECLARED_DEPENDENCY", f"{ctx.caller} did not declare dependency {ref}")


async def invoke_callable(reg: Registry, ref: str, args: Any, ctx: Context, g: GlobalState) -> Any:
    manifest, pkg_dir = reg.resolve(ref)
    scope = manifest["scope"]

    _check_caller_allowed(ctx, ref, scope)

    if ref in ctx.call_stack:
        raise CallableError("CALL_GRAPH_RECURSION", f"{ref} already on the call stack")
    new_stack = ctx.call_stack + (ref,)
    if len(new_stack) > MAX_DEPTH:
        raise CallableError("CALL_GRAPH_DEPTH_EXCEEDED", f"depth {len(new_stack)} exceeds {MAX_DEPTH}")
    if ctx.call_stack:  # a nested call, not the root
        ctx.root.child_calls += 1
        if ctx.root.child_calls > MAX_CHILD_CALLS_PER_ROOT:
            raise CallableError(
                "CALL_GRAPH_FANOUT_EXCEEDED", f"root exceeded {MAX_CHILD_CALLS_PER_ROOT} child calls"
            )

    try:
        validate(manifest["input_schema"], args)
    except SchemaError as exc:
        raise CallableError("VALIDATION_ERROR", f"args: {exc}") from exc

    g.events.append({"type": "callable_started", "ref": ref, "scope": scope, "depth": len(new_stack)})

    child_ctx = Context(caller=ref, caller_manifest=manifest, call_stack=new_stack, root=ctx.root)
    impl = manifest["implementation"]
    if scope == "core" and impl["kind"] == "python_import":
        result = await _run_core(impl, args)
    else:
        result = await _run_runner(reg, ref, pkg_dir, args, child_ctx, g)

    try:
        validate(manifest["output_schema"], result)
    except SchemaError as exc:
        raise CallableError("VALIDATION_ERROR", f"result: {exc}") from exc

    g.events.append({"type": "callable_finished", "ref": ref, "status": "ok"})
    return result


async def _run_core(impl: dict, args: Any) -> Any:
    module_name, func_name = impl["target"].split(":")
    func = getattr(importlib.import_module(module_name), func_name)
    result = func(args)
    if asyncio.iscoroutine(result):
        result = await result
    return result


async def _run_runner(reg: Registry, ref: str, pkg_dir: Path, args: Any, child_ctx: Context, g: GlobalState) -> Any:
    if g.active_runners >= MAX_GLOBAL_RUNNERS:
        raise CallableError("CALL_GRAPH_CONCURRENCY_EXCEEDED", "global runner cap reached")
    if child_ctx.root.active_runners >= MAX_CONCURRENT_RUNNERS_PER_ROOT:
        raise CallableError("CALL_GRAPH_CONCURRENCY_EXCEEDED", "per-root runner cap reached")

    parent_sock, child_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    env = {"OMNIDECK_CTRL_FD": str(child_sock.fileno()), "PATH": os.environ.get("PATH", "")}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, _RUNNER, str(pkg_dir), env=env, pass_fds=(child_sock.fileno(),)
    )
    child_sock.close()  # the parent keeps only its own end

    g.active_runners += 1
    child_ctx.root.active_runners += 1
    loop = asyncio.get_event_loop()
    parent_sock.setblocking(False)
    try:
        await frames.awrite_frame(loop, parent_sock, {"type": "start", "call_id": ref, "args": args})
        result: Any = None
        error: dict | None = None
        while True:
            try:
                frame = await frames.aread_frame(loop, parent_sock)
            except ConnectionError as exc:
                raise CallableError("CALLABLE_RUNTIME_ERROR", f"runner exited before finishing: {exc}") from exc
            kind = frame.get("type")
            if kind == "event":
                g.events.append({"type": "runner_event", "ref": ref, "event": frame.get("event")})
            elif kind == "invoke_dependency":
                await _handle_dependency(reg, child_ctx, g, loop, parent_sock, frame)
            elif kind == "finish":
                result, error = frame.get("result"), frame.get("error")
                break
        if error:
            raise CallableError(error.get("code", "CALLABLE_EXCEPTION"), error.get("message", ""))
        return result
    finally:
        parent_sock.close()
        await proc.wait()
        g.active_runners -= 1
        child_ctx.root.active_runners -= 1


async def _handle_dependency(reg, child_ctx, g, loop, parent_sock, frame) -> None:
    request_id = frame.get("request_id")
    dep_ref = frame.get("ref")
    g.events.append({"type": "dependency_call", "from": child_ctx.caller, "target": dep_ref})
    try:
        result = await invoke_callable(reg, dep_ref, frame.get("args"), child_ctx, g)
        reply = {"type": "dependency_result", "request_id": request_id, "result": result}
    except CallableError as exc:
        reply = {
            "type": "dependency_result",
            "request_id": request_id,
            "error": {"code": exc.code, "message": exc.message},
        }
    await frames.awrite_frame(loop, parent_sock, reply)


def new_agent_context(ref: str) -> tuple[Context, GlobalState]:
    """Build the top-level context for an agent-initiated invocation."""
    g = GlobalState()
    root = RootState(root_call_id=ref)
    return Context(caller="agent", caller_manifest=None, call_stack=(), root=root), g
