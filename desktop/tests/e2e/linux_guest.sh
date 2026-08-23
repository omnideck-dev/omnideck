#!/usr/bin/env bash

set -Eeuo pipefail

work_dir="${1:?work directory is required}"
package_kind="${2:?package kind is required}"
namespace="${3:?test namespace is required}"
expected_sha256="${4:?artifact SHA-256 is required}"
expected_cli_version="${5:?CLI version is required}"
expected_cli_commit="${6:?CLI commit is required}"
upgrade_from_sha256="${7:-none}"
result_dir="${work_dir}/results"
markers="${work_dir}/markers"
user_data="${work_dir}/user-data"
cli_config="${work_dir}/cli-config"
artifact="${work_dir}/candidate.${package_kind}"
upgrade_from_artifact="${work_dir}/upgrade-from.${package_kind}"
application=""
driver_application=""
package_name=""
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
current_step="initialize"
test_status="failed"

mkdir -p "${result_dir}" "${markers}" "${user_data}" "${cli_config}"
exec > >(tee -a "${result_dir}/guest.log") 2>&1

container_name="omnideck-desktop-${namespace}"
home_volume="omnideck-desktop-home-${namespace}"
state_volume="omnideck-desktop-state-${namespace}"

inventory() {
  local suffix="$1"
  {
    printf 'timestamp=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    . /etc/os-release
    printf 'os=%s\n' "${PRETTY_NAME}"
    printf 'kernel=%s\n' "$(uname -r)"
    printf 'architecture=%s\n' "$(uname -m)"
    printf 'session=%s\n' "$(loginctl list-sessions --no-legend | tr '\n' ';')"
    if command -v podman >/dev/null 2>&1; then
      podman --version
      podman info --format 'runtime={{.Host.OCIRuntime.Name}} graphRoot={{.Store.GraphRoot}}'
      podman ps --all --format 'container={{.Names}}|{{.Status}}|{{.Image}}' | sort
      podman volume ls --format 'volume={{.Name}}' | sort
      podman images --format 'image={{.Repository}}:{{.Tag}}|{{.Digest}}|{{.ID}}' | sort
    else
      printf 'podman=absent\n'
    fi
  } > "${result_dir}/inventory-${suffix}.txt"
}

cleanup_resources() {
  if command -v podman >/dev/null 2>&1; then
    podman rm --force "${container_name}" >/dev/null 2>&1 || true
    podman volume rm --force "${home_volume}" "${state_volume}" >/dev/null 2>&1 || true
  fi
}

write_evidence() {
  local exit_code=$?
  set +e
  inventory after
  mkdir -p "${result_dir}/user-data/logs" "${result_dir}/user-data/runtime"
  [[ -f "${user_data}/setup-state.json" ]] && cp -- "${user_data}/setup-state.json" "${result_dir}/user-data/setup-state.json"
  [[ -f "${user_data}/logs/desktop.log" ]] && cp -- "${user_data}/logs/desktop.log" "${result_dir}/user-data/logs/desktop.log"
  [[ -f "${user_data}/runtime/app-port" ]] && cp -- "${user_data}/runtime/app-port" "${result_dir}/user-data/runtime/app-port"
  if [[ -d "${cli_config}" ]]; then
    cp -a -- "${cli_config}" "${result_dir}/cli-config"
  fi
  printf '{\n  "status": "%s",\n  "lastStep": "%s",\n  "packageKind": "%s",\n  "namespace": "%s",\n  "artifactSha256": "%s",\n  "upgradeFromArtifactSha256": "%s",\n  "expectedCliVersion": "%s",\n  "expectedCliCommit": "%s",\n  "startedAt": "%s",\n  "finishedAt": "%s"\n}\n' \
    "${test_status}" "${current_step}" "${package_kind}" "${namespace}" \
    "${expected_sha256}" "${upgrade_from_sha256}" "${expected_cli_version}" "${expected_cli_commit}" \
    "${started_at}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${result_dir}/summary.json"
  if [[ "${test_status}" == "passed" ]]; then
    cat > "${result_dir}/junit.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="omnideck-desktop-vm-e2e" tests="15" failures="0">
  <testcase classname="desktop-vm-e2e" name="package-and-sidecar-smoke"/>
  <testcase classname="desktop-vm-e2e" name="first-run-exact-copy"/>
  <testcase classname="desktop-vm-e2e" name="hosted-open"/>
  <testcase classname="desktop-vm-e2e" name="returning-user"/>
  <testcase classname="desktop-vm-e2e" name="doctor-recovery"/>
  <testcase classname="desktop-vm-e2e" name="resume"/>
  <testcase classname="desktop-vm-e2e" name="update"/>
  <testcase classname="desktop-vm-e2e" name="occupied-port-auto-recovery"/>
  <testcase classname="desktop-vm-e2e" name="custom-app-webview-action-and-restart"/>
  <testcase classname="desktop-vm-e2e" name="native-host-download"/>
  <testcase classname="desktop-vm-e2e" name="native-host-upload"/>
  <testcase classname="desktop-vm-e2e" name="native-artifact-download-and-toast"/>
  <testcase classname="desktop-vm-e2e" name="native-zoom"/>
  <testcase classname="desktop-vm-e2e" name="native-update-bridge"/>
  <testcase classname="desktop-vm-e2e" name="external-browser-and-internal-navigation"/>
</testsuite>
XML
  else
    printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
      "<testsuite name=\"omnideck-desktop-vm-e2e\" tests=\"1\" failures=\"1\"><testcase classname=\"desktop-vm-e2e\" name=\"${current_step}\"><failure message=\"See guest.log and scenario evidence\"/></testcase></testsuite>" \
      > "${result_dir}/junit.xml"
  fi
  tar -czf "${work_dir}/evidence.tar.gz" -C "${result_dir}" .
  exit "${exit_code}"
}
trap write_evidence EXIT
trap 'printf "ERROR step=%s line=%s command=%q\\n" "${current_step}" "${LINENO}" "${BASH_COMMAND}" >&2' ERR

