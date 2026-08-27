#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "notarize-macos-dmg.sh must run on macOS" >&2
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

required_variables=(APPLE_API_KEY APPLE_API_ISSUER APPLE_API_KEY_PATH)
for variable in "${required_variables[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Required notarization input ${variable} is not set" >&2
    exit 1
  fi
done

desktop_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dmg_directory="${desktop_root}/src-tauri/target/${target}/release/bundle/dmg"

shopt -s nullglob
dmgs=("${dmg_directory}/"*.dmg)
shopt -u nullglob
if [[ "${#dmgs[@]}" -ne 1 ]]; then
  echo "expected exactly one DMG under ${dmg_directory}, found ${#dmgs[@]}" >&2
  exit 1
fi

echo "Submitting final disk image to Apple's notary service: ${dmgs[0]}"
submission_json="$(
  xcrun notarytool submit "${dmgs[0]}" \
    --key "${APPLE_API_KEY_PATH}" \
    --key-id "${APPLE_API_KEY}" \
    --issuer "${APPLE_API_ISSUER}" \
    --wait \
    --output-format json
)"
printf '%s\n' "${submission_json}"

submission_status="$(
  printf '%s' "${submission_json}" |
    node -e '
      let input = "";
      process.stdin.setEncoding("utf8");
      process.stdin.on("data", (chunk) => { input += chunk; });
      process.stdin.on("end", () => {
        const submission = JSON.parse(input);
        process.stdout.write(String(submission.status || ""));
      });
    '
)"
if [[ "${submission_status}" != "Accepted" ]]; then
  echo "Apple notarization did not accept ${dmgs[0]} (status: ${submission_status:-missing})" >&2
  exit 1
fi

echo "Stapling notarization ticket to ${dmgs[0]}"
xcrun stapler staple -v "${dmgs[0]}"
xcrun stapler validate -v "${dmgs[0]}"
