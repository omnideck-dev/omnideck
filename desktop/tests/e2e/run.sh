#!/usr/bin/env bash

set -Eeuo pipefail

original_args=("$@")

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
desktop_root="$(cd "${script_dir}/../.." && pwd)"
repo_root="$(cd "${desktop_root}/.." && pwd)"
lab_dir="${OMNIDECK_VM_LAB_DIR:-}"
cli_root="${OMNIDECK_CLI_WORKTREE:-}"
vm="${OMNIDECK_DESKTOP_VM_E2E_VM:-appimage}"
baseline="${OMNIDECK_DESKTOP_VM_E2E_BASELINE:-}"
artifact=""
assume_yes=0
keep_vm=0
original_args=("$@")

usage() {
  cat <<'EOF'
Usage: ./desktop/tests/e2e/run.sh [OPTIONS]

Build a release-shaped Desktop package, reset a disposable local-lab guest,
then run packaged smoke plus attended setup/hosted/recovery journeys.

Options:
  --vm appimage|deb|rpm|atomic|windows  Package/guest lane (default: appimage)
  --baseline NAME              Guest checkpoint (default: recommended available Linux checkpoint)
  --artifact PATH               Test this exact prebuilt package instead
  --cli PATH                    CLI worktree embedded in a local candidate
  --yes                         Accept the destructive guest reset
  --keep-vm                     Keep the stopped guest and retained overlays
  -h, --help                    Show this help
EOF
}

while (($#)); do
  case "$1" in
    --) shift ;;
    --vm) vm="${2:?--vm requires a value}"; shift 2 ;;
    --baseline) baseline="${2:?--baseline requires a value}"; shift 2 ;;
    --artifact) artifact="${2:?--artifact requires a path}"; shift 2 ;;
    --cli) cli_root="${2:?--cli requires a path}"; shift 2 ;;
    --yes) assume_yes=1; shift ;;
    --keep-vm) keep_vm=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "${vm}" == "windows" ]]; then
  arguments=()
  [[ -n "${baseline}" ]] && arguments+=(--baseline "${baseline}")
  [[ -n "${cli_root}" ]] && arguments+=(--cli "${cli_root}")
  [[ -n "${artifact}" ]] && arguments+=(--artifact "${artifact}")
  [[ "${assume_yes}" == "1" ]] && arguments+=(--yes)
  [[ "${keep_vm}" == "1" ]] && arguments+=(--keep-vm)
  exec "${script_dir}/run-windows.sh" "${arguments[@]}"
fi

case "${vm}" in
  appimage|ubuntu) vm=appimage; bundle=appimage; artifact_glob='*.AppImage' ;;
  deb|debian) vm=deb; bundle=deb; artifact_glob='*.deb' ;;
  rpm|fedora) vm=rpm; bundle=rpm; artifact_glob='*.rpm' ;;
  atomic|silverblue) vm=atomic; bundle=appimage; artifact_glob='*.AppImage' ;;
  *) printf 'Unsupported Desktop VM lane: %s\n' "${vm}" >&2; exit 2 ;;
esac

[[ -n "${lab_dir}" ]] || { printf 'Set OMNIDECK_VM_LAB_DIR to the external VM lab root.\n' >&2; exit 2; }
[[ -x "${lab_dir}/lab.sh" ]] || { printf 'Missing executable lab.sh under %s\n' "${lab_dir}" >&2; exit 2; }
lab_dir="$(cd "${lab_dir}" && pwd -P)"
[[ "$("${lab_dir}/lab.sh" --version 2>/dev/null || true)" == "omnideck-vm-lab 2."* ]] || {
  printf 'Desktop VM E2E requires OmniDeck VM lab controller 2.x.\n' >&2
  exit 2
}
for dependency in docker node python3 sha256sum ssh tar; do
  command -v "${dependency}" >/dev/null 2>&1 || { printf '%s is required.\n' "${dependency}" >&2; exit 2; }
done

if [[ "${OMNIDECK_VM_LAB_LEASED:-}" != "1" ]]; then
  lease_run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
  lease_args=(lease "${vm}" desktop "${lease_run_id}")
  [[ "${keep_vm}" != "1" ]] || lease_args+=(--keep-state)
  lease_args+=(-- "$0" "${original_args[@]}")
  exec "${lab_dir}/lab.sh" "${lease_args[@]}"