current_step="artifact checksum"
printf '%s  %s\n' "${expected_sha256}" "${artifact}" | sha256sum --check --strict
if [[ "${upgrade_from_sha256}" != "none" ]]; then
  printf '%s  %s\n' "${upgrade_from_sha256}" "${upgrade_from_artifact}" | sha256sum --check --strict
fi
inventory before

dnf_with_lock_retry() {
  local label="${1:?DNF evidence label is required}"
  shift
  local attempt=1 log="${result_dir}/dnf-${label}.log"
  while ! sudo dnf "$@" 2>&1 | tee "${log}"; do
    if ! tail -n 20 "${log}" | grep -Fq 'Failed to obtain rpm transaction lock'; then
      return 1
    fi
    ((attempt < 31)) || return 1
    printf 'RPM transaction lock is busy; retrying %s (%s of 30).\n' "${label}" "${attempt}"
    attempt=$((attempt + 1))
    sleep 2
  done
}

install_rpm() {
  local requested="${1:-${artifact}}" label="${2:-candidate-install}"
  dnf_with_lock_retry "${label}" install -y "${requested}"
}

current_step="lab preflight isolation"
cleanup_resources
if command -v podman >/dev/null 2>&1 && podman container exists omnideck-desktop; then
  printf 'Removing checkpoint container omnideck-desktop to release its reserved host port.\n' \
    | tee "${result_dir}/preflight.txt"
  podman rm --force omnideck-desktop >> "${result_dir}/preflight.txt"
fi

previous_binary_name=""
previous_package_name=""
installed_appimage="${work_dir}/installed.AppImage"
upgrade_marker="${user_data}/upgrade-marker.json"
if [[ "${upgrade_from_sha256}" != "none" ]]; then
  current_step="previous release installation"
  printf '{"schemaVersion":1,"createdBy":"previous-release-upgrade-test"}\n' > "${upgrade_marker}"
  case "${package_kind}" in
    appimage)
      cp -- "${upgrade_from_artifact}" "${installed_appimage}"
      chmod 755 "${installed_appimage}"
      previous_extraction_dir="${work_dir}/upgrade-from-extracted"
      mkdir -p "${previous_extraction_dir}"
      (
        cd "${previous_extraction_dir}"
        "${installed_appimage}" --appimage-extract >/dev/null
      )
      if [[ -x "${previous_extraction_dir}/squashfs-root/usr/bin/omnideck-desktop" ]]; then
        previous_binary_name="omnideck-desktop"
      else
        [[ -x "${previous_extraction_dir}/squashfs-root/usr/bin/omnideck" ]]
        previous_binary_name="omnideck"
      fi
      ;;
    deb)
      previous_package_name="$(dpkg-deb --field "${upgrade_from_artifact}" Package)"
      sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${upgrade_from_artifact}"
      if command -v omnideck-desktop >/dev/null 2>&1; then
        previous_binary_name="omnideck-desktop"
      else
        command -v omnideck >/dev/null
        previous_binary_name="omnideck"
      fi
      ;;
    rpm)
      previous_package_name="$(rpm -qp --queryformat '%{NAME}' "${upgrade_from_artifact}")"
      install_rpm "${upgrade_from_artifact}" previous-install
      if command -v omnideck-desktop >/dev/null 2>&1; then
        previous_binary_name="omnideck-desktop"
      else
        command -v omnideck >/dev/null
        previous_binary_name="omnideck"
      fi
      ;;
  esac
