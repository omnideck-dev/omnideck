#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$script_dir/_common.sh"

release="latest"
scenario="keep"
profile="default"
skip_confirmation="false"

usage() {
  echo "Usage: $0 [--release latest|choose|TAG] [--scenario keep|first-run|resume|update|doctor|returning] [--profile NAME] [--yes]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) release="${2:?Missing release value}"; shift 2 ;;
    --scenario) scenario="${2:?Missing scenario value}"; shift 2 ;;
    --profile) profile="${2:?Missing profile name}"; shift 2 ;;
    --yes) skip_confirmation="true"; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

validate_profile_name "$profile"
TEST_NAMESPACE="release-test-${profile}"
require_command hdiutil
require_command shasum

state_root="$HOME/Library/Application Support/omnideck-release-testing"
cache_root="$HOME/Library/Caches/omnideck-release-testing"
profiles_root="$state_root/profiles"
profile_root="$profiles_root/$profile"
selected_release="$(select_release "$release")"
require_isolated_release "$selected_release"
release_cache="$cache_root/releases/$selected_release/macos"
mkdir -p "$release_cache"
prepare_test_scenario "$scenario" "$profile_root" "$profiles_root" "$skip_confirmation"

gh release download "$selected_release" \
  --repo "$RELEASE_REPOSITORY" \
  --pattern 'OmniDeck-*-mac-arm64.dmg' \
  --pattern 'OmniDeck-*-mac-arm64.dmg.sha256' \
  --dir "$release_cache" \
  --skip-existing

artifact="$(compgen -G "$release_cache/OmniDeck-*-mac-arm64.dmg" | head -n 1)"
checksum="${artifact}.sha256"
(
  cd "$release_cache"
  shasum -a 256 --check "$(basename "$checksum")"
)

mount_point="$(mktemp -d)"
cleanup_mount() {
  hdiutil detach "$mount_point" -quiet >/dev/null 2>&1 || true
  rmdir "$mount_point" >/dev/null 2>&1 || true
}
trap cleanup_mount EXIT
hdiutil attach "$artifact" -nobrowse -readonly -mountpoint "$mount_point" -quiet

app_candidates=("$mount_point"/*.app)
if [[ ! -d "${app_candidates[0]}" ]]; then
  echo "No application was found in $artifact" >&2
  exit 1
fi
binary_candidates=("${app_candidates[0]}"/Contents/MacOS/*)
if [[ ! -x "${binary_candidates[0]}" ]]; then
  echo "No application executable was found in $artifact" >&2
  exit 1
fi

echo "Launching $selected_release with scenario '$scenario' and profile '$profile'."
"${binary_candidates[0]}"
