#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
desktop_root="$(cd "${script_dir}/../.." && pwd)"
repo_root="$(cd "${desktop_root}/.." && pwd)"
lab_dir="${OMNIDECK_VM_LAB_DIR:-}"
vm=""
baseline=""
artifact=""
package_kind=""
expected_cli_version="${OMNIDECK_DESKTOP_VM_E2E_CLI_VERSION:-$(node -e 'const m=require(process.argv[1]); process.stdout.write(m.version)' "${desktop_root}/src-tauri/binaries/vendor-manifest.json")}"
expected_cli_commit="${OMNIDECK_DESKTOP_VM_E2E_CLI_COMMIT:-$(node -e 'const m=require(process.argv[1]); process.stdout.write(m.commit)' "${desktop_root}/src-tauri/binaries/vendor-manifest.json")}"
assume_yes=0
keep_vm=0
original_args=("$@")

usage() {
  cat <<'EOF'
Usage: ./desktop/tests/e2e/run-package-smoke.sh [OPTIONS]

Launch one Linux package in one disposable VM and require the read-only
packaged smoke proof. This deliberately skips setup, WebDriver, recovery, and
package lifecycle journeys.

Options:
  --vm appimage|deb|rpm|atomic       Guest distro (required)
  --artifact PATH                    Exact AppImage, DEB, RPM, or Flatpak bundle (required)
  --package appimage|deb|rpm|flatpak Override package type inferred from PATH
  --baseline NAME                    Guest checkpoint (default: recommended available checkpoint)
  --cli-version VERSION              Expected bundled CLI version
  --cli-commit COMMIT                Expected bundled CLI commit
  --yes                              Accept the destructive guest reset
  --keep-vm                          Keep the stopped guest and retained overlays
  -h, --help                         Show this help
EOF
}

while (($#)); do
  case "$1" in
    --) shift ;;
    --vm) vm="${2:?--vm requires a value}"; shift 2 ;;
    --artifact) artifact="${2:?--artifact requires a path}"; shift 2 ;;
    --package) package_kind="${2:?--package requires a value}"; shift 2 ;;
    --baseline) baseline="${2:?--baseline requires a value}"; shift 2 ;;
    --cli-version) expected_cli_version="${2:?--cli-version requires a value}"; shift 2 ;;
    --cli-commit) expected_cli_commit="${2:?--cli-commit requires a value}"; shift 2 ;;
    --yes) assume_yes=1; shift ;;
    --keep-vm) keep_vm=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

case "${vm}" in
  appimage|ubuntu) vm=appimage ;;
  deb|debian) vm=deb ;;
  rpm|fedora) vm=rpm ;;
  atomic|silverblue) vm=atomic ;;
  *) printf 'Select a Linux guest with --vm appimage|deb|rpm|atomic.\n' >&2; exit 2 ;;
esac
[[ -n "${artifact}" ]] || { printf '%s\n' '--artifact is required.' >&2; exit 2; }
artifact="$(realpath -e "${artifact}")"
[[ -f "${artifact}" ]] || { printf 'Artifact is not a regular file: %s\n' "${artifact}" >&2; exit 2; }
if [[ -z "${package_kind}" ]]; then
  case "${artifact}" in
    *.AppImage|*.appimage) package_kind="appimage" ;;
    *.deb) package_kind="deb" ;;
    *.rpm) package_kind="rpm" ;;
    *.flatpak) package_kind="flatpak" ;;
    *) printf 'Cannot infer package type from %s; pass --package.\n' "${artifact}" >&2; exit 2 ;;
  esac
fi
case "${package_kind}" in
  appimage|deb|rpm|flatpak) ;;
  *) printf 'Unsupported package type: %s\n' "${package_kind}" >&2; exit 2 ;;
esac
[[ "${expected_cli_version}" =~ ^v?[0-9A-Za-z][0-9A-Za-z._+-]*$ ]] || {
  printf 'Unsafe expected CLI version: %s\n' "${expected_cli_version}" >&2
  exit 2
}
[[ "${expected_cli_commit}" =~ ^[0-9A-Fa-f]{7,64}$ ]] || {
  printf 'Unsafe expected CLI commit: %s\n' "${expected_cli_commit}" >&2
  exit 2
}

[[ -n "${lab_dir}" ]] || { printf 'Set OMNIDECK_VM_LAB_DIR to the external VM lab root.\n' >&2; exit 2; }
[[ -x "${lab_dir}/lab.sh" ]] || { printf 'Missing executable lab.sh under %s\n' "${lab_dir}" >&2; exit 2; }
lab_dir="$(cd "${lab_dir}" && pwd -P)"
[[ "$("${lab_dir}/lab.sh" --version 2>/dev/null || true)" == "omnideck-vm-lab 2."* ]] || {
  printf 'Desktop package smoke requires OmniDeck VM lab controller 2.x.\n' >&2
  exit 2
}
for dependency in node python3 sha256sum ssh tar; do
  command -v "${dependency}" >/dev/null 2>&1 || { printf '%s is required.\n' "${dependency}" >&2; exit 2; }
