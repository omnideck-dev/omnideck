#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
desktop_root="$(cd "${script_dir}/../.." && pwd)"
repo_root="$(cd "${desktop_root}/.." && pwd)"
lab_dir="${OMNIDECK_VM_LAB_DIR:-}"
cli_root="${OMNIDECK_CLI_WORKTREE:-}"
baseline=""
artifact=""
assume_yes=0
keep_vm=0
original_args=("$@")

usage() {
  cat <<'EOF'
Usage: ./desktop/tests/e2e/run-windows.sh [OPTIONS]

Build and install the local NSIS candidate in the disposable Windows lab,
then drive trust UI, packaged smoke, setup/hosted/recovery, uninstall, and
reinstall. The clean baseline additionally drives UAC cancellation/approval,
restart-now, a real reboot, and RunOnce reopening.

Options:
  --baseline clean|NAME         Guest checkpoint (default: podman-ready)
  --artifact PATH                Test this exact prebuilt NSIS installer
  --cli PATH                     CLI worktree embedded in a local candidate
  --yes                          Accept the destructive Windows reset
  --keep-vm                      Keep the stopped guest and retained disk/TPM
  -h, --help                     Show this help
EOF
}

while (($#)); do
  case "$1" in
    --) shift ;;
    --baseline) baseline="${2:?--baseline requires a value}"; shift 2 ;;
    --artifact) artifact="${2:?--artifact requires a path}"; shift 2 ;;
    --cli) cli_root="${2:?--cli requires a path}"; shift 2 ;;
    --yes) assume_yes=1; shift ;;
    --keep-vm) keep_vm=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ -n "${lab_dir}" ]] || { printf 'Set OMNIDECK_VM_LAB_DIR to the external VM lab root.\n' >&2; exit 2; }
[[ -x "${lab_dir}/lab.sh" ]] || { printf 'Missing executable lab.sh under %s\n' "${lab_dir}" >&2; exit 2; }
lab_dir="$(cd "${lab_dir}" && pwd -P)"
[[ "$("${lab_dir}/lab.sh" --version 2>/dev/null || true)" == "omnideck-vm-lab 2."* ]] || {
  printf 'Desktop VM E2E requires OmniDeck VM lab controller 2.x.\n' >&2
  exit 2
}
for dependency in curl docker node python3 sha256sum ssh unzip; do
  command -v "${dependency}" >/dev/null 2>&1 || { printf '%s is required.\n' "${dependency}" >&2; exit 2; }
done

if [[ "${OMNIDECK_VM_LAB_LEASED:-}" != "1" ]]; then
  lease_run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
  lease_args=(lease windows desktop "${lease_run_id}")
  [[ "${keep_vm}" != "1" ]] || lease_args+=(--keep-state)
  lease_args+=(-- "$0" "${original_args[@]}")
  exec "${lab_dir}/lab.sh" "${lease_args[@]}"
