"""Seed the opt-in setting for experimental chat goals."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def migrate(state_dir: Path) -> None:
    """Keep goals disabled on existing installations unless already configured."""
    path = state_dir / "settings.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Could not seed experimental goals in invalid settings")
        return
    if not isinstance(data, dict):
        logger.warning("Could not seed experimental goals in non-object settings")
        return
    if "goals_enabled" in data:
        return
    data["goals_enabled"] = False
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)
