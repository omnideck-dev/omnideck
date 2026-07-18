"""Subprocess entry point for one experimental Custom App action."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import inspect
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

from custom_apps import _get_action_name

_ACTION_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class ActionError(Exception):
    """A structured, user-correctable action error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _load_actions(app_root: Path) -> dict[str, Any]:
    source = app_root / "app.py"
    spec = importlib.util.spec_from_file_location("_omnideck_custom_app", source)
    if spec is None or spec.loader is None:
        raise ActionError("APP_LOAD_FAILED", "Could not load app.py.")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(app_root))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    actions: dict[str, Any] = {}
    for value in vars(module).values():
        name = _get_action_name(value)
        if name is None:
            continue
        if not _ACTION_NAME.fullmatch(name):
            raise ActionError("APP_LOAD_FAILED", "A decorated action has an invalid name.")
        existing = actions.get(name)
        if existing is not None and existing is not value:
            raise ActionError("APP_LOAD_FAILED", f"Multiple actions are registered as {name!r}.")
        actions[name] = value
    return actions


async def _invoke(app_root: Path, action_name: str, args: dict[str, Any]) -> Any:
    actions = _load_actions(app_root)
    action = actions.get(action_name)
    if action is None or not _ACTION_NAME.fullmatch(action_name):
        raise ActionError("ACTION_NOT_FOUND", "App action not found.")
    try:
        bound = inspect.signature(action).bind(**args)
    except TypeError as exc:
        raise ActionError("INVALID_ARGUMENTS", str(exc)) from exc
    result = action(*bound.args, **bound.kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


def _emit(payload: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        encoded = json.dumps({
            "ok": False,
            "error": {"code": "RESULT_NOT_JSON", "message": f"Action result is not JSON-compatible: {exc}"},
        })
    sys.__stdout__.write(encoded)
    sys.__stdout__.flush()


def main() -> None:
    """Load one action, execute it, and emit exactly one JSON envelope."""
    if len(sys.argv) != 3:
        _emit({"ok": False, "error": {"code": "RUNNER_USAGE", "message": "Invalid runner arguments."}})
        return
    app_root = Path(sys.argv[1]).resolve()
    action_name = sys.argv[2]
    try:
        raw = json.loads(sys.stdin.read())
        args = raw.get("args")
        if not isinstance(args, dict):
            raise ActionError("INVALID_ARGUMENTS", "args must be an object.")
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            result = asyncio.run(_invoke(app_root, action_name, args))
        _emit({"ok": True, "result": result})
    except ActionError as exc:
        _emit({"ok": False, "error": {"code": exc.code, "message": str(exc)}})
    except Exception as exc:
        _emit({
            "ok": False,
            "error": {"code": "ACTION_FAILED", "message": f"{type(exc).__name__}: {exc}"},
        })


if __name__ == "__main__":
    main()