fi

current_step="native package preparation"
case "${package_kind}" in
  appimage)
    chmod 755 "${artifact}"
    if [[ "${upgrade_from_sha256}" != "none" ]]; then
      candidate_appimage="${installed_appimage}.candidate"
      cp -- "${artifact}" "${candidate_appimage}"
      chmod 755 "${candidate_appimage}"
      mv -- "${candidate_appimage}" "${installed_appimage}"
      application="${installed_appimage}"
    else
      application="${artifact}"
    fi
    ;;
  deb)
    package_name="$(dpkg-deb --field "${artifact}" Package)"
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${artifact}"
    application="$(command -v omnideck-desktop)"
    ;;
  rpm)
    package_name="$(rpm -qp --queryformat '%{NAME}' "${artifact}")"
    install_rpm
    application="$(command -v omnideck-desktop)"
    ;;
  *)
    printf 'Unknown package kind: %s\n' "${package_kind}" >&2
    exit 2
    ;;
esac
[[ -x "${application}" ]]
if [[ "${package_kind}" == "appimage" ]]; then
  printf '%s  %s\n' "${expected_sha256}" "${application}" | sha256sum --check --strict
fi
[[ -f "${upgrade_marker}" || "${upgrade_from_sha256}" == "none" ]]
if [[ "${upgrade_from_sha256}" != "none" ]]; then
  if [[ -n "${previous_package_name}" ]]; then
    [[ "${previous_package_name}" == "${package_name}" ]]
  fi
  if [[ "${previous_binary_name}" == "omnideck" ]]; then
    [[ ! -e /usr/bin/omnideck ]]
  fi
  if [[ "${package_kind}" == "appimage" ]]; then
    candidate_extraction_dir="${work_dir}/candidate-extracted"
    mkdir -p "${candidate_extraction_dir}"
    (
      cd "${candidate_extraction_dir}"
      "${artifact}" --appimage-extract >/dev/null
    )
    [[ -x "${candidate_extraction_dir}/squashfs-root/usr/bin/omnideck-desktop" ]]
    [[ ! -e "${candidate_extraction_dir}/squashfs-root/usr/bin/omnideck" ]]
  fi
  python3 - "${result_dir}/upgrade.json" "${previous_binary_name}" "${upgrade_from_sha256}" "${expected_sha256}" <<'PY'
import json
from pathlib import Path
import sys

path, previous_binary, previous_sha256, candidate_sha256 = sys.argv[1:]
Path(path).write_text(json.dumps({
    "schemaVersion": 1,
    "status": "passed",
    "previousBinary": previous_binary,
    "candidateBinary": "omnideck-desktop",
    "legacyBinaryRemoved": previous_binary == "omnideck",
    "stateMarkerPreserved": True,
    "previousArtifactSha256": previous_sha256,
    "candidateArtifactSha256": candidate_sha256,
}, indent=2) + "\n", encoding="utf-8")
PY
fi
driver_application="${application}"
printf '%s\n' "${application}" > "${result_dir}/application-path.txt"
sha256sum "${application}" > "${result_dir}/application.sha256"

