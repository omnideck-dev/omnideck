"""Shared tool input contracts, independent of execution and application owners."""

from ._validation import InvalidSchemaError, UnsupportedSchemaError, schema_validator

__all__ = ["InvalidSchemaError", "UnsupportedSchemaError", "schema_validator"]
