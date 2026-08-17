#!/usr/bin/env bash

set -Eeuo pipefail

work_dir="${1:?work directory is required}"
package_kind="${2:?package kind is required}"
expected_sha256="${3:?artifact SHA-256 is required}"
expected_cli_version="${4:?CLI version is required}"
expected_cli_commit="${5:?CLI commit is required}"
artifact="${work_dir}/candidate.${package_kind}"
result_dir="${work_dir}/results"
user_data="${work_dir}/user-data"
cli_config="${work_dir}/cli-config"
markers="${work_dir}/markers"
application=""
application_label=""
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
current_step="initialize"
test_status="failed"
declare -a application_command=()

mkdir -p "${result_dir}" "${user_data}" "${cli_config}" "${markers}"
exec > >(tee -a "${result_dir}/guest.log") 2>&1

inventory() {
  local suffix="$1"
  {
    printf 'timestamp=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    . /etc/os-release
    printf 'os=%s\n' "${PRETTY_NAME}"
    printf 'kernel=%s\n' "$(uname -r)"
    printf 'architecture=%s\n' "$(uname -m)"
    printf 'packageKind=%s\n' "${package_kind}"
    printf 'session=%s\n' "$(loginctl list-sessions --no-legend | tr '\n' ';')"
  } > "${result_dir}/inventory-${suffix}.txt"
}

write_evidence() {
  local exit_code=$?
  set +e
  inventory after
  printf '{\n  "status": "%s",\n  "lastStep": "%s",\n  "packageKind": "%s",\n  "application": "%s",\n  "artifactSha256": "%s",\n  "expectedCliVersion": "%s",\n  "expectedCliCommit": "%s",\n  "startedAt": "%s",\n  "finishedAt": "%s"\n}\n' \
    "${test_status}" "${current_step}" "${package_kind}" "${application_label}" \
    "${expected_sha256}" "${expected_cli_version}" "${expected_cli_commit}" \
    "${started_at}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${result_dir}/summary.json"
  if [[ "${test_status}" == "passed" ]]; then
    printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
      '<testsuite name="omnideck-desktop-cross-distro-smoke" tests="1" failures="0"><testcase classname="desktop-vm-smoke" name="package-opens-and-sidecar-responds"/></testsuite>' \
      > "${result_dir}/junit.xml"
  else
    printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
      "<testsuite name=\"omnideck-desktop-cross-distro-smoke\" tests=\"1\" failures=\"1\"><testcase classname=\"desktop-vm-smoke\" name=\"${current_step}\"><failure message=\"See guest.log and smoke logs\"/></testcase></testsuite>" \
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

current_step="native package preparation"
case "${package_kind}" in
  appimage)
    chmod 755 "${artifact}"
    application="${artifact}"
    application_command=("${application}")
    ;;
  deb)
    if command -v apt-get >/dev/null 2>&1; then
      sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${artifact}"
      application="$(command -v omnideck-desktop)"
    else
      payload_root="${work_dir}/deb-root"
      mkdir -p "${payload_root}"
      deb_payload="${work_dir}/deb-data.tar"
      python3 - "${artifact}" "${deb_payload}" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_bytes()
assert source.startswith(b"!<arch>\n"), "invalid DEB ar header"
offset = 8
while offset + 60 <= len(source):
    header = source[offset : offset + 60]
    name = header[:16].decode("ascii").strip().rstrip("/")
    size = int(header[48:58].decode("ascii").strip())
    offset += 60
    payload = source[offset : offset + size]
    if name.startswith("data.tar"):
        Path(sys.argv[2]).write_bytes(payload)
        break
    offset += size + (size % 2)
else:
    raise AssertionError("the DEB has no data archive")
PY
      tar -x -f "${deb_payload}" -C "${payload_root}"
      application="${payload_root}/usr/bin/omnideck-desktop"
    fi
    application_command=("${application}")
    ;;
  rpm)
    if command -v dnf >/dev/null 2>&1; then
      sudo dnf install -y "${artifact}"
      application="$(command -v omnideck-desktop)"
    else
      if ! command -v rpm2cpio >/dev/null 2>&1 || ! command -v cpio >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rpm2cpio cpio
      fi
      payload_root="${work_dir}/rpm-root"
      mkdir -p "${payload_root}"
      (
        cd "${payload_root}"
        if rpm2cpio "${artifact}" | cpio --extract --make-directories --no-preserve-owner; then
          extraction_status=("${PIPESTATUS[@]}")
        else
          extraction_status=("${PIPESTATUS[@]}")
        fi
        printf 'rpm2cpioStatus=%s cpioStatus=%s\n' "${extraction_status[0]}" "${extraction_status[1]}" \
          > "${result_dir}/rpm-extraction.txt"
        [[ -x ./usr/bin/omnideck-desktop && -x ./usr/bin/omnideck-cli ]]
      )
      application="${payload_root}/usr/bin/omnideck-desktop"
    fi
    application_command=("${application}")
    ;;
  flatpak)
    if ! command -v flatpak >/dev/null 2>&1; then
      if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq flatpak
      elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y flatpak
      fi
    fi
    command -v flatpak >/dev/null 2>&1 || { printf 'Flatpak is unavailable on this guest.\n' >&2; exit 1; }
    flatpak list --user --app --columns=application | sort -u > "${work_dir}/flatpak-before.txt"
    flatpak install --user --noninteractive "${artifact}"
    flatpak list --user --app --columns=application | sort -u > "${work_dir}/flatpak-after.txt"
    mapfile -t installed_apps < <(comm -13 "${work_dir}/flatpak-before.txt" "${work_dir}/flatpak-after.txt")
    [[ "${#installed_apps[@]}" == "1" ]] || {
      printf 'Expected the bundle to add exactly one Flatpak app; added %s.\n' "${#installed_apps[@]}" >&2
      exit 1
    }
    application="${installed_apps[0]}"
    flatpak override --user --filesystem="${work_dir}" "${application}"
    application_command=(flatpak run --user "${application}")
    ;;
  *)
    printf 'Unknown package kind: %s\n' "${package_kind}" >&2
    exit 2
    ;;