fi
eval "$("${lab_dir}/lab.sh" describe "${vm}" --shell)"
ssh_port="${LAB_VM_SSH_PORT}"

[[ -n "${baseline}" ]] || baseline="$("${lab_dir}/lab.sh" baseline "${vm}" desktop)"
[[ "${baseline}" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || {
  printf 'Unsafe checkpoint name: %s\n' "${baseline}" >&2
  exit 2
}

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
  printf 'This resets only the stopped %s VM to %s before the test and clean afterward.\n' "${vm}" "${baseline}"
  printf 'Type %s to continue: ' "${vm}"
  read -r confirmation
  [[ "${confirmation}" == "${vm}" ]] || { printf 'Canceled.\n'; exit 1; }
fi

run_id="${OMNIDECK_VM_LAB_RUN_ID}"
safe_run_id="$(printf '%s' "${run_id}" | tr -cd '[:alnum:]_.-')"
source_commit="$(git -C "${repo_root}" rev-parse --short=12 HEAD)"
cli_commit="${OMNIDECK_DESKTOP_VM_E2E_CLI_COMMIT:-$(node -e 'const m=require(process.argv[1]); process.stdout.write(m.commit)' "${desktop_root}/src-tauri/binaries/vendor-manifest.json")}"
cli_version="${OMNIDECK_DESKTOP_VM_E2E_CLI_VERSION:-$(node -e 'const m=require(process.argv[1]); process.stdout.write(m.version)' "${desktop_root}/src-tauri/binaries/vendor-manifest.json")}"
namespace="de2e-$(printf '%s' "${safe_run_id}" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-' | tail -c 28)"
output_dir="${OMNIDECK_DESKTOP_VM_E2E_OUTPUT_DIR:-${lab_dir}/artifacts/desktop/e2e/${safe_run_id}-${vm}}"
build_dir="${output_dir}/build"
screenshot_dir="${output_dir}/screenshots"
remote_root="/home/tester/omnideck-desktop-e2e-${safe_run_id}"
key_file="${LAB_VM_KEY}"
known_hosts="${LAB_VM_KNOWN_HOSTS}"
vm_started=0
initial_reset=0
remote_staged=0
test_status=1

mkdir -p "${build_dir}" "${screenshot_dir}"
cp -- "${script_dir}/manual-remainder.json" "${output_dir}/manual-remainder.json"
cp -- "${script_dir}/golden-prerequisites.json" "${output_dir}/golden-prerequisites.json"
"${lab_dir}/lab.sh" evidence-init "${output_dir}" desktop e2e "${safe_run_id}" \
  "${source_commit}" "${vm}" "${baseline}" "cliVersion=${cli_version}" "cliCommit=${cli_commit}"

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
  printf 'Desktop E2E artifacts: %s\n' "${output_dir}"
  exit "${exit_code}"
}
trap cleanup EXIT

printf 'Resetting the leased %s guest to %s.\n' "${vm}" "${baseline}"
"${lab_dir}/lab.sh" reset "${vm}" "${baseline}"
initial_reset=1

printf 'Building native tauri-driver 2.0.6 for the guest.\n'
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp/omnideck-driver-home \
  --env CARGO_HOME=/tmp/omnideck-driver-cargo \
  --env RUSTUP_HOME=/usr/local/rustup \
  --volume "${build_dir}:/out" \
  omnideck-desktop-linux-builder:local \
  bash -c 'mkdir -p "$HOME" "$CARGO_HOME" && cargo install tauri-driver --version 2.0.6 --locked --root /out/tauri-driver-root'

if [[ -z "${artifact}" ]]; then
  [[ -d "${cli_root}" ]] || { printf 'CLI worktree not found: %s\n' "${cli_root}" >&2; exit 2; }
  printf 'Building the local %s candidate from Desktop %s and CLI %s.\n' \
    "${bundle}" "${source_commit}" "$(git -C "${cli_root}" rev-parse --short=12 HEAD)"
  "${desktop_root}/scripts/build-with-local-cli.sh" "${cli_root}" \
    "pnpm exec tauri build --bundles ${bundle} --target x86_64-unknown-linux-gnu"
  bundle_dir="${desktop_root}/src-tauri/target/x86_64-unknown-linux-gnu/release/bundle/${bundle}"
  artifact="$(find "${bundle_dir}" -maxdepth 1 -type f -name "${artifact_glob}" -print | sort | head -n 1)"
fi
artifact="$(realpath -e "${artifact}")"
artifact_sha256="$(sha256sum "${artifact}" | awk '{print $1}')"
printf '%s  %s\n' "${artifact_sha256}" "$(basename "${artifact}")" > "${build_dir}/artifact.sha256"
"${lab_dir}/lab.sh" evidence-set "${output_dir}" \
  "artifact=$(basename "${artifact}")" "artifactSha256=${artifact_sha256}"

printf 'Starting and verifying the %s guest.\n' "${vm}"
"${lab_dir}/lab.sh" start "${vm}"
vm_started=1
"${lab_dir}/lab.sh" wait "${vm}"
"${lab_dir}/lab.sh" verify "${vm}" | tee "${output_dir}/guest-verify.txt"
if [[ "${baseline}" == "podman-ready" ]]; then
  grep -Eq 'podman=(ready|present|installed|/)|podman_version=' "${output_dir}/guest-verify.txt" || {
    printf 'The podman-ready checkpoint did not report Podman.\n' >&2
    exit 1
  }
fi

printf 'Starting an isolated graphical tester session.\n'
"${lab_dir}/lab.sh" screenshot "${vm}" "${screenshot_dir}/login.png"
gdm_config='[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin=tester\n'
if [[ "${vm}" == "atomic" ]]; then
  gdm_config='[daemon]\nWaylandEnable=false\nAutomaticLoginEnable=true\nAutomaticLogin=tester\n'
fi
if [[ "${vm}" == "atomic" ]] ||
  ! "${lab_dir}/lab.sh" run "${vm}" "loginctl list-sessions --no-legend | grep -Eq 'tester[[:space:]]+seat0'" >/dev/null 2>&1; then
  # Console key synthesis is deliberately avoided here: keyboard layouts and
  # GDM animations can alter or discard a disposable password. This file lives
  # only in the throwaway overlay and the final clean reset removes it.
  "${lab_dir}/lab.sh" run "${vm}" \
    "if test -f /etc/gdm3/daemon.conf; then config=/etc/gdm3/daemon.conf; elif test -d /etc/gdm3; then config=/etc/gdm3/custom.conf; else config=/etc/gdm/custom.conf; fi; printf '${gdm_config}' | sudo tee \"\$config\" >/dev/null && sudo systemctl restart display-manager"
fi
for _ in $(seq 1 90); do
  if "${lab_dir}/lab.sh" run "${vm}" "loginctl list-sessions --no-legend | grep -Eq 'tester[[:space:]]+seat0'" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
"${lab_dir}/lab.sh" run "${vm}" "loginctl list-sessions --no-legend | grep -Eq 'tester[[:space:]]+seat0'"
for _ in $(seq 1 90); do
  if "${lab_dir}/lab.sh" run "${vm}" "pgrep -u tester -x gnome-shell >/dev/null" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
"${lab_dir}/lab.sh" run "${vm}" "pgrep -u tester -x gnome-shell >/dev/null"
sleep 5
"${lab_dir}/lab.sh" screenshot "${vm}" "${screenshot_dir}/desktop.png"

printf 'Staging the exact artifact and dependency-free driver.\n'
"${lab_dir}/lab.sh" run "${vm}" "mkdir -p '${remote_root}/markers'"
remote_staged=1
"${lab_dir}/lab.sh" copy-to "${vm}" "${artifact}" "${remote_root}/candidate.${bundle}"
"${lab_dir}/lab.sh" copy-to "${vm}" "${build_dir}/tauri-driver-root/bin/tauri-driver" "${remote_root}/tauri-driver"
"${lab_dir}/lab.sh" copy-to "${vm}" "${script_dir}/webdriver_client.py" "${remote_root}/webdriver_client.py"
"${lab_dir}/lab.sh" copy-to "${vm}" "${script_dir}/custom_app_fixture.py" "${remote_root}/custom_app_fixture.py"
"${lab_dir}/lab.sh" copy-to "${vm}" "${script_dir}/host_boundary_client.py" "${remote_root}/host_boundary_client.py"
"${lab_dir}/lab.sh" copy-to "${vm}" "${script_dir}/polkit_agent.py" "${remote_root}/polkit_agent.py"
"${lab_dir}/lab.sh" copy-to "${vm}" "${script_dir}/linux_guest.sh" "${remote_root}/linux_guest.sh"
"${lab_dir}/lab.sh" copy-to "${vm}" "${desktop_root}/src-tauri/setup-parity.json" "${remote_root}/setup-parity.json"
"${lab_dir}/lab.sh" copy-to "${vm}" "${desktop_root}/tests/fixtures/electron-setup/setup-parity.json" "${remote_root}/mockup-parity.json"
"${lab_dir}/lab.sh" copy-to "${vm}" "${desktop_root}/tests/fixtures/electron-setup/index.html" "${remote_root}/mockup-index.html"

ssh_options=(
  -i "${key_file}"
  -o "UserKnownHostsFile=${known_hosts}"
  -o StrictHostKeyChecking=yes
  -o BatchMode=yes
  -o ConnectTimeout=8
  -p "${ssh_port}"
)
remote_command="chmod 755 '${remote_root}/tauri-driver' '${remote_root}/webdriver_client.py' '${remote_root}/custom_app_fixture.py' '${remote_root}/host_boundary_client.py' '${remote_root}/polkit_agent.py' '${remote_root}/linux_guest.sh' && '${remote_root}/linux_guest.sh' '${remote_root}' '${bundle}' '${namespace}' '${artifact_sha256}' '${cli_version}' '${cli_commit}'"

printf 'Running packaged smoke and attended Desktop journeys.\n'
printf 'mode=target-scoped-pkttyagent; trigger=polkit-password; response=disposable-guest-password\n' \
  > "${output_dir}/authentication-driver.txt"
set +e
ssh "${ssh_options[@]}" tester@127.0.0.1 "${remote_command}" \
  > "${output_dir}/guest-session.log" 2>&1 &
journey_pid=$!
set -e

declare -A captured=()
permission_handled=0
while kill -0 "${journey_pid}" >/dev/null 2>&1; do
  marker_listing="$("${lab_dir}/lab.sh" run "${vm}" "find '${remote_root}/markers' -maxdepth 1 -type f -printf '%f\\n' 2>/dev/null | sort" 2>/dev/null || true)"
  while IFS= read -r marker; do
    [[ -n "${marker}" && -z "${captured[${marker}]:-}" ]] || continue
    captured["${marker}"]=1
    safe_marker="$(printf '%s' "${marker}" | tr -cd '[:alnum:]_.-')"
    "${lab_dir}/lab.sh" screenshot "${vm}" "${screenshot_dir}/${safe_marker}.png" >/dev/null 2>&1 || true
    if [[ "${marker}" == "permission-visible" && "${permission_handled}" == "0" ]]; then
      permission_handled=1
      sleep 2
      "${lab_dir}/lab.sh" screenshot "${vm}" "${screenshot_dir}/permission-prompt.png" >/dev/null 2>&1 || true
    fi
  done <<<"${marker_listing}"
  sleep 0.35
done
set +e
wait "${journey_pid}"
test_status=$?
set -e
tail -200 "${output_dir}/guest-session.log"

if "${lab_dir}/lab.sh" copy-from "${vm}" "${remote_root}/evidence.tar.gz" "${output_dir}/evidence.tar.gz"; then
  mkdir -p "${output_dir}/evidence"
  tar -xzf "${output_dir}/evidence.tar.gz" -C "${output_dir}/evidence"
fi

[[ -f "${output_dir}/evidence/summary.json" ]] || exit "${test_status}"
python3 - "${output_dir}/evidence/summary.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    summary = json.load(stream)
assert summary["status"] == "passed", summary
PY

node "${desktop_root}/tests/hardware/validate-proof.mjs" \
  --proof "${output_dir}/evidence/smoke/smoke-proof.json" \
  --application "${artifact}" \
  --report "${output_dir}/evidence/smoke/report.json"

exit "${test_status}"