fi
[[ -n "${baseline}" ]] || baseline="$("${lab_dir}/lab.sh" baseline windows desktop)"
[[ "${baseline}" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || {
  printf 'Unsafe checkpoint name: %s\n' "${baseline}" >&2
  exit 2
}
security_mode=0
[[ "${baseline}" != "clean" ]] || security_mode=1
eval "$("${lab_dir}/lab.sh" describe windows --shell)"

status="$("${lab_dir}/lab.sh" status windows)"
printf '%s\n' "${status}"
grep -Eq '^windows stopped ' <<<"${status}" || {
  printf 'Refusing to use a running Windows guest. Stop it only if you own the lane.\n' >&2
  exit 1
}
windows_snapshots="$("${lab_dir}/lab.sh" snapshots windows)"
grep -Fxq "${baseline}" <<<"${windows_snapshots}" || {
  printf 'The Windows guest has no %s checkpoint.\n' "${baseline}" >&2
  exit 1
}
if [[ "${assume_yes}" != "1" ]]; then
  [[ -t 0 ]] || { printf 'Re-run interactively or pass --yes.\n' >&2; exit 2; }
  printf 'This resets only the stopped Windows VM to %s before the test and clean afterward.\n' "${baseline}"
  printf 'Type windows to continue: '
  read -r confirmation
  [[ "${confirmation}" == "windows" ]] || { printf 'Canceled.\n'; exit 1; }
fi

run_id="${OMNIDECK_VM_LAB_RUN_ID}"
safe_run_id="$(printf '%s' "${run_id}" | tr -cd '[:alnum:]_.-')"
fixture_suffix="$(printf '%s' "${safe_run_id}" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-' | tail -c 28)"
fixture_id="desktop_host_boundary_${fixture_suffix}"
fixture_name="Desktop Host Boundary ${fixture_suffix}"
fixture_filename="Desktop-Host-Boundary-${fixture_suffix}.agent.omnideck.json"
source_commit="$(git -C "${repo_root}" rev-parse --short=12 HEAD)"
cli_commit="${OMNIDECK_DESKTOP_VM_E2E_CLI_COMMIT:-$(node -e 'const m=require(process.argv[1]); process.stdout.write(m.commit)' "${desktop_root}/src-tauri/binaries/vendor-manifest.json")}"
cli_version="${OMNIDECK_DESKTOP_VM_E2E_CLI_VERSION:-$(node -e 'const m=require(process.argv[1]); process.stdout.write(m.version)' "${desktop_root}/src-tauri/binaries/vendor-manifest.json")}"
output_dir="${OMNIDECK_DESKTOP_VM_E2E_OUTPUT_DIR:-${lab_dir}/artifacts/desktop/e2e/${safe_run_id}-windows}"
build_dir="${output_dir}/build"
evidence_dir="${output_dir}/evidence"
screenshot_dir="${output_dir}/screenshots"
marker_root="${output_dir}/markers"
remote_root="C:\\OmnideckDesktopE2E\\${safe_run_id}"
remote_scp_root="C:/OmnideckDesktopE2E/${safe_run_id}"
key_file="${LAB_VM_KEY}"
known_hosts="${LAB_VM_KNOWN_HOSTS}"
ssh_port="${LAB_VM_SSH_PORT}"
driver_forward_port="$((52000 + ($$ % 900)))"
driver_task_name="OmnideckDesktopE2E-${safe_run_id}"
trust_task_name="OmnideckDesktopTrust-${safe_run_id}"
vm_started=0
initial_reset=0
remote_staged=0
driver_ssh_pid=""
test_status=1

mkdir -p "${build_dir}" "${evidence_dir}" "${screenshot_dir}" "${marker_root}"
cp -- "${script_dir}/manual-remainder.json" "${output_dir}/manual-remainder.json"
cp -- "${script_dir}/golden-prerequisites.json" "${output_dir}/golden-prerequisites.json"
"${lab_dir}/lab.sh" evidence-init "${output_dir}" desktop e2e "${safe_run_id}" \
  "${source_commit}" windows "${baseline}" "cliVersion=${cli_version}" "cliCommit=${cli_commit}"

cleanup() {
  local exit_code=$?
  set +e
  if [[ -n "${driver_ssh_pid}" ]] && kill -0 "${driver_ssh_pid}" 2>/dev/null; then
    kill "${driver_ssh_pid}" 2>/dev/null || true
    wait "${driver_ssh_pid}" 2>/dev/null || true
  fi
  if [[ "${vm_started}" == "1" ]]; then
    if [[ "${remote_staged}" == "1" ]]; then
      "${lab_dir}/lab.sh" copy-from windows "${remote_scp_root}/runtime-start.log" "${output_dir}/runtime-start.log" \
        >/dev/null 2>&1 || true
    fi
    "${lab_dir}/lab.sh" run windows \
      "taskkill.exe /F /IM tauri-driver.exe & taskkill.exe /F /IM msedgedriver.exe & taskkill.exe /F /IM omnideck.exe" \
      >/dev/null 2>&1 || true
    "${lab_dir}/lab.sh" run windows \
      "powershell.exe -NoLogo -NoProfile -NonInteractive -Command Unregister-ScheduledTask -TaskName '${driver_task_name}' -Confirm:\$false -ErrorAction SilentlyContinue" \
      >/dev/null 2>&1 || true
    "${lab_dir}/lab.sh" run windows \
      "powershell.exe -NoLogo -NoProfile -NonInteractive -Command Unregister-ScheduledTask -TaskName '${trust_task_name}' -Confirm:\$false -ErrorAction SilentlyContinue" \
      >/dev/null 2>&1 || true
    if [[ "${remote_staged}" == "1" && "${keep_vm}" != "1" ]]; then
      "${lab_dir}/lab.sh" run windows \
        "powershell.exe -NoLogo -NoProfile -NonInteractive -Command Remove-Item -Recurse -Force -ErrorAction SilentlyContinue '${remote_root}'" \
        >/dev/null 2>&1 || true
    fi
    "${lab_dir}/lab.sh" stop windows || exit_code=1
    vm_started=0
  fi
  if [[ "${initial_reset}" == "1" && "${keep_vm}" != "1" ]]; then
    "${lab_dir}/lab.sh" reset windows clean || exit_code=1
  elif [[ "${keep_vm}" == "1" ]]; then
    printf 'Windows guest kept stopped for debugging.\n'
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

printf 'Resetting the leased Windows guest to %s.\n' "${baseline}"
"${lab_dir}/lab.sh" reset windows "${baseline}"
initial_reset=1

printf 'Building Windows tauri-driver 2.0.6.\n'
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp/omnideck-driver-home \
  --env CARGO_HOME=/tmp/omnideck-driver-cargo \
  --env RUSTUP_HOME=/usr/local/rustup \
  --volume "${build_dir}:/out" \
  omnideck-desktop-windows-builder:local \
  bash -c 'mkdir -p "$HOME" "$CARGO_HOME" && cargo install tauri-driver --version 2.0.6 --locked --target x86_64-pc-windows-gnu --root /out/tauri-driver-root'

if [[ -z "${artifact}" ]]; then
  [[ -d "${cli_root}" ]] || { printf 'CLI worktree not found: %s\n' "${cli_root}" >&2; exit 2; }
  printf 'Building the local NSIS candidate from Desktop %s and CLI %s.\n' \
    "${source_commit}" "$(git -C "${cli_root}" rev-parse --short=12 HEAD)"
  "${desktop_root}/scripts/build-with-local-cli-windows.sh" "${cli_root}"
  artifact="$(find "${desktop_root}/src-tauri/target/x86_64-pc-windows-gnu/release/bundle/nsis" \
    -maxdepth 1 -type f -name '*-setup.exe' -print | sort | head -n 1)"
fi
artifact="$(realpath -e "${artifact}")"
artifact_sha256="$(sha256sum "${artifact}" | awk '{print $1}')"
printf '%s  %s\n' "${artifact_sha256}" "$(basename "${artifact}")" > "${build_dir}/artifact.sha256"
"${lab_dir}/lab.sh" evidence-set "${output_dir}" \
  "artifact=$(basename "${artifact}")" "artifactSha256=${artifact_sha256}"

printf 'Starting and verifying Windows.\n'
"${lab_dir}/lab.sh" start windows
vm_started=1
"${lab_dir}/lab.sh" wait windows
"${lab_dir}/lab.sh" verify windows | tee "${output_dir}/guest-verify.txt"
if [[ "${baseline}" == "podman-ready" ]]; then
  grep -Eq 'podman=(ready|present|installed|[A-Za-z]:)|podman_version=' "${output_dir}/guest-verify.txt" || {
    printf 'The podman-ready checkpoint did not report Podman.\n' >&2
    exit 1
  }
fi

"${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/desktop-before.png"
if ! "${lab_dir}/lab.sh" run windows \
  "powershell.exe -NoLogo -NoProfile -NonInteractive -Command if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) { exit 1 }" \
  >/dev/null 2>&1; then
  "${lab_dir}/lab.sh" send-keys windows tab ret
  sleep 1
  "${lab_dir}/lab.sh" send-keys windows o m n i d e c k minus t e s t ret
  sleep 10
fi
"${lab_dir}/lab.sh" run windows \
  "powershell.exe -NoLogo -NoProfile -NonInteractive -Command if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) { exit 1 }"

printf 'Staging and installing the exact NSIS artifact.\n'
"${lab_dir}/lab.sh" run windows "cmd.exe /d /c if not exist ${remote_root} mkdir ${remote_root}"
remote_staged=1
"${lab_dir}/lab.sh" copy-to windows "${artifact}" "${remote_scp_root}/candidate-setup.exe"
"${lab_dir}/lab.sh" copy-to windows "${build_dir}/tauri-driver-root/bin/tauri-driver.exe" "${remote_scp_root}/tauri-driver.exe"
"${lab_dir}/lab.sh" copy-to windows "${script_dir}/windows_guest.ps1" "${remote_scp_root}/windows_guest.ps1"
"${lab_dir}/lab.sh" copy-to windows "${script_dir}/custom_app_fixture.py" "${remote_scp_root}/custom_app_fixture.py"
"${lab_dir}/lab.sh" copy-to windows "${script_dir}/windows_start_driver.ps1" "${remote_scp_root}/windows_start_driver.ps1"
"${lab_dir}/lab.sh" copy-to windows "${script_dir}/windows_trust.ps1" "${remote_scp_root}/windows_trust.ps1"

phase_command() {
  local phase="$1"
  "${lab_dir}/lab.sh" run windows \
    "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ${remote_root}\\windows_guest.ps1 -Phase ${phase} -WorkDir ${remote_root} -ArtifactSha256 ${artifact_sha256} -ExpectedCliVersion ${cli_version} -ExpectedCliCommit ${cli_commit}"
}

trust_launch_visible() {
  "${lab_dir}/lab.sh" run windows \
    "powershell.exe -NoLogo -NoProfile -NonInteractive -Command \"\$deadline = [DateTime]::UtcNow.AddSeconds(45); do { if ((Get-Process consent -ErrorAction SilentlyContinue) -or (Get-Process -Name candidate-setup -ErrorAction SilentlyContinue)) { exit 0 }; Start-Sleep -Milliseconds 250 } while ([DateTime]::UtcNow -lt \$deadline); exit 1\"" \
    >/dev/null 2>&1
}

printf 'Probing the published installer through Windows Attachment Manager and SmartScreen.\n'
"${lab_dir}/lab.sh" run windows \
  "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ${remote_root}\\windows_trust.ps1 -WorkDir ${remote_root}"
# The limited scheduled task launches through the logged-in tester session,
# observes the exact English controls, and drives them with UI Automation. This
# exercises the real internet-zone trust path without keyboard-focus races.
"${lab_dir}/lab.sh" run windows \
  "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ${remote_root}\\windows_trust.ps1 -WorkDir ${remote_root} -RegisterDriver"
warning_captured=0
more_info_captured=0
trust_driver_result=""
for _ in $(seq 1 160); do
  trust_driver_result="$("${lab_dir}/lab.sh" run windows \
    "powershell.exe -NoLogo -NoProfile -NonInteractive -Command \"Get-ChildItem -LiteralPath '${remote_root}\\trust-markers' -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name\"" \
    2>/dev/null | tr -d '\r' || true)"
  if [[ "${warning_captured}" == "0" ]] && grep -Fxq 'warning-observed' <<<"${trust_driver_result}"; then
    "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/smartscreen-warning.png"
    warning_captured=1
  fi
  if [[ "${more_info_captured}" == "0" ]] && grep -Fxq 'more-info-invoked' <<<"${trust_driver_result}"; then
    "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/smartscreen-more-info.png"
    more_info_captured=1
  fi
  if grep -Eq '^(run-anyway-invoked|trusted-without-warning)$' <<<"${trust_driver_result}"; then
    break
  fi
  sleep 0.25
done

if grep -Fxq 'trusted-without-warning' <<<"${trust_driver_result}"; then
  "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/installer-trusted-launch.png"
  trust_result=trusted-without-warning
elif grep -Fxq 'run-anyway-invoked' <<<"${trust_driver_result}"; then
  sleep 4
  "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/smartscreen-after-bypass.png"
  trust_result=warning-bypassed
else
  "${lab_dir}/lab.sh" copy-from windows "${remote_scp_root}/results/trust-driver-error.txt" \
    "${output_dir}/trust-driver-error.txt" >/dev/null 2>&1 || true
  printf 'The interactive SmartScreen driver did not reach an installer decision.\n' >&2
  exit 1
fi

if ! trust_launch_visible; then
  printf 'The interactive trust decision did not reach the installer.\n' >&2
  exit 1
fi
printf '%s\n' "${trust_result}" > "${output_dir}/trust-ui-result.txt"
"${lab_dir}/lab.sh" run windows \
  "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ${remote_root}\\windows_trust.ps1 -WorkDir ${remote_root} -Result ${trust_result}"
"${lab_dir}/lab.sh" send-keys windows esc
"${lab_dir}/lab.sh" run windows \
  "taskkill.exe /F /IM candidate-setup.exe & taskkill.exe /F /IM smartscreen.exe" \
  >/dev/null 2>&1 || true
"${lab_dir}/lab.sh" copy-from windows "${remote_scp_root}/results/trust.json" "${output_dir}/trust.json"

phase_command Prepare | tee "${output_dir}/prepare.log"
if [[ "${security_mode}" == "1" ]]; then
  phase_command ConfigureClean | tee "${output_dir}/configure-clean.log"
fi
application_windows="$("${lab_dir}/lab.sh" run windows \
  "powershell.exe -NoLogo -NoProfile -NonInteractive -Command \"(Get-Content -LiteralPath '${remote_root}\\application-path.txt' -Raw).Trim()\"" | tr -d '\r')"
[[ "${application_windows}" == [A-Za-z]:\\* ]] || {
  printf 'Could not resolve the installed Windows application path: %s\n' "${application_windows}" >&2
  exit 1
}

ssh_options=(
  -i "${key_file}"
  -o "UserKnownHostsFile=${known_hosts}"
  -o StrictHostKeyChecking=yes
  -o BatchMode=yes
  -o ConnectTimeout=8
  -o ExitOnForwardFailure=yes
  -p "${ssh_port}"
  -L "${driver_forward_port}:127.0.0.1:4444"
)
driver_start_count=0
stop_driver() {
  set +e
  if [[ -n "${driver_ssh_pid}" ]] && kill -0 "${driver_ssh_pid}" 2>/dev/null; then
    kill "${driver_ssh_pid}" 2>/dev/null || true
    wait "${driver_ssh_pid}" 2>/dev/null || true
  fi
  driver_ssh_pid=""
  unlink "${output_dir}/driver-tunnel.pid" 2>/dev/null || true
  "${lab_dir}/lab.sh" run windows \
    "taskkill.exe /F /IM tauri-driver.exe & taskkill.exe /F /IM msedgedriver.exe" \
    >/dev/null 2>&1 || true
  "${lab_dir}/lab.sh" run windows \
    "powershell.exe -NoLogo -NoProfile -NonInteractive -Command Unregister-ScheduledTask -TaskName '${driver_task_name}' -Confirm:\$false -ErrorAction SilentlyContinue" \
    >/dev/null 2>&1 || true
  set -e
}

start_driver() {
  local runtime_mode="${1:-reset}"
  local -a register_arguments=()
  case "${runtime_mode}" in
    reset) ;;
    skip) register_arguments+=(-SkipRuntime) ;;
    preserve) register_arguments+=(-PreserveRuntime) ;;
    *) printf 'Unknown Windows driver runtime mode: %s\n' "${runtime_mode}" >&2; return 2 ;;
  esac
  driver_start_count=$((driver_start_count + 1))
  printf 'Starting the native Windows WebView driver (runtime=%s).\n' "${runtime_mode}"
  phase_command Driver | tee -a "${output_dir}/webdriver-refresh.log"
  "${lab_dir}/lab.sh" run windows \
    "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ${remote_root}\\windows_start_driver.ps1 -WorkDir ${remote_root} -Register ${register_arguments[*]}"
  ssh "${ssh_options[@]}" -N tester@127.0.0.1 > "${output_dir}/driver-tunnel-${driver_start_count}.log" 2>&1 &
  driver_ssh_pid=$!
  printf '%s\n' "${driver_ssh_pid}" > "${output_dir}/driver-tunnel.pid"
  for _ in $(seq 1 480); do
    if curl --silent --fail --max-time 2 "http://127.0.0.1:${driver_forward_port}/status" >/dev/null 2>&1; then
      break
    fi
    kill -0 "${driver_ssh_pid}" >/dev/null 2>&1 || {
      tail -100 "${output_dir}/driver-tunnel-${driver_start_count}.log" >&2
      printf 'Windows tauri-driver exited before becoming ready.\n' >&2
      return 1
    }
    if (( _ % 10 == 0 )); then
      task_state="$("${lab_dir}/lab.sh" run windows \
        "powershell.exe -NoLogo -NoProfile -NonInteractive -Command \"(Get-ScheduledTask -TaskName '${driver_task_name}').State\"" \
        2>/dev/null | tr -d '\r' || true)"
      if [[ "${task_state}" != "Running" ]]; then
        "${lab_dir}/lab.sh" copy-from windows "${remote_scp_root}/runtime-start.log" "${output_dir}/runtime-start-${driver_start_count}.log" \
          >/dev/null 2>&1 || true
        tail -100 "${output_dir}/runtime-start-${driver_start_count}.log" 2>/dev/null >&2 || true
        printf 'Windows interactive runtime/driver task stopped before the driver became ready (state=%s).\n' "${task_state:-unknown}" >&2
        return 1
      fi
    fi
    sleep 0.5
  done
  curl --silent --fail --max-time 2 "http://127.0.0.1:${driver_forward_port}/status" >/dev/null
}