esac
[[ "${package_kind}" == "flatpak" || -x "${application}" ]] || {
  printf 'Packaged application is not executable: %s\n' "${application}" >&2
  exit 1
}
application_label="${application}"
printf '%s\n' "${application}" > "${result_dir}/application-path.txt"

current_step="desktop session"
desktop_pid=""
for _ in $(seq 1 90); do
  desktop_pid="$(pgrep -u "$(id -u)" -x gnome-shell | head -n 1 || true)"
  [[ -n "${desktop_pid}" ]] && break
  sleep 1
done
[[ -n "${desktop_pid}" ]] || { printf 'The tester GNOME shell is not active.\n' >&2; exit 1; }
tr '\0' '\n' < "/proc/${desktop_pid}/environ" > "${result_dir}/desktop-session.env"
display="$(sed -n 's/^DISPLAY=//p' "${result_dir}/desktop-session.env" | head -n 1)"
xauthority="$(sed -n 's/^XAUTHORITY=//p' "${result_dir}/desktop-session.env" | head -n 1)"
wayland_display="$(sed -n 's/^WAYLAND_DISPLAY=//p' "${result_dir}/desktop-session.env" | head -n 1)"
if [[ -z "${wayland_display}" ]]; then
  for candidate in /run/user/1000/wayland-*; do
    if [[ -S "${candidate}" ]]; then wayland_display="$(basename "${candidate}")"; break; fi
  done
fi
if [[ -z "${xauthority}" ]]; then
  for candidate in /run/user/1000/.mutter-Xwaylandauth.* /run/user/1000/gdm/Xauthority; do
    if [[ -f "${candidate}" ]]; then xauthority="${candidate}"; break; fi
  done
fi
desktop_env=(
  "XDG_RUNTIME_DIR=/run/user/1000"
  "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"
  "WEBKIT_DISABLE_DMABUF_RENDERER=1"
  "WEBKIT_DISABLE_COMPOSITING_MODE=1"
  "OMNIDECK_DESKTOP_USER_DATA=${user_data}"
  "OMNIDECK_CONFIG_DIR=${cli_config}"
)
if [[ -n "${xauthority}" && -f "${xauthority}" ]]; then
  desktop_env+=("DISPLAY=${display:-:0}" "XAUTHORITY=${xauthority}" "GDK_BACKEND=x11")
else
  [[ -n "${wayland_display}" && -S "/run/user/1000/${wayland_display}" ]] || {
    printf 'The tester session has neither an X11 authority file nor a Wayland socket.\n' >&2
    exit 1
  }
  desktop_env+=("WAYLAND_DISPLAY=${wayland_display}" "GDK_BACKEND=wayland")
fi

current_step="package launch smoke"
smoke_dir="${result_dir}/smoke"
mkdir -p "${smoke_dir}/user-data"
smoke_proof="${smoke_dir}/smoke-proof.json"
env "${desktop_env[@]}" \
  OMNIDECK_DESKTOP_USER_DATA="${smoke_dir}/user-data" \
  OMNIDECK_DESKTOP_SMOKE_FILE="${smoke_proof}" \
  "${application_command[@]}" > "${smoke_dir}/host.stdout.log" 2> "${smoke_dir}/host.stderr.log" &
smoke_pid=$!
deadline=$((SECONDS + 90))
while [[ ! -s "${smoke_proof}" ]]; do
  kill -0 "${smoke_pid}" >/dev/null 2>&1 || {
    printf 'Packaged host exited before smoke proof creation.\n' >&2
    exit 1
  }
  (( SECONDS < deadline )) || { printf 'Packaged smoke proof timed out.\n' >&2; exit 1; }
  sleep 0.25
done
touch "${markers}/smoke-proof-created"
sleep 2
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

test_status="passed"
current_step="complete"
printf 'PASS: %s opened and completed the read-only packaged smoke.\n' "${package_kind}"
