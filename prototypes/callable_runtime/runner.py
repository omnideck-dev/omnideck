"""Callable runner: the subprocess that executes one local/app callable.

The parent starts this process with a control socket on ``OMNIDECK_CTRL_FD``.
Frames on that socket:

    parent -> runner: {"type": "start", "call_id", "args"}
    runner -> parent: {"type": "invoke_dependency", "request_id", "ref", "args"}
    parent -> runner: {"type": "dependency_result", "request_id", "result"|"error"}
    parent -> runner: {"type": "cancel", "reason"}
    runner -> parent: {"type": "finish", "result"|"error"}

The implementation module exposes ``run(omni, args)`` and reaches declared
dependencies through ``omni.invoke(ref, args)``. A runner never opens another
runner; it only asks the parent, which owns dependency invocation.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
import frames  # noqa: E402


class DependencyError(Exception):
    def __init__(self, error: dict):
        self.error = error
        super().__init__(error.get("message", "dependency failed"))


class Cancelled(Exception):
    pass


class Omni:
    """In-runner SDK. ``invoke`` blocks on the control socket until the parent
    returns the dependency result."""

    def __init__(self, sock: socket.socket):
        self._sock = sock

    def invoke(self, ref: str, args: dict) -> dict:
        request_id = uuid.uuid4().hex
        frames.write_frame(
            self._sock,
            {"type": "invoke_dependency", "request_id": request_id, "ref": ref, "args": args},
        )
        while True:
            frame = frames.read_frame(self._sock)
            kind = frame.get("type")
            if kind == "dependency_result" and frame.get("request_id") == request_id:
                if frame.get("error"):
                    raise DependencyError(frame["error"])
                return frame["result"]
            if kind == "cancel":
                raise Cancelled()
            # ignore anything else in the prototype

    def emit(self, event: dict) -> None:
        frames.write_frame(self._sock, {"type": "event", "event": event})


def _load_impl(pkg_dir: str):
    spec = importlib.util.spec_from_file_location(
        "impl", os.path.join(pkg_dir, "implementation.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    fd = int(os.environ["OMNIDECK_CTRL_FD"])
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM, fileno=fd)
    pkg_dir = sys.argv[1]

    start = frames.read_frame(sock)
    args = start.get("args", {})
    omni = Omni(sock)
    try:
        module = _load_impl(pkg_dir)
        result = module.run(omni, args)
        frames.write_frame(sock, {"type": "finish", "result": result})
    except Cancelled:
        frames.write_frame(
            sock, {"type": "finish", "error": {"code": "CALLABLE_CANCELLED", "message": "cancelled"}}
        )
    except DependencyError as exc:
        frames.write_frame(sock, {"type": "finish", "error": exc.error})
    except Exception as exc:  # noqa: BLE001 - the prototype surfaces any failure
        frames.write_frame(
            sock,
            {"type": "finish", "error": {"code": "CALLABLE_EXCEPTION", "message": f"{type(exc).__name__}: {exc}"}},
        )


if __name__ == "__main__":
    main()