source /etc/os-release
if [[ "${package_kind}" == "appimage" && "${VARIANT_ID:-}" == "silverblue" ]]; then
  current_step="atomic AppImage native extraction"
  extraction_dir="${work_dir}/appimage-extracted"
  native_dir="${work_dir}/atomic-native"
  mkdir -p "${extraction_dir}" "${native_dir}"
  (
    cd "${extraction_dir}"
    "${artifact}" --appimage-extract >/dev/null
  )
  cp -- "${extraction_dir}/squashfs-root/usr/bin/omnideck-desktop" "${native_dir}/omnideck-desktop"
  cp -- "${extraction_dir}/squashfs-root/usr/bin/omnideck-cli" "${native_dir}/omnideck-cli"
  chmod 755 "${native_dir}/omnideck-desktop" "${native_dir}/omnideck-cli"
  cmp --silent "${extraction_dir}/squashfs-root/usr/bin/omnideck-desktop" "${native_dir}/omnideck-desktop"
  cmp --silent "${extraction_dir}/squashfs-root/usr/bin/omnideck-cli" "${native_dir}/omnideck-cli"
  driver_application="${native_dir}/omnideck-desktop"
  {
    printf 'packagedSmoke=%s\n' "${artifact}"
    printf 'attendedBinary=%s\n' "${driver_application}"
    printf 'reason=use byte-identical shipped binaries with Silverblue native WebKitGTK\n'
  } > "${result_dir}/atomic-execution-boundary.txt"
fi
printf '%s\n' "${driver_application}" > "${result_dir}/attended-application-path.txt"
sha256sum "${driver_application}" > "${result_dir}/attended-application.sha256"

current_step="target-scoped authorization agent"
auth_password="${work_dir}/auth-password"
auth_ready="${work_dir}/polkit-agent.ready"
auth_log="${result_dir}/polkit-agent.log"
auth_bin="${work_dir}/auth-bin"
mkdir -p "${auth_bin}"
printf '%s\n' 'omnideck-test' > "${auth_password}"
chmod 600 "${auth_password}"
cat > "${auth_bin}/pkexec" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
ready="${auth_ready}.\$\$"
rm -f -- "\${ready}"
"${work_dir}/polkit_agent.py" \\
  --process "\$\$" \\
  --password-file "${auth_password}" \\
  --ready-file "\${ready}" \\
  --log "${auth_log}" &
agent_pid=\$!
for _ in \$(seq 1 100); do
  [[ ! -e "\${ready}" ]] || break
  kill -0 "\${agent_pid}" 2>/dev/null || { wait "\${agent_pid}"; exit 1; }
  sleep 0.05
done
[[ -e "\${ready}" ]] || { echo 'The target-scoped PolicyKit agent did not register.' >&2; exit 1; }
set +e
/usr/bin/pkexec "\$@"
status=\$?
set -e
kill "\${agent_pid}" 2>/dev/null || true
wait "\${agent_pid}" 2>/dev/null || true
rm -f -- "\${ready}"
exit "\${status}"
EOF
chmod 700 "${auth_bin}/pkexec"

current_step="desktop input dependencies"
if ! command -v WebKitWebDriver >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq webkit2gtk-driver
  elif command -v dnf >/dev/null 2>&1; then
    dnf_with_lock_retry input-dependencies install -y webkitgtk6.0
  fi
fi
command -v WebKitWebDriver

current_step="desktop session"
desktop_pid=""
for _ in $(seq 1 90); do
  desktop_pid="$(pgrep -u "$(id -u)" -x gnome-shell | head -n 1 || true)"
  [[ -n "${desktop_pid}" ]] && break
  sleep 1
done
[[ -n "${desktop_pid}" ]] || {
  printf 'The tester GNOME shell is not active.\n' >&2
  exit 1
}
tr '\0' '\n' < "/proc/${desktop_pid}/environ" > "${result_dir}/desktop-session.env"
display="$(sed -n 's/^DISPLAY=//p' "${result_dir}/desktop-session.env" | head -n 1)"
xauthority="$(sed -n 's/^XAUTHORITY=//p' "${result_dir}/desktop-session.env" | head -n 1)"
wayland_display="$(sed -n 's/^WAYLAND_DISPLAY=//p' "${result_dir}/desktop-session.env" | head -n 1)"
if [[ -z "${wayland_display}" ]]; then
  for candidate in /run/user/1000/wayland-*; do
    if [[ -S "${candidate}" ]]; then
      wayland_display="$(basename "${candidate}")"
      break
    fi
  done
fi
if [[ -z "${xauthority}" ]]; then
  for candidate in /run/user/1000/.mutter-Xwaylandauth.* /run/user/1000/gdm/Xauthority; do
    if [[ -f "${candidate}" ]]; then
      xauthority="${candidate}"
      break
    fi
  done
