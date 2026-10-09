"""Evaluate in a document's main world without invoking its global eval."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from playwright.async_api import CDPSession, Frame
from playwright.async_api import Error as PlaywrightError

NO_ARGUMENT = object()
_FUNCTION_DECLARATION = re.compile(r"^(?:async)?\s*function(?:\s|\()")
_STRICT_DIRECTIVE = re.compile(
    r"""^(?:\s|/\*.*?\*/|//[^\n]*(?:\n|$))*(?P<quote>['"])use strict(?P=quote)\s*(?:;|$)""",
    re.DOTALL,
)
_SHARED_TARGET_ERROR = "This frame does not have a separate CDP session"
_CLEANUP_TIMEOUT_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class _ExecutionContext:
    context_id: int
    unique_id: str | None
    frame_id: str

    def evaluate_target(self) -> dict[str, Any]:
        # A unique identifier cannot accidentally address a new document after
        # navigation recycles a numeric execution-context identifier.
        if self.unique_id:
            return {"uniqueContextId": self.unique_id}
        return {"contextId": self.context_id}


def _result(response: dict[str, Any]) -> dict[str, Any]:
    details = response.get("exceptionDetails")
    if details:
        exception = details.get("exception") or {}
        message = exception.get("description") or details.get("text") or "JavaScript evaluation failed"
        raise PlaywrightError(str(message))
    return response.get("result") or {}


def _value(remote: dict[str, Any]) -> Any:
    if remote.get("type") == "function":
        return None
    special = remote.get("unserializableValue")
    if special == "NaN":
        return math.nan
    if special == "Infinity":
        return math.inf
    if special == "-Infinity":
        return -math.inf
    if special == "-0":
        return -0.0
    if isinstance(special, str) and special.endswith("n"):
        return int(special[:-1])
    return remote.get("value")


async def _attach(frame: Frame) -> tuple[CDPSession, Frame]:
    target = frame
    while True:
        try:
            return await frame.page.context.new_cdp_session(target), target
        except PlaywrightError as exc:
            parent = target.parent_frame
            if _SHARED_TARGET_ERROR not in str(exc) or parent is None:
                raise
            target = parent


async def _main_context(
    session: CDPSession,
    frame: Frame,
    attached_frame: Frame,
) -> _ExecutionContext:
    contexts: dict[int, _ExecutionContext] = {}

    def created(event: dict[str, Any]) -> None:
        payload = event["context"]
        auxiliary = payload.get("auxData") or {}
        if auxiliary.get("isDefault") and auxiliary.get("frameId"):
            contexts[payload["id"]] = _ExecutionContext(
                context_id=payload["id"],
                unique_id=payload.get("uniqueId"),
                frame_id=auxiliary["frameId"],
            )

    def destroyed(event: dict[str, Any]) -> None:
        contexts.pop(event["executionContextId"], None)

    def cleared(_event: dict[str, Any]) -> None:
        contexts.clear()

    session.on("Runtime.executionContextCreated", created)
    session.on("Runtime.executionContextDestroyed", destroyed)
    session.on("Runtime.executionContextsCleared", cleared)
    try:
        await session.send("Runtime.enable")
        if frame is attached_frame:
            tree = await session.send("Page.getFrameTree")
            frame_id = tree["frameTree"]["frame"]["id"]
            matches = [context for context in contexts.values() if context.frame_id == frame_id]
            if len(matches) == 1:
                return matches[0]
            raise PlaywrightError("The document's main execution context is unavailable")

        # Child frames may share a target and even have identical URLs/names.
        # A temporary DOM attribute bridges their native locator identity to
        # the exact main-world context without evaluating through the page.
        attribute = f"data-omnideck-context-{uuid4().hex}"
        candidates = list(contexts.values())
        tokens = {uuid4().hex: context for context in candidates}
        try:
            for token, context in tokens.items():
                with contextlib.suppress(PlaywrightError):
                    _result(
                        await session.send(
                            "Runtime.evaluate",
                            {
                                "expression": (
                                    "document.documentElement?.setAttribute("
                                    f"{json.dumps(attribute)}, {json.dumps(token)})"
                                ),
                                **context.evaluate_target(),
                                "returnByValue": True,
                            },
                        )
                    )
            selected_token = await frame.locator("html").get_attribute(attribute, timeout=5000)
            selected_context = tokens.get(selected_token) if selected_token is not None else None
            if selected_context is None or contexts.get(selected_context.context_id) != selected_context:
                raise PlaywrightError("The document changed while resolving its execution context")
            return selected_context
        finally:
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(_CLEANUP_TIMEOUT_SECONDS):
                    for context in candidates:
                        with contextlib.suppress(PlaywrightError):
                            await session.send(
                                "Runtime.evaluate",
                                {
                                    "expression": f"document.documentElement?.removeAttribute({json.dumps(attribute)})",
                                    **context.evaluate_target(),
                                    "returnByValue": True,
                                },
                            )
    finally:
        session.remove_listener("Runtime.executionContextCreated", created)
        session.remove_listener("Runtime.executionContextDestroyed", destroyed)
        session.remove_listener("Runtime.executionContextsCleared", cleared)