wait_for_consent() {
  local attempt
  for attempt in $(seq 1 240); do
    if "${lab_dir}/lab.sh" run windows \
      "powershell.exe -NoLogo -NoProfile -NonInteractive -Command if (Get-Process consent -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  printf 'Windows did not expose the expected consent process.\n' >&2
  return 1
}

if [[ "${security_mode}" == "1" ]]; then
  start_driver skip
else
  start_driver reset
fi

run_journey() {
  local scenario="$1"
  local label="${2:-${scenario}}"
  local restart_action="${3:-later}"
  local uac_mode="${4:-none}"
  local expected_port_conflict="${5:-}"
  local scenario_dir="${evidence_dir}/${label}"
  local marker_dir="${marker_root}/${label}"
  local -a driver_args=()
  if [[ -n "${expected_port_conflict}" ]]; then
    driver_args+=(--expected-port-conflict "${expected_port_conflict}")
  fi
  mkdir -p "${scenario_dir}" "${marker_dir}"
  python3 "${script_dir}/webdriver_client.py" \
    --application "${application_windows}" \
    --external-driver \
    --driver-url "http://127.0.0.1:${driver_forward_port}" \
    --parity "${desktop_root}/src-tauri/setup-parity.json" \
    --mockup-parity "${desktop_root}/tests/fixtures/electron-setup/setup-parity.json" \
    --mockup-html "${desktop_root}/tests/fixtures/electron-setup/index.html" \
    --evidence "${scenario_dir}" \
    --markers "${marker_dir}" \
    --scenario "${scenario}" \
    --restart-action "${restart_action}" \
    "${driver_args[@]}" \
    --timeout 2400 \
    > "${scenario_dir}/session.log" 2>&1 &
  local journey_pid=$!
  declare -A captured=()
  while kill -0 "${journey_pid}" >/dev/null 2>&1; do
    while IFS= read -r marker_path; do
      [[ -n "${marker_path}" ]] || continue
      marker="$(basename "${marker_path}")"
      [[ -z "${captured[${marker}]:-}" ]] || continue
      captured["${marker}"]=1
      "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/${label}-${marker}.png" >/dev/null 2>&1 || true
      if [[ "${uac_mode}" == "cancel-approve" && "${marker}" == "permission-visible" ]]; then
        wait_for_consent
        "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/${label}-uac-cancel.png"
        "${lab_dir}/lab.sh" send-keys windows esc
      elif [[ "${uac_mode}" == "cancel-approve" && "${marker}" == permission-retry-* ]]; then
        wait_for_consent
        "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/${label}-uac-approve.png"
        "${lab_dir}/lab.sh" send-keys windows alt-y
      fi
    done < <(find "${marker_dir}" -maxdepth 1 -type f -print | sort)
    sleep 0.3
  done
  set +e
  wait "${journey_pid}"
  local status=$?
  set -e
  cat "${scenario_dir}/session.log"
  return "${status}"
}

