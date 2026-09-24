#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/_lab.sh"
desktop_root="$(cd "${script_dir}/../.." && pwd)"
repo_root="$(cd "${desktop_root}/.." && pwd)"
profile="${OMNIDECK_DESKTOP_VM_E2E_PROFILE:-dev-fast}"
vms_csv="appimage,deb,rpm,atomic"
assume_yes=0
include_native=0
declare -A artifacts=()

usage() {
  cat <<'EOF'
Usage: ./desktop/tests/e2e/smoke-matrix.sh [OPTIONS]

Run supplied Linux packages across the disposable Ubuntu, Debian, Fedora, and
Silverblue guests. Native full-journey cells are skipped by default; this
matrix is for additional package-open compatibility evidence.

Options:
  --appimage PATH              AppImage candidate
  --deb PATH                   DEB candidate
  --rpm PATH                   RPM candidate
  --flatpak PATH               Flatpak bundle (optional; not currently published)
  --vms LIST                   Comma-separated guests (default: appimage,deb,rpm,atomic)
  --profile NAME               Deterministic lab profile (default: dev-fast)
  --include-native             Also smoke native cells already covered by full lanes
  --yes                        Accept all destructive disposable-guest resets
  -h, --help                   Show this help
EOF
}

while (($#)); do
  case "$1" in
    --) shift ;;
    --appimage) artifacts[appimage]="${2:?--appimage requires a path}"; shift 2 ;;
    --deb) artifacts[deb]="${2:?--deb requires a path}"; shift 2 ;;
    --rpm) artifacts[rpm]="${2:?--rpm requires a path}"; shift 2 ;;
    --flatpak) artifacts[flatpak]="${2:?--flatpak requires a path}"; shift 2 ;;
    --vms) vms_csv="${2:?--vms requires a value}"; shift 2 ;;
    --profile) profile="${2:?--profile requires a value}"; shift 2 ;;
    --include-native) include_native=1; shift ;;
    --yes) assume_yes=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "${#artifacts[@]}" -gt 0 ]] || {
  printf 'Supply at least one package artifact.\n' >&2
  usage >&2
  exit 2
}
require_lab
for package_kind in "${!artifacts[@]}"; do
  artifacts[${package_kind}]="$(realpath -e "${artifacts[${package_kind}]}")"
done

IFS=',' read -r -a vms <<<"${vms_csv}"
declare -A selected_vms=()
for vm in "${vms[@]}"; do
  case "${vm}" in
    appimage|deb|rpm|atomic) selected_vms[${vm}]=1 ;;
    *) printf 'Unsupported Linux guest: %s\n' "${vm}" >&2; exit 2 ;;
  esac
done
for vm in appimage deb rpm atomic; do
  [[ -n "${selected_vms[${vm}]:-}" ]] || continue
  vm_status="$("${lab_dir}/lab.sh" status "${vm}")"
  grep -Eq "^${vm} stopped " <<<"${vm_status}" || {
    printf 'Refusing to start the matrix because the %s guest is already running.\n' "${vm}" >&2
    exit 1
  }
done
"${lab_dir}/lab.sh" preflight desktop "${profile}" --lanes "${vms_csv}" >/dev/null

is_native_cell() {
  local guest="$1" package="$2"
  case "${guest}:${package}" in
    appimage:appimage|deb:deb|rpm:rpm|atomic:appimage) return 0 ;;
    *) return 1 ;;
  esac
}

cell_count=0
for vm in appimage deb rpm atomic; do
  [[ -n "${selected_vms[${vm}]:-}" ]] || continue
  for package_kind in appimage deb rpm flatpak; do
    [[ -n "${artifacts[${package_kind}]:-}" ]] || continue
    if [[ "${include_native}" != "1" ]] && is_native_cell "${vm}" "${package_kind}"; then continue; fi
    ((cell_count += 1))
  done
done
[[ "${cell_count}" -gt 0 ]] || { printf 'The selected artifacts and guests contain only skipped native cells. Pass --include-native.\n' >&2; exit 2; }

