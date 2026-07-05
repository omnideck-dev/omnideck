"""In-process implementations for core callables.

Core callables ship with Omnideck, so they run in the parent process, reached
by the manifest's ``python_import`` target. Each takes validated JSON args and
returns a JSON-shaped result.
"""

from __future__ import annotations

from typing import Any


def add(args: dict[str, Any]) -> dict[str, Any]:
    return {"sum": args["a"] + args["b"]}
