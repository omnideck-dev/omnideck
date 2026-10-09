#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "cleanup-macos-signing.sh must run on macOS" >&2
  exit 2
fi

if [[ -z "${OMNIDECK_SIGNING_DIRECTORY:-}" ]]; then
  exit 0
fi

if [[ -z "${RUNNER_TEMP:-}" ||
  "${OMNIDECK_SIGNING_DIRECTORY}" != "${RUNNER_TEMP%/}"/omnideck-signing.* ]]; then
  echo "Refusing to clean an unexpected signing directory" >&2
  exit 1
fi

if [[ -n "${OMNIDECK_SIGNING_KEYCHAIN:-}" ]]; then
  security delete-keychain "${OMNIDECK_SIGNING_KEYCHAIN}" >/dev/null 2>&1 || true
fi

if [[ -n "${OMNIDECK_SIGNING_CERTIFICATE:-}" ]]; then
  rm -f -- "${OMNIDECK_SIGNING_CERTIFICATE}"
fi
if [[ -n "${APPLE_API_KEY_PATH:-}" ]]; then
  rm -f -- "${APPLE_API_KEY_PATH}"
fi
if [[ -n "${OMNIDECK_SIGNING_KEYCHAIN:-}" ]]; then
  rm -f -- "${OMNIDECK_SIGNING_KEYCHAIN}"
fi
rmdir "${OMNIDECK_SIGNING_DIRECTORY}"

echo "Removed temporary macOS release signing material"
