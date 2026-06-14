"""Helper utilities for normalizing tool results, preparing tool arguments, and executing tool calls."""

from __future__ import annotations

import inspect
import json
import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ._tool_model import validate_arguments

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

logger = logging.getLogger(__name__)

from pydantic import BaseModel


@runtime_checkable
class _HasDict(Protocol):
    def dict(self) -> Mapping[str, object]:  # pragma: no cover - protocol
        ...


def _normalize_tool_result(obj: object) -> object:
    """Prepare tool results for JSON serialization by normalizing nested models."""
    if isinstance(obj, BaseModel):
        return _normalize_tool_result(obj.model_dump())
    if isinstance(obj, _HasDict):
        return _normalize_tool_result(obj.dict())
    if isinstance(obj, dict):
        return {k: _normalize_tool_result(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [_normalize_tool_result(i) for i in obj]
    return obj


def _prepare_tool_arguments(
    tool_func: Callable[..., Any], arguments: dict[str, Any]
) -> dict[str, Any]:
    """Validate and coerce raw LLM arguments against a tool's signature."""
    return validate_arguments(tool_func, arguments)


# Tool argument values are summarized for UI display: stringified,
# whitespace-collapsed to one line, and capped to this length. The cap
# doubles as a payload guard — large args (file content) never ship in
# full on the event.
_MAX_ARG_DISPLAY_LEN = 64


def _summarize_arguments(arguments: dict[str, Any]) -> dict[str, str]:
    """Stringify, whitespace-collapse, and length-cap tool arguments for
    display. Each value becomes a single short string."""
    summary: dict[str, str] = {}
    for key, value in arguments.items():
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, default=str)
            except (TypeError, ValueError):
                text = str(value)
        text = " ".join(text.split())
        if len(text) > _MAX_ARG_DISPLAY_LEN:
            text = text[: _MAX_ARG_DISPLAY_LEN - 1] + "…"
        summary[str(key)] = text
    return summary


async def _execute_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    tools: list[Callable[..., Any]],
) -> str:
    """Resolve and execute a single tool call, returning the result as a string.

    Args:
        tool_name: The name of the tool function to call.
        arguments: The arguments to pass to the tool function.
        tools: Available tool functions to match against.

    Returns:
        Plain string result for the LLM to read.
    """
    from sdk.events import AgentEvent, ToolCallPayload, publish_event
    from sdk.turn._turn import StopRequestedError

    # Some models emit function names with Python call syntax, e.g.
    # "browse_page(full_page=True)" instead of "browse_page".  Strip the
    # trailing parenthesised portion and merge any kwargs into arguments.
    if tool_name and "(" in tool_name:
        base, _, rest = tool_name.partition("(")
        tool_name = base
        # Try to parse kwargs like "full_page=True" into arguments
        rest = rest.rstrip(")")
        if rest and not arguments:
            arguments = {}
            for part in rest.split(","):
                part = part.strip()
                if "=" in part:
                    k, _, v = part.partition("=")
                    # Coerce simple Python literals
                    v = v.strip()
                    if v in ("True", "true"):
                        arguments[k.strip()] = True
                    elif v in ("False", "false"):
                        arguments[k.strip()] = False
                    elif v.isdigit():
                        arguments[k.strip()] = int(v)
                    else:
                        arguments[k.strip()] = v.strip("\"'")

    try:
        publish_event(AgentEvent(payload=ToolCallPayload(
            type="tool_call",
            name=str(tool_name),
            arguments=_summarize_arguments(arguments) if arguments else None,
        )))
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to publish tool_call event for tool '%s'", tool_name)

    tool_func = next(
        (t for t in tools if getattr(t, "__name__", None) == tool_name),
        None,
    )
    if not tool_func:
        logger.error("Tool '%s' not found in tools.", tool_name)
        return "Tool not found"

    try:
        validated_args = _prepare_tool_arguments(tool_func, arguments)
        if inspect.iscoroutinefunction(tool_func):
            result = await tool_func(**validated_args)
        else:
            result = tool_func(**validated_args)
        normalized = _normalize_tool_result(result)
        return str(normalized) if not isinstance(normalized, str) else normalized
    except StopRequestedError:
        raise
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.exception("Argument validation failed for tool '%s'", tool_name)
        return f"Argument validation failed: {exc}"
    except Exception as exc:
        logger.exception("Error running tool '%s'", tool_name)
        return str(exc)


__all__ = ["_execute_tool_call", "_normalize_tool_result", "_prepare_tool_arguments"]
