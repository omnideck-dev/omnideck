"""Shared plain-text notices the integration tools return to the agent.

Centralising the wording keeps every tool's phrasing identical, so the agent
sees one consistent signal for a given failure mode no matter which tool hit
it.
"""

from __future__ import annotations


def auth_failed_message(integration_id: str) -> str:
    """Notice for when the broker reports upstream rejected the credentials.

    The integration is stuck until the user supplies a fresh credential, so
    the message points them at the fix rather than implying a retry might
    work.
    """
    return (
        f"Integration {integration_id!r} rejected its credentials — "
        "reconnect it in Settings to continue."
    )
