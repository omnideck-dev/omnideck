"""Typed records the app server keeps about registered integrations.

The fields here are the subset of supervisor-side metadata that crosses the
public RPC and that the app actually uses (tool gating, UI rendering). The
supervisor's richer per-integration record (broker handle, catalog entry,
crypto material) stays on its side.
"""

from __future__ import annotations

from dataclasses import dataclass

from integrations.operation_grants import OperationGrants


@dataclass(frozen=True)
class RegisteredIntegration:
    """Snapshot of one integration as the app sees it.

    ``state`` mirrors the supervisor's runtime view: ``"running"`` for the
    happy path, ``"auth_failed"`` when the broker exited 77 (upstream
    rejected creds; user can reconnect), ``"broken"`` after three consecutive
    failed respawns. Tool gating skips anything not in
    ``"running"`` so the agent doesn't call into a dead broker.

    ``operation_grants`` is the exact agent allowlist. Agent adapters are only
    built for listed operation IDs on running integration instances.
    """

    id: str
    slug: str
    kind: str = "integration"
    operation_grants: OperationGrants = frozenset()
    state: str = "running"
