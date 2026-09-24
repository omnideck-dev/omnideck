#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
desktop_root="$(cd "$script_dir/../.." && pwd)"
repo_root="$(cd "$desktop_root/.." && pwd)"
lab_dir="${OMNIDECK_VM_LAB_DIR:-}"
target=macos-arm64
profile="${OMNIDECK_VM_LAB_PROFILE:-release-clean}"
artifact="${OMNIDECK_DESKTOP_MACOS_ARTIFACT:-}"

usage() {
  printf 'Usage: %s --artifact /path/to/omnideck_aarch64.dmg\n' "$0"
}

while (($#)); do
  case "$1" in
    --artifact) artifact="${2:?--artifact requires a path}"; shift 2 ;;
    --) shift ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$lab_dir" && -x "$lab_dir/lab.sh" ]] || {
  printf 'Set OMNIDECK_VM_LAB_DIR to the deployed OmniDeck VM lab.\n' >&2
  exit 2
}
python3 -c 'import json,subprocess,sys; data=json.loads(subprocess.check_output([sys.argv[1], "capabilities", "--json"])); assert "remote-hosts" in data["features"]' "$lab_dir/lab.sh" || {
  printf 'The deployed lab controller does not support physical hosts.\n' >&2
  exit 2
}

if [[ "${OMNIDECK_VM_LAB_LEASED:-}" != 1 ]]; then
  [[ -n "$artifact" ]] || { usage >&2; exit 2; }
  artifact="$(realpath -e "$artifact")"
  [[ -f "$artifact" && "$artifact" == *.dmg ]] || { printf 'Artifact must be an existing DMG.\n' >&2; exit 2; }
  "$lab_dir/lab.sh" preflight desktop "$profile" --lanes "$target" >/dev/null

  digest="$(shasum -a 256 "$artifact" | awk '{print $1}')"
  cache_key="candidate-dmg-${digest:0:20}"
  cache_dir="$($lab_dir/lab.sh cache-path desktop "$cache_key")"
  mkdir -p "$cache_dir"
  if [[ ! -f "$cache_dir/artifact.dmg" ]]; then
    temporary="$cache_dir/.artifact.dmg.$$"
    cp -- "$artifact" "$temporary"
    [[ "$(shasum -a 256 "$temporary" | awk '{print $1}')" == "$digest" ]]
    mv -- "$temporary" "$cache_dir/artifact.dmg"
    printf '%s  artifact.dmg\n' "$digest" > "$cache_dir/SHA256SUMS"
  fi
  prepared_artifact="$cache_dir/artifact.dmg"

  run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
  source_commit="$(git -C "$repo_root" rev-parse HEAD)"
  output_dir="$($lab_dir/lab.sh artifact-path desktop macos-hardware "$run_id")"
  "$lab_dir/lab.sh" evidence-init "$output_dir" desktop macos-hardware "$run_id" \
    "$source_commit" "$target" runtime-ready "artifactSha256=$digest" "artifactKind=dmg" "architecture=arm64"
  trap '"$lab_dir/lab.sh" evidence-finish "$output_dir" failed >/dev/null 2>&1 || true' EXIT
  status=0
  "$lab_dir/lab.sh" lease "$target" desktop "$run_id" --cleanup-baseline runtime-ready -- env \
    OMNIDECK_DESKTOP_MACOS_ARTIFACT="$prepared_artifact" \
    OMNIDECK_VM_LAB_OUTPUT_DIR="$output_dir" \
    "$0" || status=$?
  trap - EXIT
  if [[ "$status" == 0 ]]; then
    "$lab_dir/lab.sh" evidence-finish "$output_dir" passed
  else
    "$lab_dir/lab.sh" evidence-finish "$output_dir" failed
  fi
  printf 'Evidence: %s\n' "$output_dir"
  exit "$status"
fi

[[ "${OMNIDECK_VM_LAB_VM:-}" == "$target" ]] || {
  printf 'The active lab lease does not own %s.\n' "$target" >&2
  exit 2
}
artifact="${OMNIDECK_DESKTOP_MACOS_ARTIFACT:?Prepared macOS DMG is required}"
output_dir="${OMNIDECK_VM_LAB_OUTPUT_DIR:?Lab evidence directory is required}"
safe_run_id="$(printf '%s' "${OMNIDECK_VM_LAB_RUN_ID}" | tr -cd '[:alnum:]_.-')"
remote_root="/private/tmp/omnideck-desktop-macos-${safe_run_id}"
remote_staged=0

cleanup_remote() {
  local status=$?
  if [[ "$remote_staged" == 1 ]]; then
    case "$remote_root" in
      /private/tmp/omnideck-desktop-macos-[[:alnum:]_.-]*) "$lab_dir/lab.sh" run "$target" rm -rf -- "$remote_root" >/dev/null 2>&1 || true ;;
      *) printf 'Refusing to remove unexpected remote path: %s\n' "$remote_root" >&2; status=1 ;;
    esac
  fi
  exit "$status"
}
trap cleanup_remote EXIT

"$lab_dir/lab.sh" reset "$target" runtime-ready
"$lab_dir/lab.sh" verify "$target"
"$lab_dir/lab.sh" run "$target" mkdir -p \
  "$remote_root/desktop/tests" "$remote_root/desktop/src-tauri/binaries"
remote_staged=1
"$lab_dir/lab.sh" copy-to "$target" "$artifact" "$remote_root/omnideck.dmg"
"$lab_dir/lab.sh" copy-to "$target" "$script_dir" "$remote_root/desktop/tests/hardware"
"$lab_dir/lab.sh" copy-to "$target" "$desktop_root/src-tauri/binaries/vendor-manifest.json" \
  "$remote_root/desktop/src-tauri/binaries/vendor-manifest.json"
"$lab_dir/lab.sh" run "$target" chmod +x \
  "$remote_root/desktop/tests/hardware/run.sh" "$remote_root/desktop/tests/hardware/macos-lab-guest.sh"

test_status=0
"$lab_dir/lab.sh" run "$target" \
  "$remote_root/desktop/tests/hardware/macos-lab-guest.sh" "$remote_root/omnideck.dmg" "$remote_root/artifacts" || test_status=$?
mkdir -p "$output_dir/hardware"
copy_status=0
"$lab_dir/lab.sh" copy-from "$target" "$remote_root/artifacts/." "$output_dir/hardware/" || copy_status=$?
if python3 - "$output_dir/hardware/report.json" "$output_dir/hardware/installation.json" <<'PY'
import json, sys
with open(sys.argv[1]) as handle:
    report = json.load(handle)
with open(sys.argv[2]) as handle:
    installation = json.load(handle)
assert report["result"] == "pass"
assert report["host"] == {"platform": "darwin", "architecture": "arm64"}
assert report["proof"]["ready"] is True
assert installation["schemaVersion"] == 1
assert installation["kind"] == "application"
assert installation["destination"].endswith("/Applications/Omnideck Lab.app")
assert installation["bundleIdentifier"] == "dev.omnideck.desktop"
assert installation["executableSha256"] == report["application"]["sha256"]
assert installation["architecture"] == "arm64"
PY
then
  test_status=0
else
  test_status=1
fi
if [[ "$copy_status" != 0 && ! -f "$output_dir/hardware/report.json" ]]; then
  test_status="$copy_status"
fi
exit "$test_status"
