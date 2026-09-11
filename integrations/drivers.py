"""Broker launch contracts shared by catalogs and the process supervisor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class HostPathBinding:
    """Catalog-side opt-in: this integration's broker wants ``role`` at ``env_var``.

    ``role`` names a key in the supervisor's host-path registry (validated at
    boot). ``env_var`` is the env-var name the broker subprocess expects the
    resolved path under. ``mode`` records whether the broker reads or writes
    — informational today, a hook for future enforcement.
    """

    role: str
    env_var: str
    mode: Literal["read", "write"]


@dataclass(frozen=True)
class BrokerDriver:
    """Privileged executable, secret bindings, and host-path contract."""

    id: str
    command: tuple[str, ...]
    env_injection: dict[str, str] = field(default_factory=dict)
    host_paths: tuple[HostPathBinding, ...] = ()
    socket_protocol: str = "omnideck.rpc.v1"


__all__ = ["BrokerDriver", "HostPathBinding"]
