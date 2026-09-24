"""Rewrite old install paths in stored state after the computron→omnideck rename.

The container user's home, state, and app directories moved from
``/home/computron``, ``/var/lib/computron``, and ``/opt/computron`` to their
``omnideck`` equivalents. Runtime symlinks keep the old paths resolving, but
paths baked into installed skills, profiles, goals, and conversation logs get
fed back into prompts, so rewrite them at rest as well.

Walks the whole state tree, skips binary files (a NUL byte in the first 8 KB)
and anything that isn't UTF-8 text, and replaces the three old prefixes wherever
they appear. Backs up each changed file before writing. No-op on fresh installs
and on a second run, since nothing still contains the old prefixes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from migrations._backup import backup_file

logger = logging.getLogger(__name__)

_NAME = "012_computron_path_rename"

# How much of a file to sniff for a NUL byte before deciding it's binary.
_PROBE_BYTES = 8192

# Old → new install-path prefixes. Ordered longest-first isn't needed since
# none is a prefix of another, but the set must stay in sync with the image.
_PREFIX_RENAMES: tuple[tuple[str, str], ...] = (
    ("/home/computron", "/home/omnideck"),
    ("/var/lib/computron", "/var/lib/omnideck"),
    ("/opt/computron", "/opt/omnideck"),
)


def _rewrite_file(state_dir: Path, path: Path) -> bool:
    """Rewrite one file's old install paths in place. Returns True if changed."""
    if path.is_symlink():
        return False

    with path.open("rb") as f:
        head = f.read(_PROBE_BYTES)
        if b"\x00" in head:
            return False  # binary file
        data = head + f.read()

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False  # not UTF-8 text; leave it untouched

    updated = text
    for old, new in _PREFIX_RENAMES:
        updated = updated.replace(old, new)
    if updated == text:
        return False

    backup_file(state_dir, _NAME, path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(updated, encoding="utf-8")
    tmp.replace(path)
    return True


def migrate(state_dir: Path) -> None:
    """Rewrite old computron install paths to omnideck across stored state."""
    rewritten = 0
    for dirpath, dirnames, filenames in os.walk(state_dir):
        # Our own backups are already rewritten copies of nothing — and holding
        # the pre-migration originals, they must stay verbatim. os.walk skips
        # directories it can't read (e.g. the broker-owned integrations vault).
        if ".backups" in dirnames:
            dirnames.remove(".backups")
        for filename in filenames:
            path = Path(dirpath) / filename
            try:
                if _rewrite_file(state_dir, path):
                    rewritten += 1
            except OSError:
                logger.exception("Failed to rewrite %s; leaving it untouched", path)
    if rewritten:
        logger.info("Rewrote install paths in %d state file(s)", rewritten)
