"""Typed connection data at the broker boundary, independent of providers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType


class BrokerConnectionData(Mapping[str, str]):
    """Validated, read-only connection fields with a redacted repr.

    This bundle includes credentials, connection settings (such as base URL),
    and authorization metadata. All fields remain encrypted together in the
    vault. Names belong to each driver's bindings, not a universal provider
    schema; values are strings for broker environment injection. ``auth_blob``
    remains the HTTP/RPC wire field name for compatibility.
    """

    def __init__(self, fields: Mapping[str, str]) -> None:
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in fields.items()):
            raise ValueError("authentication fields must have string keys and values")
        self._fields = MappingProxyType(dict(fields))

    @classmethod
    def from_wire(cls, value: object) -> BrokerConnectionData:
        """Validate JSON input without including credential values in errors.

        Older scope metadata can contain a string array. Normalize that one
        field to the space-separated form used by OAuth and broker bindings.
        """
        if not isinstance(value, dict):
            raise ValueError("auth_blob must be an object")
        fields = dict(value)
        scopes = fields.get("scopes")
        if isinstance(scopes, list) and all(isinstance(scope, str) for scope in scopes):
            fields["scopes"] = " ".join(scopes)
        return cls(fields)

    @property
    def granted_scopes(self) -> frozenset[str]:
        """Return scope metadata only; missing scopes grant nothing."""
        return frozenset(self.get("scopes", "").split())

    def __getitem__(self, key: str) -> str:
        return self._fields[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._fields)

    def __len__(self) -> int:
        return len(self._fields)

    def __repr__(self) -> str:
        return "BrokerConnectionData(<redacted>)"