fi
desktop_env=(
  "PATH=${auth_bin}:${PATH}"
  "XDG_RUNTIME_DIR=/run/user/1000"
  "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"
  "WEBKIT_DISABLE_DMABUF_RENDERER=1"
  "WEBKIT_DISABLE_COMPOSITING_MODE=1"
  "OMNIDECK_DESKTOP_USER_DATA=${user_data}"
  "OMNIDECK_DESKTOP_TEST_NAMESPACE=${namespace}"
  "OMNIDECK_CONFIG_DIR=${cli_config}"
)
update_fixture="${result_dir}/update-fixture.json"
update_version="0.2.3"
desktop_env+=("OMNIDECK_DESKTOP_UPDATE_FIXTURE=${update_fixture}")
if [[ -n "${xauthority}" && -f "${xauthority}" ]]; then
  desktop_env+=("DISPLAY=${display:-:0}" "XAUTHORITY=${xauthority}" "GDK_BACKEND=x11")
  printf 'backend=x11 display=%s xauthority=%s\n' "${display:-:0}" "${xauthority}" \
    > "${result_dir}/desktop-backend.txt"
else
  [[ -n "${wayland_display}" && -S "/run/user/1000/${wayland_display}" ]] || {
    printf 'The tester GNOME session has neither an X11 authority file nor a Wayland socket.\n' >&2
    exit 1
  }
  desktop_env+=("WAYLAND_DISPLAY=${wayland_display}" "GDK_BACKEND=wayland")
  printf 'backend=wayland display=%s\n' "${wayland_display}" > "${result_dir}/desktop-backend.txt"
fi

current_step="unattended packaged smoke"
smoke_dir="${result_dir}/smoke"
mkdir -p "${smoke_dir}/user-data"
smoke_proof="${smoke_dir}/smoke-proof.json"
env "${desktop_env[@]}" \
  OMNIDECK_DESKTOP_USER_DATA="${smoke_dir}/user-data" \
  OMNIDECK_DESKTOP_SMOKE_FILE="${smoke_proof}" \
  "${application}" > "${smoke_dir}/host.stdout.log" 2> "${smoke_dir}/host.stderr.log" &
smoke_pid=$!
deadline=$((SECONDS + 90))
while [[ ! -s "${smoke_proof}" ]]; do
  kill -0 "${smoke_pid}" >/dev/null 2>&1 || {
    printf 'Packaged host exited before smoke proof creation.\n' >&2
    exit 1
  }
  (( SECONDS < deadline )) || {
    printf 'Packaged smoke proof timed out.\n' >&2
    exit 1
  }
  sleep 0.25
done
kill "${smoke_pid}" >/dev/null 2>&1 || true
wait "${smoke_pid}" >/dev/null 2>&1 || true
python3 - "${smoke_proof}" "${expected_cli_version}" "${expected_cli_commit}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    proof = json.load(stream)
assert proof["cliVersion"] == sys.argv[2], proof
assert proof["cliCommit"] == sys.argv[3], proof
assert proof["schemaVersion"] == 4, proof
assert proof["operations"] == ["--version", "--json runtime status"], proof
assert proof["mutation"] is False, proof
PY

run_journey() {
  local scenario="$1"
  local expected_port_conflict="${2:-}"
  local scenario_dir="${result_dir}/${scenario}"
  local driver_args=()
  if [[ -n "${expected_port_conflict}" ]]; then
    driver_args+=(--expected-port-conflict "${expected_port_conflict}")
  fi
  mkdir -p "${scenario_dir}"
  env "${desktop_env[@]}" \
    "${work_dir}/webdriver_client.py" \
      --application "${driver_application}" \
      --tauri-driver "${work_dir}/tauri-driver" \
      --parity "${work_dir}/setup-parity.json" \
      --mockup-parity "${work_dir}/mockup-parity.json" \
      --mockup-html "${work_dir}/mockup-index.html" \
      --evidence "${scenario_dir}" \
      --markers "${markers}" \
      --scenario "${scenario}" \
      "${driver_args[@]}" \
      --timeout 1800
}

current_step="attended first run"
run_journey first-run

current_step="returning user"
run_journey returning

current_step="doctor recovery"
podman rm --force "${container_name}" >/dev/null
run_journey doctor

state_path="${user_data}/setup-state.json"
current_step="interrupted setup resume"
python3 - "${state_path}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as stream:
    state = json.load(stream)
state["status"] = "in-progress"
state["reason"] = "first-run"
with open(path, "w", encoding="utf-8") as stream:
    json.dump(state, stream, indent=2, ensure_ascii=False)
    stream.write("\n")
