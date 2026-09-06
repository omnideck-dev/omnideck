"""Migration 016: replace legacy specialized-role defaults with Auto.

The old values were copied from a local Ollama configuration and could leak
``top_k``/``num_ctx`` plus arbitrary sampling overrides into cloud models.
Only the exact historical dictionaries are cleared; user-customized values
remain untouched.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_LEGACY_VISION_OPTIONS = {
    "num_ctx": 60000,
    "num_predict": 512,
    "temperature": 0.3,
    "top_k": 20,
}
_LEGACY_COMPACTION_OPTIONS = {
    "num_ctx": 32768,
    "num_predict": 8192,
    "temperature": 0.3,
    "top_k": 20,
}


def migrate(state_dir: Path) -> None:
    """Clear untouched legacy option snapshots so model defaults can apply."""
    path = state_dir / "settings.json"
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Corrupt %s, skipping migration 016", path)
        return

    changed = False
    if data.get("vision_options") == _LEGACY_VISION_OPTIONS:
        data["vision_options"] = {}
        changed = True
    if data.get("compaction_options") == _LEGACY_COMPACTION_OPTIONS:
        data["compaction_options"] = {}
        changed = True

    if changed:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Reset legacy model-role inference values to Auto in %s", path)
