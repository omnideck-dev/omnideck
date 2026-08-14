#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_dir}/_lab.sh"

vm="${1:?guest is required}"
profile="${2:?profile is required}"
run_root="${3:?run root is required}"
status_file="${4:?status file is required}"
shift 4

[[ "${OMNIDECK_VM_LAB_LEASED:-}" == "1" ]] || {
  printf 'smoke-matrix-guest.sh must run under a lab lease.\n' >&2
  exit 2
}
baseline="$("${lab_dir}/lab.sh" profile "${profile}" "${vm}")"
vm_started=0
initial_reset=0

cleanup_guest() {
  local exit_status=$?
  set +e
  if [[ "${vm_started}" == "1" ]]; then
    "${lab_dir}/lab.sh" stop "${vm}" || exit_status=1
    vm_started=0
  fi
  if [[ "${initial_reset}" == "1" ]]; then
    "${lab_dir}/lab.sh" reset "${vm}" clean || exit_status=1
  fi
  exit "${exit_status}"
}
trap cleanup_guest EXIT

printf 'Preparing %s once for %s grouped smoke cell(s).\n' "${vm}" "$#"
"${lab_dir}/lab.sh" reset "${vm}" "${baseline}"
initial_reset=1
"${lab_dir}/lab.sh" start "${vm}"
vm_started=1
"${lab_dir}/lab.sh" wait "${vm}"
"${lab_dir}/lab.sh" verify "${vm}" | tee "${run_root}/cells/${vm}-guest-verify.txt"

for cell in "$@"; do
  package_kind="${cell%%=*}"
  artifact="${cell#*=}"
  cell_name="${vm}-${package_kind}"
  cell_dir="${run_root}/cells/${cell_name}"
  mkdir -p "${cell_dir}"
  printf 'Running %s package smoke on the already-started %s guest.\n' "${package_kind}" "${vm}"
  cell_status=0
  OMNIDECK_DESKTOP_VM_SMOKE_REUSE_GUEST=1 \
  OMNIDECK_DESKTOP_VM_SMOKE_OUTPUT_DIR="${cell_dir}" \
    "${script_dir}/run-package-smoke.sh" \
      --vm "${vm}" \
      --package "${package_kind}" \
      --profile "${profile}" \
      --baseline "${baseline}" \
      --artifact "${artifact}" \
      --yes > >(tee "${cell_dir}/host.log") 2>&1 || cell_status=$?
  if [[ "${cell_status}" == "0" ]]; then
    printf '%s\t%s\tpassed\tcells/%s\tpackage opened and completed its read-only smoke\n' \
      "${vm}" "${package_kind}" "${cell_name}" >> "${status_file}"
  else
    printf '%s\t%s\tfailed\tcells/%s\tpackage smoke exited %s\n' \
      "${vm}" "${package_kind}" "${cell_name}" "${cell_status}" >> "${status_file}"
  fi
done
