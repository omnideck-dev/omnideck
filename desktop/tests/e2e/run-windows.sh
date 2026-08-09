#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
desktop_root="$(cd "${script_dir}/../.." && pwd)"
repo_root="$(cd "${desktop_root}/.." && pwd)"
lab_dir="${OMNIDECK_VM_LAB_DIR:-}"
cli_root="${OMNIDECK_CLI_WORKTREE:-}"
baseline="podman-ready"
artifact=""
assume_yes=0
keep_vm=0

usage() {
  cat <<'EOF'
Usage: ./desktop/tests/e2e/run-windows.sh [OPTIONS]

Build and install the local NSIS candidate in the disposable Windows lab,
then drive packaged smoke, setup/hosted/recovery, uninstall, and reinstall.

Options:
  --baseline NAME               Guest checkpoint (default: podman-ready)
  --artifact PATH                Test this exact prebuilt NSIS installer
  --cli PATH                     CLI worktree embedded in a local candidate
  --yes                          Accept the destructive Windows reset
  --keep-vm                      Keep the stopped guest and retained disk/TPM
  -h, --help                     Show this help
EOF
}

while (($#)); do
  case "$1" in
    --baseline) baseline="${2:?--baseline requires a value}"; shift 2 ;;
    --artifact) artifact="${2:?--artifact requires a path}"; shift 2 ;;
    --cli) cli_root="${2:?--cli requires a path}"; shift 2 ;;
    --yes) assume_yes=1; shift ;;
    --keep-vm) keep_vm=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ "${baseline}" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || {
  printf 'Unsafe checkpoint name: %s\n' "${baseline}" >&2
  exit 2
}
if [[ "${baseline}" == "clean" ]]; then
  printf 'The automated Windows lane starts at podman-ready. Use desktop/tests/manual/clean-first-run.md for the real UAC/restart path.\n' >&2
  exit 2
fi

[[ -n "${lab_dir}" ]] || { printf 'Set OMNIDECK_VM_LAB_DIR to the external VM lab root.\n' >&2; exit 2; }
[[ -x "${lab_dir}/lab.sh" ]] || { printf 'Missing executable lab.sh under %s\n' "${lab_dir}" >&2; exit 2; }
lab_dir="$(cd "${lab_dir}" && pwd -P)"
for dependency in curl docker flock node python3 sha256sum ssh unzip; do
  command -v "${dependency}" >/dev/null 2>&1 || { printf '%s is required.\n' "${dependency}" >&2; exit 2; }
done

