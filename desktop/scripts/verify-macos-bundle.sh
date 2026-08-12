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
    echo "usage: $0 <aarch64-apple-darwin|x86_64-apple-darwin>" >&2
    exit 2
    ;;
esac

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

shopt -s nullglob
mounted_apps=("${mount_point}/"*.app)
shopt -u nullglob
if [[ "${#mounted_apps[@]}" -ne 1 ]]; then
  echo "expected exactly one app bundle in ${dmgs[0]}, found ${#mounted_apps[@]}" >&2
  exit 1
fi

echo "Verifying packaged app bundle ${mounted_apps[0]}"
verify_app "${mounted_apps[0]}"
