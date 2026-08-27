#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "configure-macos-signing.sh must run on macOS" >&2
  exit 2
fi

required_variables=(
  APPLE_TEAM_ID
  DESKTOP_MAC_CERTIFICATE_P12_BASE64
  DESKTOP_MAC_CERTIFICATE_PASSWORD
  DESKTOP_APPLE_API_KEY_ID
  DESKTOP_APPLE_API_ISSUER_ID
  DESKTOP_APPLE_API_PRIVATE_KEY_BASE64
  GITHUB_ENV
  RUNNER_TEMP
)

for variable in "${required_variables[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Required macOS signing input ${variable} is not set" >&2
    exit 1
  fi
done

signing_directory="$(mktemp -d "${RUNNER_TEMP%/}/omnideck-signing.XXXXXX")"
keychain_path="${signing_directory}/omnideck-signing.keychain-db"
certificate_path="${signing_directory}/developer-id.p12"
api_key_path="${signing_directory}/AuthKey_${DESKTOP_APPLE_API_KEY_ID}.p8"
keychain_password="$(openssl rand -hex 32)"

cleanup_on_error() {
  local status=$?
  if [[ "${status}" -ne 0 ]]; then
    security delete-keychain "${keychain_path}" >/dev/null 2>&1 || true
    rm -f -- "${certificate_path}" "${api_key_path}" "${keychain_path}"
    rmdir "${signing_directory}" 2>/dev/null || true
  fi
  return "${status}"
}
trap cleanup_on_error EXIT

printf '%s' "${DESKTOP_MAC_CERTIFICATE_P12_BASE64}" |
  openssl base64 -d -A > "${certificate_path}"
printf '%s' "${DESKTOP_APPLE_API_PRIVATE_KEY_BASE64}" |
  openssl base64 -d -A > "${api_key_path}"
chmod 600 "${certificate_path}" "${api_key_path}"

if ! grep -q '^-----BEGIN PRIVATE KEY-----$' "${api_key_path}" ||
  ! grep -q '^-----END PRIVATE KEY-----$' "${api_key_path}"; then
  echo "The decoded App Store Connect API key is not a PEM private key" >&2
  exit 1
fi

security create-keychain -p "${keychain_password}" "${keychain_path}"
security set-keychain-settings -t 21600 -u "${keychain_path}"
security unlock-keychain -p "${keychain_password}" "${keychain_path}"
security import "${certificate_path}" \
  -k "${keychain_path}" \
  -P "${DESKTOP_MAC_CERTIFICATE_PASSWORD}" \
  -T /usr/bin/codesign \
  -T /usr/bin/security
security set-key-partition-list \
  -S apple-tool:,apple:,codesign: \
  -s \
  -k "${keychain_password}" \
  "${keychain_path}" >/dev/null
security list-keychains -d user -s "${keychain_path}"

identity_output="$(security find-identity -v -p codesigning "${keychain_path}")"
printf '%s\n' "${identity_output}"
identity_lines="$(printf '%s\n' "${identity_output}" | sed -n '/"Developer ID Application:/p')"
identity_count="$(printf '%s\n' "${identity_lines}" | grep -c . || true)"
if [[ "${identity_count}" -ne 1 ]]; then
  echo "The signing archive must contain exactly one valid Developer ID Application identity" >&2
  exit 1
fi

signing_identity="$(printf '%s\n' "${identity_lines}" |
  sed -n 's/^[^"]*"\([^"]*\)".*$/\1/p')"
if [[ -z "${signing_identity}" || "${signing_identity}" != *"(${APPLE_TEAM_ID})" ]]; then
  echo "The Developer ID Application identity does not belong to Apple team ${APPLE_TEAM_ID}" >&2
  exit 1
fi

certificate_subject="$(
  security find-certificate -c "${signing_identity}" -p "${keychain_path}" |
    openssl x509 -noout -subject
)"
if [[ "${certificate_subject}" != *"OU=${APPLE_TEAM_ID}"* ]]; then
  echo "The Developer ID certificate subject does not contain team ${APPLE_TEAM_ID}" >&2
  exit 1
fi

{
  printf 'APPLE_SIGNING_IDENTITY=%s\n' "${signing_identity}"
  printf 'APPLE_API_KEY=%s\n' "${DESKTOP_APPLE_API_KEY_ID}"
  printf 'APPLE_API_ISSUER=%s\n' "${DESKTOP_APPLE_API_ISSUER_ID}"
  printf 'APPLE_API_KEY_PATH=%s\n' "${api_key_path}"
  printf 'OMNIDECK_SIGNING_DIRECTORY=%s\n' "${signing_directory}"
  printf 'OMNIDECK_SIGNING_KEYCHAIN=%s\n' "${keychain_path}"
  printf 'OMNIDECK_SIGNING_CERTIFICATE=%s\n' "${certificate_path}"
} >> "${GITHUB_ENV}"

trap - EXIT
echo "Configured ${signing_identity} for signed and notarized release packaging"
