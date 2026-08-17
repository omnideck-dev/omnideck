#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
desktop_root="$(cd "$script_dir/../.." && pwd)"
repo_root="$(cd "$desktop_root/.." && pwd)"
lab_dir="${OMNIDECK_VM_LAB_DIR:-}"
target=macos-arm64
profile="${OMNIDECK_VM_LAB_PROFILE:-release-clean}"
artifact="${OMNIDECK_DESKTOP_MACOS_ARTIFACT:-}"
upgrade_from_artifact="${OMNIDECK_DESKTOP_MACOS_UPGRADE_FROM_ARTIFACT:-}"
mode="${OMNIDECK_MACOS_E2E_MODE:-full}"

usage() { printf 'Usage: %s --artifact /path/to/omnideck_aarch64.dmg [--upgrade-from-artifact /path/to/previous.dmg] [--only boundaries]\n' "$0"; }

while (($#)); do
  case "$1" in
    --artifact) artifact="${2:?--artifact requires a path}"; shift 2 ;;
    --upgrade-from-artifact) upgrade_from_artifact="${2:?--upgrade-from-artifact requires a path}"; shift 2 ;;
    --only) [[ "${2:-}" == boundaries ]] || { printf '%s\n' '--only supports boundaries.' >&2; exit 2; }; mode=boundaries; shift 2 ;;
    --) shift ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$lab_dir" && -x "$lab_dir/lab.sh" ]] || {
  printf 'Set OMNIDECK_VM_LAB_DIR to the deployed OmniDeck VM lab.\n' >&2
  exit 2
}

if [[ "${OMNIDECK_VM_LAB_LEASED:-}" != 1 ]]; then
  [[ -n "$artifact" ]] || { usage >&2; exit 2; }
  artifact="$(realpath -e "$artifact")"
  [[ -f "$artifact" && "$artifact" == *.dmg ]] || { printf 'Artifact must be an existing DMG.\n' >&2; exit 2; }
  if [[ -n "$upgrade_from_artifact" ]]; then
    upgrade_from_artifact="$(realpath -e "$upgrade_from_artifact")"
    [[ -f "$upgrade_from_artifact" && "$upgrade_from_artifact" == *.dmg ]] || {
      printf 'Upgrade-from artifact must be an existing DMG.\n' >&2
      exit 2
    }
  fi
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
  prepared_upgrade_from_artifact=""
  upgrade_from_digest="none"
  if [[ -n "$upgrade_from_artifact" ]]; then
    upgrade_from_digest="$(shasum -a 256 "$upgrade_from_artifact" | awk '{print $1}')"
    upgrade_cache_key="upgrade-from-dmg-${upgrade_from_digest:0:20}"
    upgrade_cache_dir="$($lab_dir/lab.sh cache-path desktop "$upgrade_cache_key")"
    mkdir -p "$upgrade_cache_dir"
    if [[ ! -f "$upgrade_cache_dir/artifact.dmg" ]]; then
      upgrade_temporary="$upgrade_cache_dir/.artifact.dmg.$$"
      cp -- "$upgrade_from_artifact" "$upgrade_temporary"
      [[ "$(shasum -a 256 "$upgrade_temporary" | awk '{print $1}')" == "$upgrade_from_digest" ]]
      mv -- "$upgrade_temporary" "$upgrade_cache_dir/artifact.dmg"
      printf '%s  artifact.dmg\n' "$upgrade_from_digest" > "$upgrade_cache_dir/SHA256SUMS"
    fi
    prepared_upgrade_from_artifact="$upgrade_cache_dir/artifact.dmg"
  fi

  run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
  source_commit="$(git -C "$repo_root" rev-parse HEAD)"
  output_dir="$($lab_dir/lab.sh artifact-path desktop macos-e2e "$run_id")"
  "$lab_dir/lab.sh" evidence-init "$output_dir" desktop macos-e2e "$run_id" \
    "$source_commit" "$target" runtime-ready \
    "artifactSha256=$digest" "upgradeFromArtifactSha256=$upgrade_from_digest" \
    "artifactKind=dmg" "architecture=arm64" "driver=accessibility"
  trap '"$lab_dir/lab.sh" evidence-finish "$output_dir" failed >/dev/null 2>&1 || true' EXIT
  status=0
  "$lab_dir/lab.sh" lease "$target" desktop-e2e "$run_id" --cleanup-baseline runtime-ready -- env \
    OMNIDECK_DESKTOP_MACOS_ARTIFACT="$cache_dir/artifact.dmg" \
    OMNIDECK_DESKTOP_MACOS_UPGRADE_FROM_ARTIFACT="$prepared_upgrade_from_artifact" \
    OMNIDECK_VM_LAB_OUTPUT_DIR="$output_dir" \
    OMNIDECK_MACOS_E2E_MODE="$mode" \
    OMNIDECK_MACOS_E2E_SCREENSHOTS="${OMNIDECK_MACOS_E2E_SCREENSHOTS:-1}" \
    "$0" || status=$?
  trap - EXIT
  evidence_status=failed
  [[ "$status" == 0 ]] && evidence_status=passed
  [[ "$status" == 3 ]] && evidence_status=blocked
  "$lab_dir/lab.sh" evidence-finish "$output_dir" "$evidence_status"
  printf 'Evidence: %s\n' "$output_dir"
  exit "$status"