run_host_boundary() {
  local operation="$1"
  local upload_path="${2:-}"
  local scenario_dir="${evidence_dir}/host-boundaries/${operation}"
  local -a operation_args=()
  if [[ "${operation}" == "upload" ]]; then
    operation_args+=(--upload-path "${upload_path}")
  fi
  mkdir -p "${scenario_dir}"
  python3 "${script_dir}/host_boundary_client.py" \
    --application "${application_windows}" \
    --external-driver \
    --driver-url "http://127.0.0.1:${driver_forward_port}" \
    --operation "${operation}" \
    --fixture-id "${fixture_id}" \
    --fixture-name "${fixture_name}" \
    --evidence "${scenario_dir}" \
    "${operation_args[@]}" \
    --timeout 240 \
    > "${scenario_dir}/session.log" 2>&1
}

verify_host_download() {
  "${lab_dir}/lab.sh" run windows \
    "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ${remote_root}\\windows_guest.ps1 -Phase HostBoundaryDownload -WorkDir ${remote_root} -FixtureName \"${fixture_name}\" -FixtureFilename ${fixture_filename}"
}

complete_clean_security_setup() {
  local boot_before boot_after setup_status consent_pid last_consent_pid=""
  boot_before="$("${lab_dir}/lab.sh" run windows \
    "powershell.exe -NoLogo -NoProfile -NonInteractive -Command \"(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')\"" \
    | tr -d '\r')"

  run_journey first-run first-run now cancel-approve
  "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/restart-now-issued.png" >/dev/null 2>&1 || true

  if [[ -n "${driver_ssh_pid}" ]] && kill -0 "${driver_ssh_pid}" 2>/dev/null; then
    kill "${driver_ssh_pid}" 2>/dev/null || true
    wait "${driver_ssh_pid}" 2>/dev/null || true
  fi
  driver_ssh_pid=""

  printf 'Waiting for the restart-now disconnect, reboot, and new Windows boot identity.\n'
  observed_disconnect=0
  for _ in $(seq 1 180); do
    if ! "${lab_dir}/lab.sh" run windows "exit" >/dev/null 2>&1; then
      observed_disconnect=1
      break
    fi
    sleep 0.5
  done
  [[ "${observed_disconnect}" == "1" ]] || {
    printf 'Restart now never disconnected Windows SSH.\n' >&2
    return 1
  }
  "${lab_dir}/lab.sh" wait windows
  "${lab_dir}/lab.sh" verify windows | tee "${output_dir}/guest-verify-after-restart.txt"
  boot_after="$("${lab_dir}/lab.sh" run windows \
    "powershell.exe -NoLogo -NoProfile -NonInteractive -Command \"(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')\"" \
    | tr -d '\r')"
  [[ "${boot_before}" != "${boot_after}" ]] || {
    printf 'Restart now did not produce a new Windows boot identity.\n' >&2
    return 1
  }
  printf 'before=%s\nafter=%s\n' "${boot_before}" "${boot_after}" > "${output_dir}/reboot-proof.txt"

  printf 'Signing into the rebooted graphical session so Windows can consume RunOnce.\n'
  if ! "${lab_dir}/lab.sh" run windows \
    "powershell.exe -NoLogo -NoProfile -NonInteractive -Command if (Get-Process explorer -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" \
    >/dev/null 2>&1; then
    "${lab_dir}/lab.sh" send-keys windows ret
    sleep 1
    "${lab_dir}/lab.sh" send-keys windows o m n i d e c k minus t e s t ret
    for _ in $(seq 1 120); do
      if "${lab_dir}/lab.sh" run windows \
        "powershell.exe -NoLogo -NoProfile -NonInteractive -Command if (Get-Process explorer -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" \
        >/dev/null 2>&1; then
        break
      fi
      sleep 0.5
    done
  fi
  "${lab_dir}/lab.sh" run windows \
    "powershell.exe -NoLogo -NoProfile -NonInteractive -Command if (Get-Process explorer -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"

  printf 'Waiting for RunOnce to reopen the installed app after sign-in.\n'
  for _ in $(seq 1 360); do
    if "${lab_dir}/lab.sh" run windows \
      "powershell.exe -NoLogo -NoProfile -NonInteractive -Command if (Get-Process omnideck -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" \
      >/dev/null 2>&1; then
      break
    fi
    if "${lab_dir}/lab.sh" run windows \
      "powershell.exe -NoLogo -NoProfile -NonInteractive -Command if (Get-Process consent -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" \
      >/dev/null 2>&1; then
      "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/post-reboot-uac-early.png" >/dev/null 2>&1 || true
      "${lab_dir}/lab.sh" send-keys windows alt-y
    fi
    sleep 0.5
  done
  phase_command RunOnceProof | tee "${output_dir}/runonce-proof.log"
  "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/runonce-reopened.png"
  "${lab_dir}/lab.sh" copy-from windows \
    "${remote_scp_root}/results/runonce-proof.json" "${output_dir}/runonce-proof.json"

  printf 'Allowing resumed setup to finish while approving any post-reboot installer prompt.\n'
  setup_status=""
  for _ in $(seq 1 1200); do
    consent_pid="$("${lab_dir}/lab.sh" run windows \
      "powershell.exe -NoLogo -NoProfile -NonInteractive -Command \"(Get-Process consent -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id)\"" \
      2>/dev/null | tr -d '\r' || true)"
    if [[ -n "${consent_pid}" && "${consent_pid}" != "${last_consent_pid}" ]]; then
      last_consent_pid="${consent_pid}"
      "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/post-reboot-uac-${consent_pid}.png" >/dev/null 2>&1 || true
      "${lab_dir}/lab.sh" send-keys windows alt-y
    fi
    setup_status="$(phase_command SetupStatus 2>/dev/null | tr -d '\r' | tail -n 1 || true)"
    [[ "${setup_status}" == "complete" ]] && break
    sleep 2
  done
  [[ "${setup_status}" == "complete" ]] || {
    printf 'RunOnce setup did not reach complete state (last status=%s).\n' "${setup_status:-missing}" >&2
    return 1
  }
  "${lab_dir}/lab.sh" screenshot windows "${screenshot_dir}/runonce-setup-complete.png"
  printf '{"status":"passed","uacCancellation":true,"uacApproval":true,"restartNow":true,"runOnceReopen":true,"bootBefore":"%s","bootAfter":"%s"}\n' \
    "${boot_before}" "${boot_after}" > "${output_dir}/windows-security-summary.json"

  "${lab_dir}/lab.sh" run windows "taskkill.exe /F /IM omnideck.exe" >/dev/null 2>&1 || true
}