status="$("${lab_dir}/lab.sh" status windows)"
printf '%s\n' "${status}"
grep -Eq '^windows stopped ' <<<"${status}" || {
  printf 'Refusing to use a running Windows guest. Stop it only if you own the lane.\n' >&2
  exit 1
}
"${lab_dir}/lab.sh" snapshots windows | grep -Fxq "${baseline}" || {
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

exec 9>"${TMPDIR:-/tmp}/omnideck-cli-vm-e2e-windows.lock"
flock -n 9 || { printf 'The Windows lane is leased by the CLI E2E suite.\n' >&2; exit 1; }
exec 8>"${TMPDIR:-/tmp}/omnideck-desktop-vm-e2e-windows.lock"
flock -n 8 || { printf 'The Windows Desktop lane is already leased.\n' >&2; exit 1; }

run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
safe_run_id="$(printf '%s' "${run_id}" | tr -cd '[:alnum:]_.-')"
source_commit="$(git -C "${repo_root}" rev-parse --short=12 HEAD)"
cli_commit="$(node -e 'const m=require(process.argv[1]); process.stdout.write(m.commit)' "${desktop_root}/src-tauri/binaries/vendor-manifest.json")"
cli_version="$(node -e 'const m=require(process.argv[1]); process.stdout.write(m.version)' "${desktop_root}/src-tauri/binaries/vendor-manifest.json")"
output_dir="${OMNIDECK_DESKTOP_VM_E2E_OUTPUT_DIR:-${lab_dir}/artifacts/desktop-e2e/${safe_run_id}-windows}"
build_dir="${output_dir}/build"
evidence_dir="${output_dir}/evidence"
screenshot_dir="${output_dir}/screenshots"
marker_root="${output_dir}/markers"
remote_root="C:\\OmnideckDesktopE2E\\${safe_run_id}"
remote_scp_root="C:/OmnideckDesktopE2E/${safe_run_id}"
key_file="${lab_dir}/keys/id_ed25519"
known_hosts="${lab_dir}/runtime/known_hosts"
ssh_port=2225
driver_forward_port="$((52000 + ($$ % 900)))"
driver_task_name="OmnideckDesktopE2E-${safe_run_id}"
discarded_before="${output_dir}/discarded-before.txt"
discarded_after="${output_dir}/discarded-after.txt"
discarded_created="${output_dir}/discarded-created.txt"
vm_started=0
initial_reset=0
remote_staged=0
driver_ssh_pid=""
test_status=1

mkdir -p "${build_dir}" "${evidence_dir}" "${screenshot_dir}" "${marker_root}"
cp -- "${script_dir}/manual-remainder.json" "${output_dir}/manual-remainder.json"
cp -- "${script_dir}/golden-prerequisites.json" "${output_dir}/golden-prerequisites.json"
find "${lab_dir}/discarded" -maxdepth 1 \
  \( -type f -name 'windows.qcow2.*' -o -type d -name 'windows-tpm.*' \) \
  -print | sort > "${discarded_before}"
printf '{\n  "runId": "%s",\n  "vm": "windows",\n  "baseline": "%s",\n  "sourceCommit": "%s",\n  "status": "building"\n}\n' \
  "${safe_run_id}" "${baseline}" "${source_commit}" > "${output_dir}/run.json"

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
  find "${lab_dir}/discarded" -maxdepth 1 \
    \( -type f -name 'windows.qcow2.*' -o -type d -name 'windows-tpm.*' \) \
    -print | sort > "${discarded_after}"
  comm -13 "${discarded_before}" "${discarded_after}" > "${discarded_created}"
  if [[ "${exit_code}" == "0" && "${keep_vm}" != "1" ]]; then
    while IFS= read -r path; do
      [[ -n "${path}" ]] || continue
      [[ "$(dirname "${path}")" == "${lab_dir}/discarded" ]] || {
        printf 'Refusing unexpected discarded path: %s\n' "${path}" >&2
        exit_code=1
        continue
      }
      case "$(basename "${path}")" in
        windows.qcow2.*) [[ -f "${path}" ]] && unlink "${path}" ;;
        windows-tpm.*) [[ -d "${path}" ]] && rm -r -- "${path}" ;;
        *) printf 'Refusing unexpected discarded name: %s\n' "${path}" >&2; exit_code=1 ;;
      esac
    done < "${discarded_created}"
    printf 'Windows disk and TPM state created by this successful run were purged.\n'
  elif [[ -s "${discarded_created}" ]]; then
    printf 'Debug disk/TPM retained. Purge with: %s %s\n' "${script_dir}/purge.sh" "${output_dir}"
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
printf '{\n  "runId": "%s",\n  "vm": "windows",\n  "baseline": "%s",\n  "sourceCommit": "%s",\n  "cliVersion": "%s",\n  "cliCommit": "%s",\n  "artifact": "%s",\n  "artifactSha256": "%s"\n}\n' \
  "${safe_run_id}" "${baseline}" "${source_commit}" "${cli_version}" "${cli_commit}" \
  "$(basename "${artifact}")" "${artifact_sha256}" > "${output_dir}/run.json"

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
  "${lab_dir}/lab.sh" send-keys windows ret
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
"${lab_dir}/lab.sh" copy-to windows "${script_dir}/windows_start_driver.ps1" "${remote_scp_root}/windows_start_driver.ps1"

phase_command() {
  local phase="$1"
  "${lab_dir}/lab.sh" run windows \
    "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ${remote_root}\\windows_guest.ps1 -Phase ${phase} -WorkDir ${remote_root} -ArtifactSha256 ${artifact_sha256} -ExpectedCliVersion ${cli_version} -ExpectedCliCommit ${cli_commit}"
}

