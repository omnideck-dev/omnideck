#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab_dir="${OMNIDECK_VM_LAB_DIR:-}"
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
[[ -n "${lab_dir}" ]] || { printf 'Set OMNIDECK_VM_LAB_DIR to the external VM lab root.\n' >&2; exit 2; }
[[ -x "${lab_dir}/lab.sh" ]] || { printf 'Missing executable lab.sh under %s\n' "${lab_dir}" >&2; exit 2; }
lab_dir="$(cd "${lab_dir}" && pwd -P)"
[[ "$("${lab_dir}/lab.sh" --version 2>/dev/null || true)" == "omnideck-vm-lab 2."* ]] || {
  printf 'Desktop smoke matrix requires OmniDeck VM lab controller 2.x.\n' >&2
  exit 2
}
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
run_root="${OMNIDECK_DESKTOP_VM_SMOKE_MATRIX_OUTPUT_DIR:-${lab_dir}/artifacts/desktop/smoke-matrix/${safe_run_id}}"
status_file="${run_root}/cell-status.tsv"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p "${run_root}/cells"
: > "${status_file}"
"${lab_dir}/lab.sh" evidence-init "${run_root}" desktop smoke-matrix "${safe_run_id}" \
  "${source_commit}" multi qualification "scope=cross-distro-package-open-smoke" \
  "guests=${vms_csv}" "cellCount=${cell_count}"

record() {
  local guest="$1" package="$2" status="$3" evidence="$4" detail="$5"
  detail="${detail//$'\t'/ }"
  detail="${detail//$'\n'/ }"
  printf '%s\t%s\t%s\t%s\t%s\n' "${guest}" "${package}" "${status}" "${evidence}" "${detail}" >> "${status_file}"
}

for vm in appimage deb rpm atomic; do
  [[ -n "${selected_vms[${vm}]:-}" ]] || continue
  for package_kind in appimage deb rpm flatpak; do
    artifact="${artifacts[${package_kind}]:-}"
    [[ -n "${artifact}" ]] || continue
    if [[ "${include_native}" != "1" ]] && is_native_cell "${vm}" "${package_kind}"; then continue; fi
    cell_name="${vm}-${package_kind}"
    cell_dir="${run_root}/cells/${cell_name}"
    mkdir -p "${cell_dir}"
    printf 'Running %s package smoke on the %s guest.\n' "${package_kind}" "${vm}"
    cell_status=0
    OMNIDECK_DESKTOP_VM_SMOKE_OUTPUT_DIR="${cell_dir}" \
      "${script_dir}/run-package-smoke.sh" \
        --vm "${vm}" \
        --package "${package_kind}" \
        --artifact "${artifact}" \
        --yes > >(tee "${cell_dir}/host.log") 2>&1 || cell_status=$?
    if [[ "${cell_status}" == "0" ]]; then
      record "${vm}" "${package_kind}" passed "cells/${cell_name}" "package opened and completed its read-only smoke"
    else
      record "${vm}" "${package_kind}" failed "cells/${cell_name}" "package smoke exited ${cell_status}"
    fi
  done
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
printf 'Cross-distro smoke matrix evidence: %s\n' "${run_root}"
exit "${report_status}"
