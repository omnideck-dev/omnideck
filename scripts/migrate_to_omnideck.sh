#!/usr/bin/env bash
# Move dev state from the old ~/.computron_9000 location to ~/.omnideck and
# leave a compat symlink behind. Run once, manually. Safe to re-run: it
# no-ops when there is nothing to do.
set -euo pipefail

OLD="$HOME/.computron_9000"
NEW="$HOME/.omnideck"
OLD_CTR="computron_virtual_computer"

# -L before -e: a dangling symlink is "already migrated", not "nothing there".
if [ -L "$OLD" ]; then
    echo "$OLD is already a symlink — nothing to do."
    exit 0
fi

if [ ! -e "$OLD" ]; then
    echo "Nothing to migrate — $OLD does not exist."
    exit 0
fi

if [ -d "$NEW" ]; then
    echo "ERROR: $NEW already exists. Merge or remove it manually, then re-run." >&2
    exit 1
fi

# The old-named dev container bind-mounts $OLD; `just stop` on the renamed
# branch only knows the new container name, so remove the old one here.
if command -v docker >/dev/null && docker ps -aq -f "name=^${OLD_CTR}\$" | grep -q .; then
    echo "Removing old dev container ${OLD_CTR} (state lives in $OLD, nothing is lost)"
    docker rm -f "$OLD_CTR" >/dev/null
fi

echo "Migrating $OLD → $NEW"
mv "$OLD" "$NEW"
ln -sn "$NEW" "$OLD"
echo "Done. $OLD is now a symlink to $NEW."