set +e
if [[ "${security_mode}" == "1" ]]; then
  (set -Eeuo pipefail; complete_clean_security_setup)
else
  (set -Eeuo pipefail; run_journey first-run)
fi
test_status=$?
set -e

if [[ "${test_status}" == "0" && "${security_mode}" == "1" ]]; then
  stop_driver
  start_driver preserve
fi

if [[ "${test_status}" == "0" ]]; then
  set +e
  (
    set -Eeuo pipefail
    run_journey returning returning-initial
    phase_command Doctor
    run_journey doctor
    phase_command Resume
    run_journey resume
    phase_command Update
    run_journey update
    occupied_port="$(phase_command PortConflict | tr -d '\r' | tail -n 1)"
    [[ "${occupied_port}" =~ ^[0-9]+$ ]]
    run_journey port-conflict port-conflict later none "${occupied_port}"
    phase_command VerifyPortConflict
    run_journey returning returning-final
    phase_command CustomAppFixture
    run_journey custom-app
    run_host_boundary download
    download_path="$(verify_host_download | tr -d '\r' | tail -n 1)"
    [[ "${download_path}" == [A-Za-z]:\\* ]]
    run_host_boundary upload "${download_path}"
    phase_command Final
  )
  test_status=$?
  set -e
fi

"${lab_dir}/lab.sh" copy-from windows "${remote_scp_root}/tauri-driver.stdout.log" "${output_dir}/tauri-driver.stdout.log" \
  >/dev/null 2>&1 || true
