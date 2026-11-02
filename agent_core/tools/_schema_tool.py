"""Executable tools with an explicit input contract, independent of MCP."""

from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any

from jsonschema import ValidationError
from referencing.exceptions import Unresolvable

from utils.schema_validation import schema_validator


class SchemaTool:
    """Advertise and enforce the same input schema without coercing arguments."""

    def __init__(
        self, name: str, description: str, input_schema: dict[str, Any],
        invoke: Callable[[dict[str, Any]], Awaitable[Any]],
    ) -> None:
        self.__name__ = name
        self.__doc__ = description
        self._schema = deepcopy(input_schema)
        self._validator = schema_validator(self._schema)
        self._invoke = invoke

    def definition(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.__name__, "description": self.__doc__,
            "parameters": deepcopy(self._schema),
        }}

    async def __call__(self, **arguments: Any) -> Any:
        try:
            self._validator.validate(arguments)
        except ValidationError as exc:
            raise ValueError(f"Invalid arguments for tool '{self.__name__}' at {exc.json_path}: {exc.message}") from exc
        except Unresolvable as exc:
            raise ValueError(
                f"Cannot validate tool '{self.__name__}': schema references must resolve within the supplied schema"
            ) from exc
        return await self._invoke(arguments)
