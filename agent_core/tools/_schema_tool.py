"""Executable tools with an explicit input contract, independent of MCP."""

from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any


class SchemaTool:
    """Keep a supplied schema intact instead of inferring it from **kwargs."""

    def __init__(
        self, name: str, description: str, input_schema: dict[str, Any],
        invoke: Callable[[dict[str, Any]], Awaitable[Any]],
    ) -> None:
        self.__name__ = name
        self.__doc__ = description
        self._schema = deepcopy(input_schema)
        self._invoke = invoke

    def definition(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.__name__, "description": self.__doc__,
            "parameters": deepcopy(self._schema),
        }}

    async def __call__(self, **arguments: Any) -> Any:
        return await self._invoke(arguments)