"${lab_dir}/lab.sh" copy-from windows "${remote_scp_root}/tauri-driver.stderr.log" "${output_dir}/tauri-driver.stderr.log" \
  >/dev/null 2>&1 || true

"${lab_dir}/lab.sh" run windows \
  "powershell.exe -NoLogo -NoProfile -NonInteractive -Command if (Test-Path '${remote_root}\\results') { Compress-Archive -Force -Path '${remote_root}\\results\\*' -DestinationPath '${remote_root}\\guest-evidence.zip' }" \
  >/dev/null 2>&1 || true
if "${lab_dir}/lab.sh" copy-from windows "${remote_scp_root}/guest-evidence.zip" "${output_dir}/guest-evidence.zip"; then
  mkdir -p "${evidence_dir}/guest"
  unzip_status=0
  unzip -q -o "${output_dir}/guest-evidence.zip" -d "${evidence_dir}/guest" || unzip_status=$?
  case "${unzip_status}" in
    0|1) ;;
    *) printf 'Could not extract Windows evidence (unzip exit %s).\n' "${unzip_status}" >&2; exit "${unzip_status}" ;;
  esac
fi

[[ -f "${evidence_dir}/guest/summary.json" ]] || exit "${test_status}"
python3 - "${evidence_dir}/guest/summary.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8-sig") as stream:
    summary = json.load(stream)