async def evaluate_frame(frame: Frame, expression: str, arg: Any = NO_ARGUMENT) -> Any:
    """Evaluate an expression or function in the selected frame's main world.

    Args:
        frame: Frame whose document and JavaScript globals the expression uses.
        expression: JavaScript expression, statements, or function source.
        arg: Optional JSON-serializable argument passed to a returned function.

    Returns:
        The JSON-compatible result, awaiting promises when necessary.

    Raises:
        PlaywrightError: If evaluation fails or the selected document disappears.
        TypeError: If the argument is not JSON-serializable.
        ValueError: If the argument contains non-finite numbers.
    """
    arguments = [] if arg is NO_ARGUMENT else [{"value": json.loads(json.dumps(arg, allow_nan=False))}]
    source = expression.strip()
    if _FUNCTION_DECLARATION.match(source):
        source = f"({source})"

    # A block gives each call fresh lexical declarations while retaining the
    # completion value and access to the document's main-world globals.
    strict_prefix = '"use strict";\n' if _STRICT_DIRECTIVE.match(source) else ""
    source = strict_prefix + "{\n" + source + "\n}"

    session, attached_frame = await _attach(frame)
    object_group = f"omnideck-evaluation-{uuid4().hex}"
    try:
        context = await _main_context(session, frame, attached_frame)
        # Compile and execute exactly once. Detecting the returned function
        # avoids recompiling expressions or retrying side effects on failure.
        remote = _result(
            await session.send(
                "Runtime.evaluate",
                {
                    "expression": source,
                    **context.evaluate_target(),
                    "objectGroup": object_group,
                    "awaitPromise": False,
                    "returnByValue": False,
                    "userGesture": True,
                },
            )
        )
        object_id = remote.get("objectId")
        if object_id is None:
            return _value(remote)

        is_function = remote.get("type") == "function"
        response = await session.send(
            "Runtime.callFunctionOn",
            {
                "objectId": object_id,
                "functionDeclaration": (
                    "function(...args) { return this(...args); }" if is_function else "function() { return this; }"
                ),
                "arguments": arguments if is_function else [],
                "objectGroup": object_group,
                "awaitPromise": True,
                "returnByValue": True,
                "userGesture": True,
            },
        )
        return _value(_result(response))
    finally:
        # An unresponsive renderer can also block object release. Cleanup must
        # remain bounded when the caller cancels a running script.
        try:
            with contextlib.suppress(PlaywrightError, TimeoutError):
                async with asyncio.timeout(_CLEANUP_TIMEOUT_SECONDS):
                    await session.send("Runtime.releaseObjectGroup", {"objectGroup": object_group})
        finally:
            with contextlib.suppress(PlaywrightError, TimeoutError):
                async with asyncio.timeout(_CLEANUP_TIMEOUT_SECONDS):
                    await session.detach()


__all__ = ["NO_ARGUMENT", "evaluate_frame"]
