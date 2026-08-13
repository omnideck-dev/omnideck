#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
desktop_root="$(cd "${script_dir}/../.." && pwd)"
repo_root="$(cd "${desktop_root}/.." && pwd)"
source "${script_dir}/_lab.sh"
lanes_csv="${OMNIDECK_DESKTOP_VM_E2E_LANES:-appimage,deb,rpm,atomic,windows}"
profile="${OMNIDECK_DESKTOP_VM_E2E_PROFILE:-dev-fast}"
cli_root="${OMNIDECK_CLI_WORKTREE:-}"
assume_yes=0

while (($#)); do
  case "$1" in
    --lanes) lanes_csv="${2:?--lanes requires a value}"; shift 2 ;;
    --profile) profile="${2:?--profile requires a value}"; shift 2 ;;
    --cli) cli_root="${2:?--cli requires a value}"; shift 2 ;;
    --yes) assume_yes=1; shift ;;
    -h|--help) printf 'Usage: %s --cli PATH [--lanes LIST] [--profile NAME] [--yes]\n' "$0"; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

[[ -d "$cli_root" ]] || { printf 'Pass --cli PATH or set OMNIDECK_CLI_WORKTREE.\n' >&2; exit 2; }
require_lab
for dependency in docker node python3 sha256sum; do
  command -v "$dependency" >/dev/null 2>&1 || { printf '%s is required.\n' "$dependency" >&2; exit 2; }
done
IFS=',' read -r -a lanes <<<"$lanes_csv"
declare -A selected=() artifact_by_kind=()
linux_bundles=()
for lane in "${lanes[@]}"; do
  case "$lane" in appimage|deb|rpm|atomic|windows) ;; *) printf 'Unsupported lane: %s\n' "$lane" >&2; exit 2 ;; esac
  selected["$lane"]=1
done
"${lab_dir}/lab.sh" preflight desktop "$profile" --lanes "$lanes_csv" >/dev/null

run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
run_root="$("${lab_dir}/lab.sh" artifact-path desktop candidate-matrix "$run_id")"
status_file="${run_root}/lane-status.tsv"
mkdir -p "${run_root}/lanes"
: > "$status_file"
desktop_source_state
"${lab_dir}/lab.sh" evidence-init "$run_root" desktop candidate-matrix "$run_id" \
  "$source_commit" multi qualification "phase=preparing" "profile=${profile}" \
  "lanes=${lanes_csv}" "sourceDirty=${source_dirty}" "sourceFingerprint=${source_fingerprint}"
finalized=0
finish_incomplete() {
  local exit_status=$?
  set +e
  if [[ "$finalized" != 1 ]]; then
    "${lab_dir}/lab.sh" evidence-finish "$run_root" failed || true
    printf 'Desktop candidate matrix evidence: %s\n' "$run_root"
  fi
  return "$exit_status"
}
trap finish_incomplete EXIT

[[ -z "${selected[appimage]:-}${selected[atomic]:-}" ]] || linux_bundles+=(appimage)
[[ -z "${selected[deb]:-}" ]] || linux_bundles+=(deb)
[[ -z "${selected[rpm]:-}" ]] || linux_bundles+=(rpm)
ensure_cli_builder
if [[ "${#linux_bundles[@]}" -gt 0 ]]; then
  ensure_desktop_builder linux
  create_desktop_build_output linux
  bundle_csv="$(IFS=,; printf '%s' "${linux_bundles[*]}")"
  printf 'Building all requested Linux packages once before leasing any guest.\n'
  OMNIDECK_CLI_BUILDER_IMAGE="$cli_builder_image" \
  OMNIDECK_DESKTOP_BUILDER_IMAGE="$desktop_builder_image" \
  OMNIDECK_DESKTOP_BUILD_OUTPUT_DIR="$desktop_build_output" \
    "${desktop_root}/scripts/build-with-local-cli.sh" "$cli_root" \
    "pnpm exec tauri build --bundles ${bundle_csv} --target x86_64-unknown-linux-gnu"
  for kind in "${linux_bundles[@]}"; do
    case "$kind" in
      appimage) glob='*.AppImage' ;;
      deb) glob='*.deb' ;;
      rpm) glob='*.rpm' ;;
    esac
    built="$(find "${desktop_build_output}/x86_64-unknown-linux-gnu/release/bundle/${kind}" -maxdepth 1 -type f -name "$glob" -print | sort | head -n 1)"
    [[ -n "$built" ]] || { printf 'Missing built %s candidate.\n' "$kind" >&2; exit 1; }
    cache_candidate_artifact "$built" "$kind"
    artifact_by_kind["$kind"]="$prepared_artifact"
  done
  remove_desktop_build_output
fi
if [[ -n "${selected[windows]:-}" ]]; then
  ensure_desktop_builder windows
  create_desktop_build_output windows
  printf 'Building the requested Windows package once before leasing its guest.\n'
  OMNIDECK_CLI_BUILDER_IMAGE="$cli_builder_image" \
  OMNIDECK_DESKTOP_WINDOWS_BUILDER_IMAGE="$desktop_builder_image" \
  OMNIDECK_DESKTOP_BUILD_OUTPUT_DIR="$desktop_build_output" \
    "${desktop_root}/scripts/build-with-local-cli-windows.sh" "$cli_root"
  built="$(find "${desktop_build_output}/x86_64-pc-windows-gnu/release/bundle/nsis" -maxdepth 1 -type f -name '*-setup.exe' -print | sort | head -n 1)"
  [[ -n "$built" ]] || { printf 'Missing built Windows candidate.\n' >&2; exit 1; }
  cache_candidate_artifact "$built" nsis
  artifact_by_kind[windows]="$prepared_artifact"
  remove_desktop_build_output
fi
"${lab_dir}/lab.sh" evidence-set "$run_root" "phase=prepared"

status=0
for lane in "${lanes[@]}"; do
  case "$lane" in
    appimage|atomic) artifact="${artifact_by_kind[appimage]}" ;;
    deb) artifact="${artifact_by_kind[deb]}" ;;
    rpm) artifact="${artifact_by_kind[rpm]}" ;;
    windows) artifact="${artifact_by_kind[windows]}" ;;
  esac
  arguments=(--vm "$lane" --profile "$profile" --cli "$cli_root" --artifact "$artifact")
  [[ "$assume_yes" == 0 ]] || arguments+=(--yes)
  lane_status=0
  lane_dir="${run_root}/lanes/${lane}"
  mkdir -p "$lane_dir"
  OMNIDECK_DESKTOP_VM_E2E_OUTPUT_DIR="$lane_dir" \
    "$script_dir/run.sh" "${arguments[@]}" > >(tee "${lane_dir}/host.log") 2>&1 || lane_status=$?
  if [[ "$lane_status" == 0 ]]; then
    printf '%s\tpassed\tlanes/%s\n' "$lane" "$lane" >> "$status_file"
  else
    printf '%s\tfailed\tlanes/%s\n' "$lane" "$lane" >> "$status_file"
    status=1
  fi
done
if [[ "$status" == 0 ]]; then
  "${lab_dir}/lab.sh" evidence-finish "$run_root" passed
else
  "${lab_dir}/lab.sh" evidence-finish "$run_root" failed || true
fi
finalized=1
printf 'Desktop candidate matrix evidence: %s\n' "$run_root"
exit "$status"