phase_command Prepare | tee "${output_dir}/prepare.log"
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
printf 'Starting the native Windows WebView driver.\n'
"${lab_dir}/lab.sh" run windows \
  "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ${remote_root}\\windows_start_driver.ps1 -WorkDir ${remote_root} -Register"
ssh "${ssh_options[@]}" -N tester@127.0.0.1 > "${output_dir}/driver-tunnel.log" 2>&1 &
driver_ssh_pid=$!
for _ in $(seq 1 480); do
  if curl --silent --fail --max-time 2 "http://127.0.0.1:${driver_forward_port}/status" >/dev/null 2>&1; then
    break
  fi
  kill -0 "${driver_ssh_pid}" >/dev/null 2>&1 || {
    tail -100 "${output_dir}/driver-tunnel.log" >&2
    printf 'Windows tauri-driver exited before becoming ready.\n' >&2
    exit 1
  }
  if (( _ % 10 == 0 )); then
    task_state="$("${lab_dir}/lab.sh" run windows \
      "powershell.exe -NoLogo -NoProfile -NonInteractive -Command \"(Get-ScheduledTask -TaskName '${driver_task_name}').State\"" \
      2>/dev/null | tr -d '\r' || true)"
    if [[ "${task_state}" != "Running" ]]; then
      "${lab_dir}/lab.sh" copy-from windows "${remote_scp_root}/runtime-start.log" "${output_dir}/runtime-start.log" \
        >/dev/null 2>&1 || true
      tail -100 "${output_dir}/runtime-start.log" 2>/dev/null >&2 || true
      printf 'Windows interactive runtime/driver task stopped before the driver became ready (state=%s).\n' "${task_state:-unknown}" >&2
      exit 1
    fi
  fi
  sleep 0.5
done
curl --silent --fail --max-time 2 "http://127.0.0.1:${driver_forward_port}/status" >/dev/null

run_journey() {
  local scenario="$1"
  local label="${2:-${scenario}}"
  local scenario_dir="${evidence_dir}/${label}"
  local marker_dir="${marker_root}/${label}"
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

set +e
(
  set -Eeuo pipefail
  run_journey first-run
  run_journey returning returning-initial
  phase_command Doctor
  run_journey doctor
  phase_command Resume
  run_journey resume
  phase_command Update
  run_journey update
  run_journey returning returning-final
  phase_command Final
)
test_status=$?
set -e

"${lab_dir}/lab.sh" copy-from windows "${remote_scp_root}/tauri-driver.stdout.log" "${output_dir}/tauri-driver.stdout.log" \
  >/dev/null 2>&1 || true
"${lab_dir}/lab.sh" copy-from windows "${remote_scp_root}/tauri-driver.stderr.log" "${output_dir}/tauri-driver.stderr.log" \
  >/dev/null 2>&1 || true

"${lab_dir}/lab.sh" run windows \
  "powershell.exe -NoLogo -NoProfile -NonInteractive -Command if (Test-Path '${remote_root}\\results') { Compress-Archive -Force -Path '${remote_root}\\results\\*' -DestinationPath '${remote_root}\\guest-evidence.zip' }" \
  >/dev/null 2>&1 || true
if "${lab_dir}/lab.sh" copy-from windows "${remote_scp_root}/guest-evidence.zip" "${output_dir}/guest-evidence.zip"; then
  mkdir -p "${evidence_dir}/guest"
  unzip -q -o "${output_dir}/guest-evidence.zip" -d "${evidence_dir}/guest"
fi

[[ -f "${evidence_dir}/guest/summary.json" ]] || exit "${test_status}"
python3 - "${evidence_dir}/guest/summary.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8-sig") as stream:
    summary = json.load(stream)
assert summary["status"] == "passed", summary
PY
node "${desktop_root}/tests/hardware/validate-proof.mjs" \
  --proof "${evidence_dir}/guest/smoke/smoke-proof.json" \
  --application "${artifact}" \
  --report "${evidence_dir}/guest/smoke/report.json"

exit "${test_status}"