PY
podman rm --force "${container_name}" >/dev/null
run_journey resume

current_step="candidate update"
python3 - "${state_path}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as stream:
    state = json.load(stream)
state["status"] = "complete"
state["appVersion"] = "0.0.0-e2e-older"
with open(path, "w", encoding="utf-8") as stream:
    json.dump(state, stream, indent=2, ensure_ascii=False)
    stream.write("\n")
PY
run_journey update

current_step="occupied saved port recovery"
old_port="$(tr -d '[:space:]' < "${user_data}/runtime/app-port")"
instance_path="${cli_config}/instances/${container_name}.yaml"
conflict_path="${cli_config}/instances/${container_name}-occupied-port.yaml"
python3 - "${state_path}" "${instance_path}" "${conflict_path}" "${container_name}" "${old_port}" <<'PY'
import json
from pathlib import Path
import sys

state_path = Path(sys.argv[1])
instance_path = Path(sys.argv[2])
conflict_path = Path(sys.argv[3])
container_name = sys.argv[4]
old_port = sys.argv[5]

with state_path.open(encoding="utf-8") as stream:
    state = json.load(stream)
state["status"] = "complete"
state["appVersion"] = "0.0.0-e2e-port-conflict"
with state_path.open("w", encoding="utf-8") as stream:
    json.dump(state, stream, indent=2, ensure_ascii=False)
    stream.write("\n")

source = instance_path.read_text(encoding="utf-8")
expected_name = f"container_name: {container_name}\n"
if expected_name not in source:
    raise AssertionError(f"saved instance did not contain {expected_name!r}")
if f'web_ui_port: "{old_port}"\n' not in source:
    raise AssertionError(f"saved instance did not use port {old_port}")
conflict_path.write_text(
    source.replace(
        expected_name,
        f"container_name: {container_name}-occupied-port\n",
        1,
    ),
    encoding="utf-8",
)
PY
run_journey port-conflict "${old_port}"
new_port="$(tr -d '[:space:]' < "${user_data}/runtime/app-port")"
[[ "${new_port}" != "${old_port}" ]]
grep -Fq "web_ui_port: \"${old_port}\"" "${conflict_path}"
grep -Fq "web_ui_port: \"${new_port}\"" "${instance_path}"
printf 'occupiedPort=%s\nselectedPort=%s\n' "${old_port}" "${new_port}" \
  > "${result_dir}/port-conflict-recovery.txt"

current_step="final returning user"
run_journey returning

current_step="Custom App fixture"
podman cp "${work_dir}/custom_app_fixture.py" "${container_name}:/tmp/omnideck-custom-app-fixture.py"
podman exec --user omnideck "${container_name}" \
  python3 /tmp/omnideck-custom-app-fixture.py
custom_app_port="$(tr -d '[:space:]' < "${user_data}/runtime/app-port")"
curl --fail --silent --show-error --max-time 15 \
  --request PUT \
  --header 'Content-Type: application/json' \
  --header 'X-Requested-With: XMLHttpRequest' \
  --data '{"custom_apps_enabled":true,"setup_complete":true}' \
  "http://127.0.0.1:${custom_app_port}/api/settings" \
  > "${result_dir}/custom-app-settings.json"
curl --fail --silent --show-error --max-time 15 \
  "http://127.0.0.1:${custom_app_port}/api/custom-apps" \
  > "${result_dir}/custom-app-catalog.json"
python3 - "${result_dir}/custom-app-catalog.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    catalog = json.load(stream)
apps = {app["slug"]: app for app in catalog["apps"]}
assert apps["desktop-smoke"]["title"] == "Desktop Custom App Smoke", catalog
assert apps["desktop-smoke"]["has_actions"] is True, catalog
PY

current_step="Custom App packaged WebView"
run_journey custom-app

fixture_id="desktop_host_boundary_${namespace}"
fixture_name="Desktop Host Boundary ${namespace}"
fixture_filename="Desktop-Host-Boundary-${namespace}.agent.omnideck.json"
artifact_filename="desktop-artifact-${namespace}.txt"
artifact_contents="native artifact download ${namespace}"
download_dir="$(xdg-user-dir DOWNLOAD 2>/dev/null || true)"
[[ -n "${download_dir}" ]] || download_dir="${HOME}/Downloads"
mkdir -p "${download_dir}"
download_path="${download_dir}/${fixture_filename}"