assert summary["status"] == "passed", summary
PY
python3 - "${output_dir}/trust.json" "${output_dir}/trust-ui-result.txt" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8-sig") as stream:
    trust = json.load(stream)
zone_identifier = trust["zoneIdentifier"]
if isinstance(zone_identifier, dict):
    zone_identifier = zone_identifier.get("value", "")
assert "ZoneId=3" in zone_identifier, trust
assert trust["smartScreen"] in {"warning-bypassed", "trusted-without-warning"}, trust
result = open(sys.argv[2], encoding="utf-8").read().strip()
assert result in {"warning-bypassed", "trusted-without-warning"}, result
PY
if [[ "${security_mode}" == "1" ]]; then
  python3 - "${output_dir}/windows-security-summary.json" "${output_dir}/runonce-proof.json" <<'PY'
import json
import sys

security = json.load(open(sys.argv[1], encoding="utf-8"))
proof = json.load(open(sys.argv[2], encoding="utf-8-sig"))
assert security["status"] == "passed", security
assert all(security[key] is True for key in (
    "uacCancellation", "uacApproval", "restartNow", "runOnceReopen"
)), security
assert security["bootBefore"] != security["bootAfter"], security
assert proof["runOnceValueConsumed"] is True, proof
assert proof["interactiveProcessCount"] >= 1, proof
assert proof["setupStatePresent"] is True, proof
PY
fi
node "${desktop_root}/tests/hardware/validate-proof.mjs" \
  --proof "${evidence_dir}/guest/smoke/smoke-proof.json" \
  --application "${artifact}" \
  --report "${evidence_dir}/guest/smoke/report.json"

exit "${test_status}"
