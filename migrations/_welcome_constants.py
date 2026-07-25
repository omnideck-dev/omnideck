"""Stable identities shared by welcome-data seeding and first-run startup."""

# These values are data identities, not presentation policy. The setup API
# returns them so the UI can build its own first-run Desktop Layout snapshot
# without importing the migration's event-building implementation.
WELCOME_CONVERSATION_ID = "welcome-to-omnideck"
WELCOME_DASHBOARD_FILENAME = "welcome_dashboard.html"

__all__ = [
    "WELCOME_CONVERSATION_ID",
    "WELCOME_DASHBOARD_FILENAME",
]
