#!/usr/bin/env bash

set -Eeuo pipefail

work_dir="${1:?work directory is required}"
package_kind="${2:?package kind is required}"
namespace="${3:?test namespace is required}"
expected_sha256="${4:?artifact SHA-256 is required}"
expected_cli_version="${5:?CLI version is required}"
expected_cli_commit="${6:?CLI commit is required}"
result_dir="${work_dir}/results"
markers="${work_dir}/markers"
user_data="${work_dir}/user-data"
cli_config="${work_dir}/cli-config"
artifact="${work_dir}/candidate.${package_kind}"
application=""
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
  printf '{\n  "status": "%s",\n  "lastStep": "%s",\n  "packageKind": "%s",\n  "namespace": "%s",\n  "artifactSha256": "%s",\n  "expectedCliVersion": "%s",\n  "expectedCliCommit": "%s",\n  "startedAt": "%s",\n  "finishedAt": "%s"\n}\n' \
    "${test_status}" "${current_step}" "${package_kind}" "${namespace}" \
    "${expected_sha256}" "${expected_cli_version}" "${expected_cli_commit}" \
    "${started_at}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${result_dir}/summary.json"
  if [[ "${test_status}" == "passed" ]]; then
    cat > "${result_dir}/junit.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="omnideck-desktop-vm-e2e" tests="7" failures="0">
  <testcase classname="desktop-vm-e2e" name="package-and-sidecar-smoke"/>
  <testcase classname="desktop-vm-e2e" name="first-run-exact-copy"/>
  <testcase classname="desktop-vm-e2e" name="hosted-open"/>
  <testcase classname="desktop-vm-e2e" name="returning-user"/>
  <testcase classname="desktop-vm-e2e" name="doctor-recovery"/>
  <testcase classname="desktop-vm-e2e" name="resume"/>
  <testcase classname="desktop-vm-e2e" name="update"/>
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
inventory before

current_step="lab preflight isolation"
cleanup_resources
if podman container exists omnideck-desktop; then
  printf 'Removing checkpoint container omnideck-desktop to release its reserved host port.\n' \
    | tee "${result_dir}/preflight.txt"
  podman rm --force omnideck-desktop >> "${result_dir}/preflight.txt"
fi

current_step="native package preparation"
case "${package_kind}" in
  appimage)
    chmod 755 "${artifact}"
    application="${artifact}"
    ;;
  deb)
    package_name="$(dpkg-deb --field "${artifact}" Package)"
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${artifact}"
    application="$(command -v omnideck)"
    ;;
  rpm)
    package_name="$(rpm -qp --queryformat '%{NAME}' "${artifact}")"
    sudo dnf install -y "${artifact}"
    application="$(command -v omnideck)"
    ;;
  *)
    printf 'Unknown package kind: %s\n' "${package_kind}" >&2
    exit 2
    ;;
esac
[[ -x "${application}" ]]
printf '%s\n' "${application}" > "${result_dir}/application-path.txt"
sha256sum "${application}" > "${result_dir}/application.sha256"

current_step="WebDriver dependency"
if ! command -v WebKitWebDriver >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq webkit2gtk-driver
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y webkit2gtk6.0-driver
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
if [[ -z "${xauthority}" ]]; then
  for candidate in /run/user/1000/.mutter-Xwaylandauth.* /run/user/1000/gdm/Xauthority; do
    if [[ -f "${candidate}" ]]; then
      xauthority="${candidate}"
      break
    fi
  done
fi
desktop_env=(
  "XDG_RUNTIME_DIR=/run/user/1000"
  "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"
  "OMNIDECK_DESKTOP_USER_DATA=${user_data}"
  "OMNIDECK_DESKTOP_TEST_NAMESPACE=${namespace}"
  "OMNIDECK_CONFIG_DIR=${cli_config}"
)
if [[ -n "${xauthority}" && -f "${xauthority}" ]]; then
  desktop_env+=("DISPLAY=${display:-:0}" "XAUTHORITY=${xauthority}" "GDK_BACKEND=x11")
  printf 'backend=x11 display=%s xauthority=%s\n' "${display:-:0}" "${xauthority}" \
    > "${result_dir}/desktop-backend.txt"
else
  wayland_display="$(sed -n 's/^WAYLAND_DISPLAY=//p' "${result_dir}/desktop-session.env" | head -n 1)"
  if [[ -z "${wayland_display}" ]]; then
    for candidate in /run/user/1000/wayland-*; do
      if [[ -S "${candidate}" ]]; then
        wayland_display="$(basename "${candidate}")"
        break
      fi
    done
  fi
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
  local scenario_dir="${result_dir}/${scenario}"
  mkdir -p "${scenario_dir}"
  env "${desktop_env[@]}" \
    "${work_dir}/webdriver_client.py" \
      --application "${application}" \
      --tauri-driver "${work_dir}/tauri-driver" \
      --parity "${work_dir}/setup-parity.json" \
      --mockup-parity "${work_dir}/mockup-parity.json" \
      --mockup-html "${work_dir}/mockup-index.html" \
      --evidence "${scenario_dir}" \
      --markers "${markers}" \
      --scenario "${scenario}" \
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

current_step="final returning user"
run_journey returning

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
    sudo dnf remove -y "${package_name}"
    [[ ! -e "${application}" ]]
    [[ -f "${state_path}" ]]
    podman container inspect "${container_name}" >/dev/null
    sudo dnf install -y "${artifact}"
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
printf 'PASS: package smoke, exact-copy setup, hosted, returning, doctor, resume, and update completed.\n'
