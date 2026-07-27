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
require_command sha256sum

state_root="${XDG_STATE_HOME:-$HOME/.local/state}/omnideck-release-testing"
cache_root="${XDG_CACHE_HOME:-$HOME/.cache}/omnideck-release-testing"
profiles_root="$state_root/profiles"
profile_root="$profiles_root/$profile"
selected_release="$(select_release "$release")"
require_isolated_release "$selected_release"
release_cache="$cache_root/releases/$selected_release/linux"
mkdir -p "$release_cache"
prepare_test_scenario "$scenario" "$profile_root" "$profiles_root" "$skip_confirmation"

gh release download "$selected_release" \
  --repo "$RELEASE_REPOSITORY" \
  --pattern 'OmniDeck-*-linux-x86_64.AppImage' \
  --pattern 'OmniDeck-*-linux-x86_64.AppImage.sha256' \
  --dir "$release_cache" \
  --skip-existing

artifact="$(compgen -G "$release_cache/OmniDeck-*-linux-x86_64.AppImage" | head -n 1)"
checksum="${artifact}.sha256"
(
  cd "$release_cache"
  sha256sum --check "$(basename "$checksum")"
)
chmod +x "$artifact"

extracted_app="$release_cache/extracted/squashfs-root/AppRun"
if [[ ! -x "$extracted_app" ]]; then
  extraction_root="$release_cache/extracted"
  if [[ -d "$extraction_root" ]]; then
    rm -rf -- "$extraction_root"
  fi
  mkdir -p "$extraction_root"
  (
    cd "$extraction_root"
    "$artifact" --appimage-extract >/dev/null
  )
fi

echo "Launching $selected_release with scenario '$scenario' and profile '$profile'."
exec "$extracted_app"