fi

[[ "${OMNIDECK_VM_LAB_VM:-}" == "$target" ]] || { printf 'The active lease does not own %s.\n' "$target" >&2; exit 2; }
artifact="${OMNIDECK_DESKTOP_MACOS_ARTIFACT:?Prepared macOS DMG is required}"
upgrade_from_artifact="${OMNIDECK_DESKTOP_MACOS_UPGRADE_FROM_ARTIFACT:-}"
output_dir="${OMNIDECK_VM_LAB_OUTPUT_DIR:?Lab evidence directory is required}"
safe_run_id="$(printf '%s' "$OMNIDECK_VM_LAB_RUN_ID" | tr -cd '[:alnum:]_.-')"
remote_root="/private/tmp/omnideck-desktop-macos-e2e-${safe_run_id}"
remote_staged=0

cleanup_remote() {
  local status=$?
  if [[ "$remote_staged" == 1 ]]; then
    case "$remote_root" in
      /private/tmp/omnideck-desktop-macos-e2e-[[:alnum:]_.-]*)
        "$lab_dir/lab.sh" run "$target" rm -rf -- "$remote_root" >/dev/null 2>&1 || true ;;
      *) printf 'Refusing to remove unexpected remote path: %s\n' "$remote_root" >&2; status=1 ;;
    esac
  fi
  exit "$status"
}
trap cleanup_remote EXIT

"$lab_dir/lab.sh" reset "$target" runtime-ready
"$lab_dir/lab.sh" verify "$target"
"$lab_dir/lab.sh" run "$target" mkdir -p \
  "$remote_root/desktop/tests/e2e" "$remote_root/desktop/tests/hardware" \
  "$remote_root/desktop/src-tauri/binaries"
remote_staged=1
"$lab_dir/lab.sh" copy-to "$target" "$artifact" "$remote_root/omnideck.dmg"
if [[ -n "$upgrade_from_artifact" ]]; then
  "$lab_dir/lab.sh" copy-to "$target" "$upgrade_from_artifact" "$remote_root/upgrade-from.dmg"
fi
"$lab_dir/lab.sh" copy-to "$target" "$script_dir/macos_accessibility_guest.sh" "$remote_root/desktop/tests/e2e/macos_accessibility_guest.sh"
"$lab_dir/lab.sh" copy-to "$target" "$script_dir/custom_app_fixture.py" "$remote_root/desktop/tests/e2e/custom_app_fixture.py"
"$lab_dir/lab.sh" copy-to "$target" "$desktop_root/tests/hardware/run.sh" "$remote_root/desktop/tests/hardware/run.sh"
"$lab_dir/lab.sh" copy-to "$target" "$desktop_root/tests/hardware/validate-proof.mjs" "$remote_root/desktop/tests/hardware/validate-proof.mjs"
"$lab_dir/lab.sh" copy-to "$target" "$desktop_root/src-tauri/binaries/vendor-manifest.json" "$remote_root/desktop/src-tauri/binaries/vendor-manifest.json"
"$lab_dir/lab.sh" copy-to "$target" "$desktop_root/src-tauri/setup-parity.json" "$remote_root/desktop/src-tauri/setup-parity.json"
"$lab_dir/lab.sh" run "$target" chmod 755 \
  "$remote_root/desktop/tests/e2e/macos_accessibility_guest.sh" "$remote_root/desktop/tests/hardware/run.sh"

test_status=0
"$lab_dir/lab.sh" run "$target" env \
  "OMNIDECK_MACOS_E2E_SCREENSHOTS=${OMNIDECK_MACOS_E2E_SCREENSHOTS:-1}" \
  "OMNIDECK_MACOS_E2E_MODE=${OMNIDECK_MACOS_E2E_MODE:-full}" \
  "$remote_root/desktop/tests/e2e/macos_accessibility_guest.sh" \
  "$remote_root" "$remote_root/omnideck.dmg" "$remote_root/results" \
  "$(if [[ -n "$upgrade_from_artifact" ]]; then printf '%s' "$remote_root/upgrade-from.dmg"; else printf 'none'; fi)" || test_status=$?
mkdir -p "$output_dir/e2e"
"$lab_dir/lab.sh" copy-from "$target" "$remote_root/results/." "$output_dir/e2e/" || true

if [[ -f "$output_dir/e2e/summary.json" ]]; then
  python3 - "$output_dir/e2e/summary.json" <<'PY' || test_status=1
import json, sys
with open(sys.argv[1]) as handle:
    summary = json.load(handle)
assert summary["status"] == "passed", summary
assert summary["platform"] == "darwin", summary
assert summary["architecture"] == "arm64", summary
assert summary["driver"] == "macos-accessibility", summary
PY
fi
exit "$test_status"