if [[ "${assume_yes}" != "1" ]]; then
  [[ -t 0 ]] || { printf 'Re-run interactively or pass --yes.\n' >&2; exit 2; }
  printf 'This runs %s smoke cells and resets only stopped disposable guests: %s\n' "${cell_count}" "${vms_csv}"
  printf 'Type smoke-matrix to continue: '
  read -r confirmation
  [[ "${confirmation}" == "smoke-matrix" ]] || { printf 'Canceled.\n'; exit 1; }
fi

run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
safe_run_id="$(printf '%s' "${run_id}" | tr -cd '[:alnum:]_.-')"
source_commit="$(git -C "${script_dir}/../../.." rev-parse --short=12 HEAD)"
run_root="${OMNIDECK_DESKTOP_VM_SMOKE_MATRIX_OUTPUT_DIR:-$("${lab_dir}/lab.sh" artifact-path desktop smoke-matrix "${safe_run_id}")}"
status_file="${run_root}/cell-status.tsv"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p "${run_root}/cells"
: > "${status_file}"
"${lab_dir}/lab.sh" evidence-init "${run_root}" desktop smoke-matrix "${safe_run_id}" \
  "${source_commit}" multi qualification "scope=cross-distro-package-open-smoke" \
  "guests=${vms_csv}" "cellCount=${cell_count}"

matrix_finalized=0
finish_incomplete_matrix() {
  local exit_status=$? evidence_status=failed
  set +e
  if [[ "${matrix_finalized}" != "1" ]]; then
    case "${exit_status}" in
      129|130|143) evidence_status=canceled ;;
    esac
    "${lab_dir}/lab.sh" evidence-finish "${run_root}" "${evidence_status}" || true
    printf 'Cross-distro smoke matrix evidence: %s\n' "${run_root}"
  fi
  return "${exit_status}"
}
trap finish_incomplete_matrix EXIT

record() {
  local guest="$1" package="$2" status="$3" evidence="$4" detail="$5"
  detail="${detail//$'\t'/ }"
  detail="${detail//$'\n'/ }"
  printf '%s\t%s\t%s\t%s\t%s\n' "${guest}" "${package}" "${status}" "${evidence}" "${detail}" >> "${status_file}"
}

for vm in appimage deb rpm atomic; do
  [[ -n "${selected_vms[${vm}]:-}" ]] || continue
  guest_cells=()
  for package_kind in appimage deb rpm flatpak; do
    artifact="${artifacts[${package_kind}]:-}"
    [[ -n "${artifact}" ]] || continue
    if [[ "${include_native}" != "1" ]] && is_native_cell "${vm}" "${package_kind}"; then continue; fi
    guest_cells+=("${package_kind}=${artifact}")
  done
  [[ "${#guest_cells[@]}" -gt 0 ]] || continue
  guest_status=0
  "${lab_dir}/lab.sh" lease "${vm}" desktop-smoke-matrix "${safe_run_id}-${vm}" \
    --cleanup-baseline clean -- \
    "${script_dir}/smoke-matrix-guest.sh" "${vm}" "${profile}" "${run_root}" "${status_file}" \
    "${guest_cells[@]}" || guest_status=$?
  if [[ "${guest_status}" != "0" ]]; then
    record "${vm}" infrastructure failed "cells/${vm}-guest-verify.txt" \
      "grouped guest preparation or cleanup exited ${guest_status}"
  fi
done

report_status=0
python3 "${script_dir}/smoke_matrix_report.py" \
  --status-file "${status_file}" \
  --output "${run_root}" \
  --run-id "${safe_run_id}" \
  --started-at "${started_at}" || report_status=$?
if [[ "${report_status}" == "0" ]]; then
  "${lab_dir}/lab.sh" evidence-finish "${run_root}" passed
else
  "${lab_dir}/lab.sh" evidence-finish "${run_root}" failed || true
fi
matrix_finalized=1
printf 'Cross-distro smoke matrix evidence: %s\n' "${run_root}"
exit "${report_status}"