run_host_boundary() {
  local operation="$1"
  local operation_dir="${result_dir}/host-boundaries/${operation}"
  local attempt
  local -a operation_args=()
  if [[ "${operation}" == "upload" ]]; then
    operation_args+=(--upload-path "${download_path}")
  elif [[ "${operation}" == "artifact-download" ]]; then
    operation_args+=(--artifact-filename "${artifact_filename}")
  elif [[ "${operation}" == "zoom" ]]; then
    operation_args+=(--native-input-signal-dir "${markers}")
  elif [[ "${operation}" == "update-bridge" ]]; then
    operation_args+=(--expected-update-version "${update_version}")
  fi
  mkdir -p "${operation_dir}"
  for attempt in 1 2 3; do
    rm -f "${operation_dir}/failure.txt"
    if env "${desktop_env[@]}" \
      "${work_dir}/host_boundary_client.py" \
        --application "${driver_application}" \
        --tauri-driver "${work_dir}/tauri-driver" \
        --operation "${operation}" \
        --fixture-id "${fixture_id}" \
        --fixture-name "${fixture_name}" \
        --evidence "${operation_dir}" \
        "${operation_args[@]}" \
        --timeout 240; then
      return 0
    fi
    if [[ "${attempt}" == "3" ]] ||
      ! grep -Eq 'WebDriverError:.*(Remote end closed|Connection reset|Connection refused)' \
        "${operation_dir}/failure.txt"; then
      return 1
    fi
    cp "${operation_dir}/failure.txt" \
      "${operation_dir}/transient-failure-attempt-${attempt}.txt"
    cp "${operation_dir}/tauri-driver.log" \
      "${operation_dir}/transient-driver-attempt-${attempt}.log"
    printf 'Retrying %s after a transient WebDriver disconnect (attempt %s of 3).\n' \
      "${operation}" "$((attempt + 1))"
    sleep 1
  done
}

current_step="native host download"
run_host_boundary download
python3 - "${download_path}" "${fixture_name}" "${result_dir}/host-boundaries/filesystem.json" <<'PY'
import json
from pathlib import Path
import sys
import time

path = Path(sys.argv[1])
deadline = time.monotonic() + 30
while time.monotonic() < deadline and not path.is_file():
    time.sleep(0.25)
if not path.is_file():
    raise AssertionError(f"native download did not create {path}")
with path.open(encoding="utf-8") as stream:
    pack = json.load(stream)
assert pack["kind"] == "omnideck.pack", pack
assert pack["version"] == 1, pack
assert len(pack["profiles"]) == 1, pack
assert pack["profiles"][0]["name"] == sys.argv[2], pack
evidence = {
    "status": "passed",
    "path": str(path),
    "size": path.stat().st_size,
    "kind": pack["kind"],
    "version": pack["version"],
    "profileName": pack["profiles"][0]["name"],
}
Path(sys.argv[3]).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
PY

current_step="native host upload"
run_host_boundary upload

current_step="native artifact fixture"
podman exec \
  --env "E2E_ARTIFACT_FILENAME=${artifact_filename}" \
  --env "E2E_ARTIFACT_CONTENTS=${artifact_contents}" \
  "${container_name}" python -c \
  'import os; from pathlib import Path; from artifacts import record_artifact; name=os.environ["E2E_ARTIFACT_FILENAME"]; path=Path("/home/computron") / name; path.write_text(os.environ["E2E_ARTIFACT_CONTENTS"], encoding="utf-8"); record_artifact(conversation_id="desktop-vm-artifact", path=str(path), filename=name, content_type="text/plain", agent_name="Desktop VM", sent_at="2026-08-12T00:00:00Z")'

current_step="native artifact download"
run_host_boundary artifact-download
artifact_download_path="${download_dir}/${artifact_filename}"
python3 - "${artifact_download_path}" "${artifact_contents}" "${result_dir}/host-boundaries/artifact-filesystem.json" <<'PY'
import json
from pathlib import Path
import sys
import time

path = Path(sys.argv[1])
deadline = time.monotonic() + 30
while time.monotonic() < deadline and not path.is_file():
    time.sleep(0.25)
if not path.is_file():
    raise AssertionError(f"native artifact download did not create {path}")
contents = path.read_text(encoding="utf-8")
assert contents == sys.argv[2], contents
Path(sys.argv[3]).write_text(json.dumps({
    "status": "passed",
    "path": str(path),
    "size": path.stat().st_size,
    "contents": contents,
}, indent=2) + "\n", encoding="utf-8")
PY

