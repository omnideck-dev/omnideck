"""Deprecated v1/v2 permission wire format.

Only metadata migration and older-client compatibility projections may import
this module. Runtime authorization uses explicit canonical operation IDs.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Capability(StrEnum):
    """What an integration is."""

    EMAIL = "email"
    CALENDAR = "calendar"
    DRIVE = "drive"
    CONTACTS = "contacts"
    HTTP = "http"


class Access(IntEnum):
    """How much access the user grants for one capability.

    IntEnum so comparisons work naturally: ``Access.READ_WRITE > Access.READ``.
    Serialized to/from short strings at the deprecated HTTP/RPC boundary.
    """

    OFF = 0
    READ = 1
    READ_WRITE = 2


_ACCESS_TO_STR: dict[Access, str] = {
    Access.OFF: "off",
    Access.READ: "r",
    Access.READ_WRITE: "rw",
}

_STR_TO_ACCESS: dict[str, Access] = {v: k for k, v in _ACCESS_TO_STR.items()}


def access_to_str(access: Access) -> str:
    """Short string form for wire serialization: ``"off"``, ``"r"``, ``"rw"``."""
    return _ACCESS_TO_STR[access]


def access_from_str(s: str) -> Access:
    """Parse a short string back to an Access level. Raises ValueError on bad input."""
    result = _STR_TO_ACCESS.get(s)
    if result is None:
        msg = f"unknown access level: {s!r} (expected one of {sorted(_STR_TO_ACCESS)})"
        raise ValueError(msg)
    return result


Permissions = dict[Capability, Access]


def permissions_to_dict(perms: Permissions) -> dict[str, str]:
    """Serialize to a JSON-friendly ``{capability: access_str}`` dict."""
    return {cap.value: access_to_str(access) for cap, access in perms.items()}


def permissions_from_dict(d: dict[str, str]) -> Permissions:
    """Deserialize from a JSON ``{capability: access_str}`` dict.

    Skips unknown capabilities so a meta file written by a newer version
    (with capabilities this version doesn't know about) doesn't crash on
    load — the unknown capability is simply invisible until the code is
    updated.
    """
    perms: Permissions = {}
    for cap_str, access_str in d.items():
        try:
            cap = Capability(cap_str)
        except ValueError:
            continue
        perms[cap] = access_from_str(access_str)
    return perms
