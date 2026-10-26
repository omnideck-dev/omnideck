"""Migration 016: Grant the ``theme`` tool category to the installed ``assistant`` skill.

Migration 006 copied the shipped ``assistant`` skill into ``{state}/skills/`` once
and never touches it again, so adding ``theme`` to the shipped record only reaches
fresh installs. This appends it to an install that already has the skill, letting
the agent read and change ``custom.css`` there too.

Only the category is appended; the rest of the record — including any prompt the
user has edited — is left exactly as it was. A skill the user deleted stays
deleted, and one that already grants ``theme`` is not rewritten.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from skills._store import SKILLS_SUBDIR

logger = logging.getLogger(__name__)

_ASSISTANT_FILE = "assistant.json"
_CATEGORY = "theme"


def migrate(state_dir: Path) -> None:
    """Append the ``theme`` category to the installed ``assistant`` skill."""
    path = state_dir / SKILLS_SUBDIR / _ASSISTANT_FILE
    if not path.exists():
        return

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Unreadable %s, skipping migration 016", path)
        return

    categories = list(record.get("tool_categories") or [])
    if _CATEGORY in categories:
        return

    record["tool_categories"] = [*categories, _CATEGORY]
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    logger.info("Granted the %s tool category to the assistant skill", _CATEGORY)
