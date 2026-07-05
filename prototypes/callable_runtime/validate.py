"""Tiny JSON Schema subset validator for the prototype.

Supports the shapes the prototype manifests use: object with properties and
required, arrays with an items schema, and scalar type checks. It stands in for
a real jsonschema validator. The runtime turns a raised SchemaError into a
VALIDATION_ERROR at the callable boundary.
"""

from __future__ import annotations

from typing import Any

_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


class SchemaError(Exception):
    pass


def validate(schema: dict[str, Any], value: Any, path: str = "$") -> None:
    expected = schema.get("type")
    if expected:
        # bool is a subclass of int; keep integer and boolean distinct.
        if expected in ("integer", "number") and isinstance(value, bool):
            raise SchemaError(f"{path}: expected {expected}, got boolean")
        if not isinstance(value, _TYPES[expected]):
            raise SchemaError(
                f"{path}: expected {expected}, got {type(value).__name__}"
            )
    if expected == "object":
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaError(f"{path}: missing required field '{key}'")
        for key, subschema in schema.get("properties", {}).items():
            if key in value:
                validate(subschema, value[key], f"{path}.{key}")
    elif expected == "array":
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(value):
                validate(item_schema, item, f"{path}[{i}]")
