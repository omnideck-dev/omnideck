"""Seed the welcome conversation on a fresh install.

Like every migration this runs exactly once, but it only seeds when setup is
still incomplete — a genuine first run. That gives the three properties we
want:

* fresh install (setup not complete) → seeded, once, before the UI lists
  conversations (so it shows in the sidebar without a refresh);
* existing install (setup already complete when this migration first runs)
  → skipped, so upgraders never get it;
* deleted by the user → never comes back, because the migration is marked
  applied and never re-runs (and even a re-run would find setup complete and
  skip).

Runs after ``002_install_default_profiles`` so the profile the welcome
conversation references already exists.
"""

from __future__ import annotations

import logging
from pathlib import Path

from settings import load_settings

logger = logging.getLogger(__name__)


def migrate(_state_dir: Path) -> None:
    """Seed the welcome conversation, but only on a fresh install."""
    if load_settings().get("setup_complete"):
        # Existing install — don't plant a welcome conversation on upgrade.
        return

    # Lazy import: the seeder pulls in conversations/artifacts/sdk.events,
    # heavier than a migration module should import at module load.
    from migrations._welcome_conversation import seed_welcome_conversation

    try:
        seed_welcome_conversation()
    except Exception:
        # Seeding is a nice-to-have; never let it fail app startup.
        logger.exception("Failed to seed welcome conversation")