current_step="native zoom bridge"
run_host_boundary zoom

current_step="native update bridge"
python3 - "${update_fixture}" "${update_version}" <<'PY'
import json
from pathlib import Path
import sys

Path(sys.argv[1]).write_text(json.dumps({
    "version": sys.argv[2],
    "imageRef": "ghcr.io/omnideck-dev/omnideck@sha256:" + ("a" * 64),
}, indent=2) + "\n", encoding="utf-8")
PY
run_host_boundary update-bridge

current_step="external browser and internal navigation"
if command -v xdg-mime >/dev/null 2>&1 &&
  [[ -x /snap/bin/firefox ]] &&
  [[ -n "${wayland_display}" ]] &&
  [[ -S "/run/user/1000/${wayland_display}" ]]; then
  browser_wrapper="${work_dir}/firefox-wayland"
  applications_dir="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
  browser_desktop="${applications_dir}/omnideck-e2e-firefox.desktop"
  cat > "${browser_wrapper}" <<EOF
#!/usr/bin/env bash
unset DISPLAY XAUTHORITY
export XDG_RUNTIME_DIR=/run/user/1000
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
export WAYLAND_DISPLAY=${wayland_display}
export GDK_BACKEND=wayland
export MOZ_ENABLE_WAYLAND=1
exec /snap/bin/firefox "\$@"
EOF
  chmod 755 "${browser_wrapper}"
  mkdir -p "${applications_dir}"
  cat > "${browser_desktop}" <<EOF
[Desktop Entry]
Name=Firefox (OmniDeck E2E Wayland)
Exec=${browser_wrapper} %u
Type=Application
Terminal=false
NoDisplay=true
MimeType=x-scheme-handler/http;x-scheme-handler/https;
EOF
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${applications_dir}"
  fi
  xdg-mime default "$(basename "${browser_desktop}")" x-scheme-handler/http
  xdg-mime default "$(basename "${browser_desktop}")" x-scheme-handler/https
  [[ "$(xdg-mime query default x-scheme-handler/http)" == "$(basename "${browser_desktop}")" ]]
  [[ "$(xdg-mime query default x-scheme-handler/https)" == "$(basename "${browser_desktop}")" ]]
  desktop_env+=("BROWSER=${browser_wrapper}")
else
  printf 'The AppImage guest has no supported Wayland Firefox session.\n' >&2
  exit 1
fi
run_host_boundary external-links
touch "${markers}/external-browser-visible"
sleep 5
pkill -u "$(id -u)" -TERM -x firefox >/dev/null 2>&1 || true

current_step="resource contract"
podman container inspect "${container_name}" > "${result_dir}/container-inspect.json"
podman volume inspect "${home_volume}" "${state_volume}" > "${result_dir}/volume-inspect.json"
curl --fail --silent --show-error --max-time 15 "http://127.0.0.1:$(cat "${user_data}/runtime/app-port")" \
  > "${result_dir}/hosted.html"
grep -Fq 'sha256:' "${user_data}/setup-state.json"

current_step="package lifecycle"
case "${package_kind}" in
  deb)
    dpkg-query --listfiles "${package_name}" > "${result_dir}/installed-files.txt"
    sudo env DEBIAN_FRONTEND=noninteractive apt-get remove -y "${package_name}"
    [[ ! -e "${application}" ]]
    [[ -f "${state_path}" ]]
    podman container inspect "${container_name}" >/dev/null
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${artifact}"
    [[ -x "${application}" ]]
    ;;
  rpm)
    rpm -ql "${package_name}" > "${result_dir}/installed-files.txt"
    dnf_with_lock_retry candidate-remove remove -y "${package_name}"
    [[ ! -e "${application}" ]]
    [[ -f "${state_path}" ]]
    podman container inspect "${container_name}" >/dev/null
    install_rpm
    [[ -x "${application}" ]]
    ;;
  appimage)
    printf 'AppImage is a direct-execution package; install/uninstall receipts do not apply.\n' \
      > "${result_dir}/package-lifecycle.txt"
    ;;
esac

current_step="cleanup"
cleanup_resources
test_status="passed"
current_step="complete"
printf 'PASS: package smoke, setup/recovery, Custom App WebView, native download/upload/artifact/zoom/update boundaries, and package lifecycle completed.\n'
