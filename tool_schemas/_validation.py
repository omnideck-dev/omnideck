"""JSON Schema validation shared by discovery and executable tools."""

from typing import Any

from jsonschema import Draft202012Validator, SchemaError
from jsonschema.protocols import Validator
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.jsonschema import UnknownDialect, specification_with


class InvalidSchemaError(ValueError):
    """The supplied schema is not valid under its declared rules."""


class UnsupportedSchemaError(ValueError):
    """The supplied schema declares an unsupported dialect."""


def schema_validator(schema: dict[str, Any]) -> Validator:
    """Check a schema and create a validator without external retrieval."""
    if "$schema" in schema:
        if not isinstance(schema["$schema"], str):
            raise InvalidSchemaError("Invalid input schema dialect")
        try:
            specification_with(schema["$schema"])
        except UnknownDialect as exc:
            raise UnsupportedSchemaError("Unsupported input schema dialect") from exc
    validator_class = validator_for(schema, default=Draft202012Validator)
    try:
        validator_class.check_schema(schema)
    except SchemaError as exc:
        raise InvalidSchemaError(f"Invalid input schema: {exc.message}") from exc
    # Only embedded resources and local references may resolve. The default
    # registry retrieval refuses external resources, including HTTP and files.
    return validator_class(schema, registry=Registry())