done

if [[ "${OMNIDECK_VM_LAB_LEASED:-}" != "1" ]]; then
  lease_run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
  lease_args=(lease "${vm}" desktop-smoke "${lease_run_id}")
  [[ "${keep_vm}" != "1" ]] || lease_args+=(--keep-state)
  lease_args+=(-- "$0" "${original_args[@]}")
  exec "${lab_dir}/lab.sh" "${lease_args[@]}"
fi
eval "$("${lab_dir}/lab.sh" describe "${vm}" --shell)"
ssh_port="${LAB_VM_SSH_PORT}"

[[ -n "${baseline}" ]] || baseline="$("${lab_dir}/lab.sh" baseline "${vm}" desktop)"
[[ "${baseline}" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || { printf 'Unsafe checkpoint name: %s\n' "${baseline}" >&2; exit 2; }

status="$("${lab_dir}/lab.sh" status "${vm}")"
printf '%s\n' "${status}"
grep -Eq "^${vm} stopped " <<<"${status}" || {
  printf 'Refusing to use a running guest. Stop it only if you own that VM lane.\n' >&2
  exit 1
}
"${lab_dir}/lab.sh" snapshots "${vm}" | grep -Fxq "${baseline}" || {
  printf 'The %s guest has no %s checkpoint.\n' "${vm}" "${baseline}" >&2
  exit 1
}
if [[ "${assume_yes}" != "1" ]]; then
  [[ -t 0 ]] || { printf 'Re-run interactively or pass --yes.\n' >&2; exit 2; }
  printf 'This resets only the stopped %s VM to %s before the smoke and clean afterward.\n' "${vm}" "${baseline}"
  printf 'Type %s to continue: ' "${vm}"
  read -r confirmation
  [[ "${confirmation}" == "${vm}" ]] || { printf 'Canceled.\n'; exit 1; }
fi

run_id="${OMNIDECK_VM_LAB_RUN_ID}"
safe_run_id="$(printf '%s' "${run_id}" | tr -cd '[:alnum:]_.-')"
source_commit="$(git -C "${repo_root}" rev-parse --short=12 HEAD)"
artifact_sha256="$(sha256sum "${artifact}" | awk '{print $1}')"
output_dir="${OMNIDECK_DESKTOP_VM_SMOKE_OUTPUT_DIR:-${lab_dir}/artifacts/desktop/package-smoke/${safe_run_id}-${vm}-${package_kind}}"
screenshot_dir="${output_dir}/screenshots"
remote_root="/home/tester/omnideck-desktop-smoke-${safe_run_id}"
key_file="${LAB_VM_KEY}"
known_hosts="${LAB_VM_KNOWN_HOSTS}"
vm_started=0
initial_reset=0
remote_staged=0

mkdir -p "${output_dir}" "${screenshot_dir}"
"${lab_dir}/lab.sh" evidence-init "${output_dir}" desktop package-smoke "${safe_run_id}" \
  "${source_commit}" "${vm}" "${baseline}" "packageKind=${package_kind}" \
  "artifact=$(basename "${artifact}")" "artifactSha256=${artifact_sha256}" "scope=launch-smoke"

cleanup() {
  local exit_code=$?
  set +e
  if [[ "${remote_staged}" == "1" && "${vm_started}" == "1" && "${keep_vm}" != "1" ]]; then
    "${lab_dir}/lab.sh" run "${vm}" "rm -rf -- '${remote_root}'" >/dev/null 2>&1 || true
  fi
  if [[ "${vm_started}" == "1" ]]; then
    "${lab_dir}/lab.sh" stop "${vm}" || exit_code=1
    vm_started=0
  fi
  if [[ "${initial_reset}" == "1" && "${keep_vm}" != "1" ]]; then
    "${lab_dir}/lab.sh" reset "${vm}" clean || exit_code=1
  elif [[ "${keep_vm}" == "1" ]]; then
    printf 'Guest kept stopped for debugging: %s\n' "${vm}"
  fi
  if [[ "${exit_code}" == "0" ]]; then
    "${lab_dir}/lab.sh" evidence-finish "${output_dir}" passed || exit_code=1
  else
    "${lab_dir}/lab.sh" evidence-finish "${output_dir}" failed || true
  fi
  printf 'Cross-distro package smoke artifacts: %s\n' "${output_dir}"
  exit "${exit_code}"
}
trap cleanup EXIT

printf 'Resetting the leased %s guest to %s.\n' "${vm}" "${baseline}"
"${lab_dir}/lab.sh" reset "${vm}" "${baseline}"
initial_reset=1
printf 'Starting and verifying the %s guest.\n' "${vm}"
"${lab_dir}/lab.sh" start "${vm}"
vm_started=1
"${lab_dir}/lab.sh" wait "${vm}"
"${lab_dir}/lab.sh" verify "${vm}" | tee "${output_dir}/guest-verify.txt"

printf 'Starting an isolated graphical tester session.\n'
"${lab_dir}/lab.sh" screenshot "${vm}" "${screenshot_dir}/login.png"
gdm_config='[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin=tester\n'
if [[ "${vm}" == "atomic" ]]; then
  gdm_config='[daemon]\nWaylandEnable=false\nAutomaticLoginEnable=true\nAutomaticLogin=tester\n'
fi
if [[ "${vm}" == "atomic" ]] ||
  ! "${lab_dir}/lab.sh" run "${vm}" "loginctl list-sessions --no-legend | grep -Eq 'tester[[:space:]]+seat0'" >/dev/null 2>&1; then
  "${lab_dir}/lab.sh" run "${vm}" \
    "if test -f /etc/gdm3/daemon.conf; then config=/etc/gdm3/daemon.conf; elif test -d /etc/gdm3; then config=/etc/gdm3/custom.conf; else config=/etc/gdm/custom.conf; fi; printf '${gdm_config}' | sudo tee \"\$config\" >/dev/null && sudo systemctl restart display-manager"
fi
for _ in $(seq 1 90); do
  if "${lab_dir}/lab.sh" run "${vm}" "pgrep -u tester -x gnome-shell >/dev/null" >/dev/null 2>&1; then break; fi
  sleep 1
done
"${lab_dir}/lab.sh" run "${vm}" "pgrep -u tester -x gnome-shell >/dev/null"
sleep 3
"${lab_dir}/lab.sh" screenshot "${vm}" "${screenshot_dir}/desktop.png"

printf 'Staging the exact %s artifact and smoke harness.\n' "${package_kind}"
"${lab_dir}/lab.sh" run "${vm}" "mkdir -p '${remote_root}/markers'"
remote_staged=1
"${lab_dir}/lab.sh" copy-to "${vm}" "${artifact}" "${remote_root}/candidate.${package_kind}"
"${lab_dir}/lab.sh" copy-to "${vm}" "${script_dir}/linux_package_smoke.sh" "${remote_root}/linux_package_smoke.sh"

ssh_options=(
  -i "${key_file}"
  -o "UserKnownHostsFile=${known_hosts}"
  -o StrictHostKeyChecking=yes
  -o BatchMode=yes
  -o ConnectTimeout=8
  -p "${ssh_port}"
)
remote_command="chmod 755 '${remote_root}/linux_package_smoke.sh' && '${remote_root}/linux_package_smoke.sh' '${remote_root}' '${package_kind}' '${artifact_sha256}' '${expected_cli_version}' '${expected_cli_commit}'"
printf 'Running only the package-open smoke on %s.\n' "${vm}"
set +e
ssh "${ssh_options[@]}" tester@127.0.0.1 "${remote_command}" > "${output_dir}/guest-session.log" 2>&1 &
smoke_pid=$!
set -e
screenshot_captured=0
while kill -0 "${smoke_pid}" >/dev/null 2>&1; do
  if [[ "${screenshot_captured}" == "0" ]] &&
    "${lab_dir}/lab.sh" run "${vm}" "test -f '${remote_root}/markers/smoke-proof-created'" >/dev/null 2>&1; then
    screenshot_captured=1
    "${lab_dir}/lab.sh" screenshot "${vm}" "${screenshot_dir}/package-opened.png" >/dev/null 2>&1 || true
  fi
  sleep 0.25
done
set +e
wait "${smoke_pid}"
test_status=$?
set -e
tail -200 "${output_dir}/guest-session.log"

if "${lab_dir}/lab.sh" copy-from "${vm}" "${remote_root}/evidence.tar.gz" "${output_dir}/evidence.tar.gz"; then
  mkdir -p "${output_dir}/evidence"
  tar -xzf "${output_dir}/evidence.tar.gz" -C "${output_dir}/evidence"
fi
[[ -f "${output_dir}/evidence/summary.json" ]] || exit "${test_status}"
python3 - "${output_dir}/evidence/summary.json" "${package_kind}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    summary = json.load(stream)
assert summary["status"] == "passed", summary
assert summary["packageKind"] == sys.argv[2], summary
PY
exit "${test_status}"
