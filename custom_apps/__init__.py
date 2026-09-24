"""Public helpers for authoring Omnideck Custom App backends."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, overload

_ACTION_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_ACTION_NAME_ATTRIBUTE = "__omnideck_action_name__"


@overload
def action[Action: Callable[..., Any]](function: Action, /) -> Action: ...


@overload
def action[Action: Callable[..., Any]](*, name: str | None = None) -> Callable[[Action], Action]: ...


def action[Action: Callable[..., Any]](
    function: Action | None = None,
    /,
    *,
    name: str | None = None,
) -> Action | Callable[[Action], Action]:
    """Mark a function as a callable Custom App backend action."""

    def decorate(target: Action) -> Action:
        action_name = name or target.__name__
        if not _ACTION_NAME.fullmatch(action_name):
            raise ValueError("Action names must be valid Python-style identifiers up to 64 characters.")
        setattr(target, _ACTION_NAME_ATTRIBUTE, action_name)
        return target

    return decorate(function) if function is not None else decorate


def _get_action_name(value: Any) -> str | None:
    """Return the registered action name for a decorated callable."""
    name = getattr(value, _ACTION_NAME_ATTRIBUTE, None)
    return name if callable(value) and isinstance(name, str) else None


__all__ = ["action"]
