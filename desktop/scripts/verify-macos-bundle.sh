#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "verify-macos-bundle.sh must run on macOS" >&2
  exit 2
fi

target="${1:-}"
case "${target}" in
  aarch64-apple-darwin|x86_64-apple-darwin) ;;
  *)
    echo "usage: $0 <aarch64-apple-darwin|x86_64-apple-darwin> [--require-developer-id TEAM_ID]" >&2
    exit 2
    ;;
esac

expected_team_id=""
if [[ "${2:-}" == "--require-developer-id" ]]; then
  expected_team_id="${3:-}"
  if [[ ! "${expected_team_id}" =~ ^[A-Z0-9]{10}$ || -n "${4:-}" ]]; then
    echo "usage: $0 <aarch64-apple-darwin|x86_64-apple-darwin> [--require-developer-id TEAM_ID]" >&2
    exit 2
  fi
elif [[ -n "${2:-}" ]]; then
  echo "usage: $0 <aarch64-apple-darwin|x86_64-apple-darwin> [--require-developer-id TEAM_ID]" >&2
  exit 2
fi

desktop_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bundle_root="${desktop_root}/src-tauri/target/${target}/release/bundle"

shopt -s nullglob
apps=("${bundle_root}/macos/"*.app)
dmgs=("${bundle_root}/dmg/"*.dmg)
shopt -u nullglob

if [[ "${#apps[@]}" -gt 1 ]]; then
  echo "expected at most one app bundle under ${bundle_root}/macos, found ${#apps[@]}" >&2
  exit 1
fi
if [[ "${#dmgs[@]}" -ne 1 ]]; then
  echo "expected exactly one DMG under ${bundle_root}/dmg, found ${#dmgs[@]}" >&2
  exit 1
fi

verify_app() {
  local app="$1"
  local details

  codesign --verify --deep --strict --verbose=4 "${app}"
  details="$(codesign --display --verbose=4 "${app}" 2>&1)"
  printf '%s\n' "${details}"

  if grep -q '^Info.plist=not bound$' <<<"${details}"; then
    echo "${app} has an executable-only signature; Info.plist is not sealed" >&2
    return 1
  fi
  if grep -q '^Sealed Resources=none$' <<<"${details}"; then
    echo "${app} has no sealed bundle resources" >&2
    return 1
  fi
  if grep -Eq 'flags=.*linker-signed' <<<"${details}"; then
    echo "${app} has only the linker-generated signature" >&2
    return 1
  fi

  if [[ -n "${expected_team_id}" ]]; then
    if ! grep -q '^Authority=Developer ID Application:' <<<"${details}"; then
      echo "${app} is not signed with a Developer ID Application certificate" >&2
      return 1
    fi
    if ! grep -q "^TeamIdentifier=${expected_team_id}$" <<<"${details}"; then
      echo "${app} is not signed by expected Apple team ${expected_team_id}" >&2
      return 1
    fi
    if ! grep -Eq '^flags=.*\(runtime\)' <<<"${details}"; then
      echo "${app} does not enable the hardened runtime" >&2
      return 1
    fi
    if ! grep -Eq '^Timestamp=.+$' <<<"${details}" || grep -q '^Timestamp=none$' <<<"${details}"; then
      echo "${app} does not have a secure signing timestamp" >&2
      return 1
    fi
  fi
}

if [[ "${#apps[@]}" -eq 1 ]]; then
  echo "Verifying retained app bundle ${apps[0]}"
  verify_app "${apps[0]}"
else
  echo "Tauri removed the intermediate app after creating the DMG; verifying the packaged app"
fi

mount_point="$(mktemp -d "${TMPDIR:-/tmp}/omnideck-dmg.XXXXXX")"
mounted=0
cleanup() {
  if [[ "${mounted}" -eq 1 ]]; then
    hdiutil detach "${mount_point}" -quiet || hdiutil detach "${mount_point}" -force -quiet || true
  fi
  rmdir "${mount_point}" 2>/dev/null || true
}
trap cleanup EXIT

hdiutil attach -readonly -nobrowse -mountpoint "${mount_point}" "${dmgs[0]}" >/dev/null
mounted=1

applications_link="${mount_point}/Applications"
if [[ ! -L "${applications_link}" ]]; then
  echo "${dmgs[0]} does not contain the Applications drag-and-drop target" >&2
  exit 1
fi
if [[ "$(readlink "${applications_link}")" != "/Applications" ]]; then
  echo "${applications_link} does not point to /Applications" >&2
  exit 1
fi
if [[ ! -f "${mount_point}/.DS_Store" ]]; then
  echo "${dmgs[0]} does not contain Finder layout metadata" >&2
  exit 1
fi
packaged_background="${mount_point}/.background/dmg-background.png"
source_background="${desktop_root}/src-tauri/assets/dmg-background.png"
if [[ ! -f "${packaged_background}" ]] || ! cmp -s "${source_background}" "${packaged_background}"; then
  echo "${dmgs[0]} does not contain the configured DMG background" >&2
  exit 1
fi

shopt -s nullglob
mounted_apps=("${mount_point}/"*.app)
shopt -u nullglob
if [[ "${#mounted_apps[@]}" -ne 1 ]]; then
  echo "expected exactly one app bundle in ${dmgs[0]}, found ${#mounted_apps[@]}" >&2
  exit 1
fi

echo "Verifying packaged app bundle ${mounted_apps[0]}"
verify_app "${mounted_apps[0]}"

if [[ -n "${expected_team_id}" ]]; then
  dmg_details="$(codesign --display --verbose=4 "${dmgs[0]}" 2>&1)"
  printf '%s\n' "${dmg_details}"
  codesign --verify --strict --verbose=4 "${dmgs[0]}"
  if ! grep -q '^Authority=Developer ID Application:' <<<"${dmg_details}"; then
    echo "${dmgs[0]} is not signed with a Developer ID Application certificate" >&2
    exit 1
  fi
  if ! grep -q "^TeamIdentifier=${expected_team_id}$" <<<"${dmg_details}"; then
    echo "${dmgs[0]} is not signed by expected Apple team ${expected_team_id}" >&2
    exit 1
  fi
  if ! grep -Eq '^Timestamp=.+$' <<<"${dmg_details}" || grep -q '^Timestamp=none$' <<<"${dmg_details}"; then
    echo "${dmgs[0]} does not have a secure signing timestamp" >&2
    exit 1
  fi

  echo "Validating the notarization ticket stapled to ${dmgs[0]}"
  xcrun stapler validate "${dmgs[0]}"

  echo "Assessing packaged application with Gatekeeper"
  spctl --assess --type execute --verbose=4 "${mounted_apps[0]}"

  echo "Assessing disk image with Gatekeeper"
  spctl --assess --type open --context context:primary-signature --verbose=4 "${dmgs[0]}"
fi
