#!/usr/bin/env bash

set -Eeuo pipefail

export LANG=C
export LC_ALL=C

dmg="${1:?DMG path is required}"
output_dir="${2:?Output directory is required}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mount_point="$(mktemp -d "/private/tmp/omnideck-dmg.XXXXXX")"

cleanup_mount() {
  hdiutil detach "$mount_point" -quiet >/dev/null 2>&1 || true
  rmdir "$mount_point" >/dev/null 2>&1 || true
}
trap cleanup_mount EXIT

[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || {
  printf 'The macOS lab guest requires native Apple Silicon.\n' >&2
  exit 2
}
[[ -f "$dmg" ]] || { printf 'DMG not found: %s\n' "$dmg" >&2; exit 1; }
if pgrep -f '/(omnideck-desktop|omnideck)$' >/dev/null 2>&1; then
  printf 'Close the existing omnideck application before acquiring the macOS test lane.\n' >&2
  exit 1
fi

hdiutil attach "$dmg" -nobrowse -readonly -mountpoint "$mount_point" -quiet
app="$(find "$mount_point" -maxdepth 1 -type d -name '*.app' -print -quit)"
[[ -n "$app" ]] || { printf 'The DMG contains no application bundle.\n' >&2; exit 1; }
application="$app/Contents/MacOS/omnideck-desktop"
[[ -x "$application" ]] || { printf 'The app contains no executable omnideck host.\n' >&2; exit 1; }
file "$application" | grep -Eq 'Mach-O 64-bit.*arm64'

installed_app="$HOME/Applications/Omnideck Lab.app"
[[ ! -e "$installed_app" ]] || {
  printf 'The disposable baseline was not clean; application already exists: %s\n' "$installed_app" >&2
  exit 1
}
/usr/bin/ditto "$app" "$installed_app"
installed_application="$installed_app/Contents/MacOS/omnideck-desktop"
[[ "$(defaults read "$installed_app/Contents/Info" CFBundleIdentifier 2>/dev/null || true)" == dev.omnideck.desktop ]] || {
  printf 'The installed application has an unexpected bundle identifier.\n' >&2
  exit 1
}
[[ -x "$installed_application" ]] || { printf 'Installed application executable is missing.\n' >&2; exit 1; }
[[ "$(shasum -a 256 "$application" | awk '{print $1}')" == "$(shasum -a 256 "$installed_application" | awk '{print $1}')" ]] || {
  printf 'Installed application executable differs from the mounted candidate.\n' >&2
  exit 1
}

mkdir -p "$output_dir"
installed_digest="$(shasum -a 256 "$installed_application" | awk '{print $1}')"
node - "$output_dir/installation.json" "$installed_app" "$installed_digest" <<'NODE'
const fs = require('node:fs');
const [path, destination, sha256] = process.argv.slice(2);
fs.writeFileSync(path, `${JSON.stringify({
  schemaVersion: 1,
  kind: 'application',
  destination,
  bundleIdentifier: 'dev.omnideck.desktop',
  executableSha256: sha256,
  architecture: 'arm64',
}, null, 2)}\n`);
NODE

"$script_dir/run.sh" --application "$installed_application" --output "$output_dir" --require-ready
