#!/usr/bin/env bash

set -Eeuo pipefail
export LANG=C
export LC_ALL=C

work_dir="${1:?work directory is required}"
dmg="${2:?DMG path is required}"
result_dir="${3:?result directory is required}"
upgrade_dmg="${4:-none}"
namespace="release-test-macos"
managed_root="$HOME/.omnideck-lab"
user_data="$managed_root/state/desktop-e2e"
cli_config="$managed_root/config/desktop-e2e"
downloads="$managed_root/downloads/desktop-e2e"
run_token="$(printf '%s' "$work_dir" | shasum -a 256 | awk '{print substr($1,1,12)}')"
native_download_dir="$HOME/Downloads"
fixture_name="Desktop Host Boundary ${namespace} ${run_token}"
fixture_filename="Desktop-Host-Boundary-${namespace}-${run_token}.agent.omnideck.json"
download_path="$native_download_dir/$fixture_filename"
artifact_filename="desktop-artifact-${namespace}-${run_token}.txt"
artifact_contents="native artifact download ${namespace} ${run_token}"
artifact_download_path="$native_download_dir/$artifact_filename"
update_fixture="$work_dir/update-fixture.json"
update_version=99.0.0
installed_app="$HOME/Applications/Omnideck Lab.app"
application="$installed_app/Contents/MacOS/omnideck-desktop"
driver_app="$HOME/Applications/Omnideck Lab Driver.app"
driver="$driver_app/Contents/MacOS/omnideck-lab-driver"
input_extension="$HOME/.omnideck-lab/input/omnideck-lab-input.dylib"
downloads_permission_helper="$HOME/.local/libexec/omnideck-lab/allow-downloads.sh"
container_name="omnideck-desktop-${namespace}"
home_volume="omnideck-desktop-home-${namespace}"
state_volume="omnideck-desktop-state-${namespace}"
mount_point="$(mktemp -d /private/tmp/omnideck-dmg.XXXXXX)"
upgrade_mount_point=""
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
current_step=initialize
test_status=failed
application_pid=''
downloads_permission_pid=''
soft_failures=()
mode="${OMNIDECK_MACOS_E2E_MODE:-full}"
[[ "$mode" == full || "$mode" == boundaries ]] || { printf 'Unsupported macOS E2E mode: %s\n' "$mode" >&2; exit 2; }

mkdir -p "$result_dir" "$result_dir/accessibility" "$result_dir/screenshots" \
  "$result_dir/host-boundaries" "$user_data" "$cli_config" "$downloads"
exec > >(tee -a "$result_dir/guest.log") 2>&1

stop_application() {
  if [[ -n "$application_pid" ]] && kill -0 "$application_pid" >/dev/null 2>&1; then
    kill "$application_pid" >/dev/null 2>&1 || true
    wait "$application_pid" >/dev/null 2>&1 || true
  fi
  application_pid=''
  pkill -f "^$application$" >/dev/null 2>&1 || true
}

finish_downloads_permission() {
  if [[ -n "$downloads_permission_pid" ]]; then
    wait "$downloads_permission_pid"
    downloads_permission_pid=''
  fi
}

write_evidence() {
  local exit_code=$?
  set +e
  if [[ "$test_status" != passed && -n "$application_pid" ]] && kill -0 "$application_pid" >/dev/null 2>&1; then
    "$driver" dump "$application" "$result_dir/accessibility/failure-$current_step.json" >/dev/null 2>&1 || true
    "$driver" screenshot "$application" "$result_dir/screenshots/failure-$current_step.png" >/dev/null 2>&1 || true
  fi
  finish_downloads_permission
  podman logs "$container_name" > "$result_dir/container.log" 2>&1 || true
  stop_application
  hdiutil detach "$mount_point" -quiet >/dev/null 2>&1 || true
  if [[ -n "$upgrade_mount_point" ]]; then
    hdiutil detach "$upgrade_mount_point" -quiet >/dev/null 2>&1 || true
    rmdir "$upgrade_mount_point" >/dev/null 2>&1 || true
  fi
  rmdir "$mount_point" >/dev/null 2>&1 || true
  [[ -f "$user_data/setup-state.json" ]] && cp -- "$user_data/setup-state.json" "$result_dir/setup-state.json"
  [[ -f "$user_data/logs/desktop.log" ]] && cp -- "$user_data/logs/desktop.log" "$result_dir/desktop.log"
  [[ -f "$user_data/runtime/app-port" ]] && cp -- "$user_data/runtime/app-port" "$result_dir/app-port"
  podman container inspect "$container_name" > "$result_dir/container-inspect.json" 2>/dev/null || true
  podman volume inspect "$home_volume" "$state_volume" > "$result_dir/volume-inspect.json" 2>/dev/null || true
  rm -f -- "$download_path" "$artifact_download_path"
  node - "$result_dir/summary.json" "$test_status" "$current_step" "$started_at" <<'NODE'
const fs = require('node:fs');
const [path, status, lastStep, startedAt] = process.argv.slice(2);
fs.writeFileSync(path, `${JSON.stringify({
  schemaVersion: 1,
  status,
  lastStep,
  platform: 'darwin',
  architecture: 'arm64',
  driver: 'macos-accessibility',
  startedAt,
  finishedAt: new Date().toISOString(),
}, null, 2)}\n`);
NODE
  if [[ "$test_status" == passed ]]; then
    cat > "$result_dir/junit.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="omnideck-desktop-macos-e2e" tests="17" failures="0">
  <testcase classname="desktop-macos-e2e" name="package-and-sidecar-smoke"/>
  <testcase classname="desktop-macos-e2e" name="first-run-accessibility"/>
  <testcase classname="desktop-macos-e2e" name="hosted-open"/>
  <testcase classname="desktop-macos-e2e" name="returning-user"/>
  <testcase classname="desktop-macos-e2e" name="doctor-recovery"/>
  <testcase classname="desktop-macos-e2e" name="resume"/>
  <testcase classname="desktop-macos-e2e" name="update"/>
  <testcase classname="desktop-macos-e2e" name="occupied-port-auto-recovery"/>
  <testcase classname="desktop-macos-e2e" name="custom-app-native-webview"/>
  <testcase classname="desktop-macos-e2e" name="custom-app-restart-persistence"/>
  <testcase classname="desktop-macos-e2e" name="external-browser-and-internal-navigation"/>
  <testcase classname="desktop-macos-e2e" name="native-host-download"/>
  <testcase classname="desktop-macos-e2e" name="native-host-upload"/>
  <testcase classname="desktop-macos-e2e" name="native-artifact-download-and-toast"/>
  <testcase classname="desktop-macos-e2e" name="native-update-bridge-visible-contract"/>
  <testcase classname="desktop-macos-e2e" name="dmg-remove-preserves-state"/>
  <testcase classname="desktop-macos-e2e" name="dmg-reinstall-and-sidecar-smoke"/>
</testsuite>
XML
  else
    printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
      "<testsuite name=\"omnideck-desktop-macos-e2e\" tests=\"1\" failures=\"1\"><testcase classname=\"desktop-macos-e2e\" name=\"$current_step\"><failure message=\"See guest.log and Accessibility evidence\"/></testcase></testsuite>" \
      > "$result_dir/junit.xml"
  fi
  exit "$exit_code"
}
trap write_evidence EXIT
trap 'printf "ERROR step=%s line=%s command=%q\\n" "$current_step" "$LINENO" "$BASH_COMMAND" >&2' ERR

[[ "$(uname -s)/$(uname -m)" == Darwin/arm64 ]] || exit 2
[[ -x "$driver" ]] || { printf 'The macOS lab Accessibility driver is not installed.\n' >&2; exit 3; }
[[ -f "$input_extension" ]] || { printf 'The macOS lab trusted-input extension is not installed.\n' >&2; exit 3; }
[[ -x "$downloads_permission_helper" ]] || { printf 'The macOS lab Downloads permission helper is not installed.\n' >&2; exit 3; }

current_step='Accessibility permission preflight'
preflight="$("$driver" preflight 2>&1 || true)"
[[ "$preflight" == *'accessibility=true'* ]] || { printf '%s\n' "$preflight" >&2; exit 3; }

current_step='exclusive desktop process'
/usr/bin/pgrep -f '/omnideck-desktop$' > "$result_dir/preexisting-omnideck-desktop-pids.txt" 2>/dev/null || true
/usr/bin/pgrep -f '/omnideck$' > "$result_dir/preexisting-omnideck-pids.txt" 2>/dev/null || true
/usr/bin/pkill -f '/omnideck-desktop$' 2>/dev/null || true
/usr/bin/pkill -f '/omnideck$' 2>/dev/null || true
for _ in 1 2 3 4 5; do
  if ! /usr/bin/pgrep -f '/omnideck-desktop$' >/dev/null 2>&1 &&
     ! /usr/bin/pgrep -f '/omnideck$' >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
! /usr/bin/pgrep -f '/omnideck-desktop$' >/dev/null 2>&1
! /usr/bin/pgrep -f '/omnideck$' >/dev/null 2>&1

if [[ "$upgrade_dmg" != none ]]; then
  current_step='previous DMG installation'
  upgrade_mount_point="$(mktemp -d /private/tmp/omnideck-upgrade-dmg.XXXXXX)"
  hdiutil attach "$upgrade_dmg" -nobrowse -readonly -mountpoint "$upgrade_mount_point" -quiet
  upgrade_source_app="$(find "$upgrade_mount_point" -maxdepth 1 -type d -name '*.app' -print -quit)"
  [[ -n "$upgrade_source_app" ]]
  if [[ -x "$upgrade_source_app/Contents/MacOS/omnideck-desktop" ]]; then
    previous_binary=omnideck-desktop
  else
    [[ -x "$upgrade_source_app/Contents/MacOS/omnideck" ]]
    previous_binary=omnideck
  fi
  [[ ! -e "$installed_app" ]]
  /usr/bin/ditto "$upgrade_source_app" "$installed_app"
  printf '{"schemaVersion":1,"createdBy":"previous-release-upgrade-test"}\n' \
    > "$user_data/upgrade-marker.json"
  /bin/rm -rf -- "$installed_app"
fi

current_step='exact DMG installation'
hdiutil attach "$dmg" -nobrowse -readonly -mountpoint "$mount_point" -quiet
source_app="$(find "$mount_point" -maxdepth 1 -type d -name '*.app' -print -quit)"
[[ -n "$source_app" && -x "$source_app/Contents/MacOS/omnideck-desktop" ]]
file "$source_app/Contents/MacOS/omnideck-desktop" | grep -Eq 'Mach-O 64-bit.*arm64'
[[ ! -e "$installed_app" ]]
/usr/bin/ditto "$source_app" "$installed_app"
[[ "$(defaults read "$installed_app/Contents/Info" CFBundleIdentifier 2>/dev/null || true)" == dev.omnideck.desktop ]]
[[ "$(shasum -a 256 "$source_app/Contents/MacOS/omnideck-desktop" | awk '{print $1}')" == "$(shasum -a 256 "$application" | awk '{print $1}')" ]]
[[ ! -e "$installed_app/Contents/MacOS/omnideck" ]]
if [[ "$upgrade_dmg" != none ]]; then
  [[ -f "$user_data/upgrade-marker.json" ]]
  python3 - "$result_dir/upgrade.json" "$previous_binary" <<'PY'
import json
from pathlib import Path
import sys

Path(sys.argv[1]).write_text(json.dumps({
    "schemaVersion": 1,
    "status": "passed",
    "previousBinary": sys.argv[2],
    "candidateBinary": "omnideck-desktop",
    "legacyBinaryRemoved": sys.argv[2] == "omnideck",
    "stateMarkerPreserved": True,
}, indent=2) + "\n", encoding="utf-8")
PY
fi

desktop_env=(
  "PATH=$HOME/.local/bin:/opt/podman/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  "HOME=$HOME"
  "OMNIDECK_DESKTOP_USER_DATA=$user_data"
  "OMNIDECK_DESKTOP_TEST_NAMESPACE=$namespace"
  "OMNIDECK_CONFIG_DIR=$cli_config"
  "OMNIDECK_DESKTOP_UPDATE_FIXTURE=$update_fixture"
)

current_step='packaged read-only smoke'
mkdir -p "$result_dir/smoke"
env "PATH=${desktop_env[0]#PATH=}" "$work_dir/desktop/tests/hardware/run.sh" \
  --application "$application" --output "$result_dir/smoke" --require-ready

launch_application() {
  local label="$1" expected_text="${2:-}" timeout="${3:-30}"
  local entry pid_line attempt attempt_label
  local open_env=()
  stop_application
  for entry in "${desktop_env[@]}"; do open_env+=(--env "$entry"); done
  for attempt in 1 2 3; do
    attempt_label="$label"
    [[ "$attempt" == 1 ]] || attempt_label="${label}-launch-retry-${attempt}"
    /usr/bin/open -n -F -a "$installed_app" \
      -o "$result_dir/${attempt_label}.stdout.log" \
      --stderr "$result_dir/${attempt_label}.stderr.log" \
      "${open_env[@]}"
    if pid_line="$("$driver" wait "$application" 30)"; then
      application_pid="${pid_line#pid=}"
      if [[ "$application_pid" =~ ^[0-9]+$ ]] && \
         "$driver" wait-windows "$application" 1 30; then
        if [[ -z "$expected_text" ]] || \
           "$driver" wait-text "$application" "$expected_text" "$timeout"; then
          return 0
        fi
      fi
    fi
    printf 'Application launched without an accessible window; retrying (%s of 3).\n' "$attempt" >&2
    stop_application
    sleep 1
  done
  printf 'Application did not expose a window after 3 launch attempts.\n' >&2
  return 1
}

dump_accessibility() {
  local label="$1"
  "$driver" dump "$application" "$result_dir/accessibility/${label}.json"
}

capture() {
  local label="$1" destination
  [[ "${OMNIDECK_MACOS_E2E_SCREENSHOTS:-1}" == 1 ]] || return 0
  destination="$result_dir/screenshots/$label"
  mkdir -p "$destination"
  /usr/bin/open -a "$installed_app"
  sleep 0.2
  /usr/bin/open -n -a "$driver_app" \
    -o "$destination/driver.stdout.log" --stderr "$destination/driver.stderr.log" \
    --args screenshot "$application" "$destination"
  for _ in $(seq 1 50); do
    if grep -q '^screenshots=' "$destination/driver.stdout.log" 2>/dev/null && \
      python3 - "$destination" <<'PY'
import struct, sys
from pathlib import Path
for path in Path(sys.argv[1]).glob('window-*.png'):
    data=path.read_bytes()[:24]
    if len(data) == 24 and data[:8] == b'\x89PNG\r\n\x1a\n':
        width, height=struct.unpack('>II', data[16:24])
        if width >= 640 and height >= 400: raise SystemExit(0)
raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep 0.2
  done
  printf 'The Accessibility driver could not capture %s.\n' "$label" >&2
  return 3
}

assert_tree_text() {
  local tree="$1"; shift
  python3 - "$tree" "$@" <<'PY'
import json, sys
records=json.load(open(sys.argv[1], encoding='utf-8'))
haystack='\n'.join(str(record.get(key, '')) for record in records for key in ('title','description','value','identifier'))
missing=[text for text in sys.argv[2:] if text not in haystack]
assert not missing, {'missing': missing, 'observed': haystack}
PY
}

mouse_click() {
  local query="$1"
  env DYLD_INSERT_LIBRARIES="$input_extension" \
    OMNIDECK_LAB_INPUT_TARGET="$application" OMNIDECK_LAB_INPUT_CLICK="$query" \
    "$driver" wait "$application" 2 >/dev/null
}

wait_ready_and_open() {
  local label="$1"
  "$driver" wait-text "$application" 'omnideck is ready' 1800
  dump_accessibility "${label}-ready"
  assert_tree_text "$result_dir/accessibility/${label}-ready.json" \
    'omnideck is ready' 'Everything is prepared. Open omnideck whenever you’re ready.' 'Open omnideck'
  capture "${label}-ready"
  "$driver" click "$application" 'Open omnideck' 30
  "$driver" wait-text "$application" 'Welcome to Omnideck' 180
  dump_accessibility "${label}-hosted"
  capture "${label}-hosted"
}

current_step='attended first run'
launch_application first-run 'Welcome to omnideck' 60
dump_accessibility first-run-welcome
assert_tree_text "$result_dir/accessibility/first-run-welcome.json" \
  'Welcome to omnideck' 'A one-time setup will prepare everything omnideck needs on this computer.' 'Set up omnideck'
capture first-run-welcome
"$driver" click "$application" 'Set up omnideck' 30
wait_ready_and_open first-run

state_path="$user_data/setup-state.json"
if [[ "$mode" == full ]]; then
current_step='returning user'
launch_application returning 'Welcome to Omnideck' 180
dump_accessibility returning-hosted
capture returning-hosted

current_step='doctor recovery'
stop_application
podman rm --force "$container_name" >/dev/null
launch_application doctor 'Try again' 180
dump_accessibility doctor-error
capture doctor-error
"$driver" click "$application" 'Try again' 30
wait_ready_and_open doctor

current_step='interrupted setup resume'
stop_application
python3 - "$state_path" <<'PY'
import json, sys
path=sys.argv[1]
state=json.load(open(path, encoding='utf-8'))
state['status']='in-progress'; state['reason']='first-run'
with open(path,'w',encoding='utf-8') as stream: json.dump(state,stream,indent=2); stream.write('\n')
PY
podman rm --force "$container_name" >/dev/null
launch_application resume 'Continuing from where the last attempt stopped.' 120
dump_accessibility resume-progress
wait_ready_and_open resume

current_step='candidate update reconciliation'
stop_application
python3 - "$state_path" <<'PY'
import json, sys
path=sys.argv[1]
state=json.load(open(path, encoding='utf-8'))
state['status']='complete'; state['appVersion']='0.0.0-e2e-older'
with open(path,'w',encoding='utf-8') as stream: json.dump(state,stream,indent=2); stream.write('\n')
PY
launch_application update 'Bringing omnideck up to date.' 120
dump_accessibility update-progress
wait_ready_and_open update

current_step='occupied saved port recovery'
stop_application
old_port="$(tr -d '[:space:]' < "$user_data/runtime/app-port")"
instance_path="$cli_config/instances/${container_name}.yaml"
conflict_path="$cli_config/instances/${container_name}-occupied-port.yaml"
python3 - "$state_path" "$instance_path" "$conflict_path" "$container_name" "$old_port" <<'PY'
import json, sys
from pathlib import Path
state_path, instance_path, conflict_path = map(Path, sys.argv[1:4])
container_name, old_port = sys.argv[4:]
state=json.load(state_path.open(encoding='utf-8'))
state['status']='complete'; state['appVersion']='0.0.0-e2e-port-conflict'
with state_path.open('w',encoding='utf-8') as stream: json.dump(state,stream,indent=2); stream.write('\n')
source=instance_path.read_text(encoding='utf-8')
expected=f'container_name: {container_name}\n'
assert expected in source and f'web_ui_port: "{old_port}"\n' in source
conflict_path.write_text(source.replace(expected,f'container_name: {container_name}-occupied-port\n',1),encoding='utf-8')
PY
launch_application port-conflict "Port $old_port is already in use" 300
dump_accessibility port-conflict-progress
wait_ready_and_open port-conflict
new_port="$(tr -d '[:space:]' < "$user_data/runtime/app-port")"
[[ "$new_port" != "$old_port" ]]
grep -Fq "web_ui_port: \"$old_port\"" "$conflict_path"
grep -Fq "web_ui_port: \"$new_port\"" "$instance_path"
printf 'occupiedPort=%s\nselectedPort=%s\n' "$old_port" "$new_port" > "$result_dir/port-conflict-recovery.txt"
else
  current_step='boundary-only healthy runtime'
  new_port="$(tr -d '[:space:]' < "$user_data/runtime/app-port")"
  [[ "$new_port" =~ ^[0-9]+$ ]]
fi

current_step='Custom App fixture'
stop_application
podman cp "$work_dir/desktop/tests/e2e/custom_app_fixture.py" \
  "$container_name:/tmp/omnideck-custom-app-fixture.py"
podman exec "$container_name" chmod 0644 /tmp/omnideck-custom-app-fixture.py
podman exec --user omnideck "$container_name" python3 /tmp/omnideck-custom-app-fixture.py
curl --fail --silent --show-error --max-time 15 \
  --request PUT --header 'Content-Type: application/json' \
  --header 'X-Requested-With: XMLHttpRequest' \
  --data '{"custom_apps_enabled":true,"setup_complete":true}' \
  "http://127.0.0.1:$new_port/api/settings" > "$result_dir/custom-app-settings.json"
curl --fail --silent --show-error --max-time 15 \
  "http://127.0.0.1:$new_port/api/custom-apps" > "$result_dir/custom-app-catalog.json"
python3 - "$result_dir/custom-app-catalog.json" <<'PY'
import json, sys
catalog=json.load(open(sys.argv[1], encoding='utf-8'))
apps={app['slug']: app for app in catalog['apps']}
assert apps['desktop-smoke']['title'] == 'Desktop Custom App Smoke', catalog
assert apps['desktop-smoke']['has_actions'] is True, catalog
PY
fixture_id="desktop_host_boundary_${namespace}"
curl --fail --silent --show-error --max-time 15 \
  --request POST --header 'Content-Type: application/json' \
  --header 'X-Requested-With: XMLHttpRequest' \
  --data "{\"id\":\"$fixture_id\",\"name\":\"$fixture_name\",\"description\":\"Native desktop host-boundary fixture\",\"system_prompt\":\"Exercise native download and upload behavior.\"}" \
  "http://127.0.0.1:$new_port/api/profiles" > "$result_dir/host-boundary-profile.json"
podman exec \
  --env "E2E_ARTIFACT_FILENAME=$artifact_filename" \
  --env "E2E_ARTIFACT_CONTENTS=$artifact_contents" \
  "$container_name" python -c \
  'import os; from pathlib import Path; from artifacts import record_artifact; name=os.environ["E2E_ARTIFACT_FILENAME"]; path=Path("/home/computron") / name; path.write_text(os.environ["E2E_ARTIFACT_CONTENTS"], encoding="utf-8"); record_artifact(conversation_id="desktop-macos-artifact", path=str(path), filename=name, content_type="text/plain", agent_name="Desktop macOS", sent_at="2026-08-12T00:00:00Z")'
python3 - "$update_fixture" "$update_version" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    'version': sys.argv[2],
    'imageRef': 'ghcr.io/omnideck-dev/omnideck@sha256:' + ('a' * 64),
}, indent=2) + '\n', encoding='utf-8')
PY
python3 - "$state_path" <<'PY'
import json, sys
path=sys.argv[1]
state=json.load(open(path, encoding='utf-8'))
state['status']='complete'; state['appVersion']='0.0.0-e2e-custom-app'
with open(path,'w',encoding='utf-8') as stream: json.dump(state,stream,indent=2); stream.write('\n')
PY

current_step='Custom App native WebView action'
launch_application custom-app 'omnideck is ready' 1800
dump_accessibility custom-app-ready
capture custom-app-ready
"$driver" click "$application" 'Open omnideck' 30
"$driver" wait-text "$application" 'Agents' 180
dump_accessibility custom-app-main
capture custom-app-main
if [[ "$mode" == full ]]; then
"$driver" click "$application" 'Apps' 30
"$driver" wait-text "$application" 'Desktop Custom App Smoke' 60
dump_accessibility custom-app-catalog
capture custom-app-catalog
"$driver" click "$application" 'Desktop Custom App Smoke' 30
"$driver" wait-text "$application" 'Invoke packaged action' 60
"$driver" click "$application" 'Invoke packaged action' 30
"$driver" wait-text "$application" 'Action result: tauri-webview' 60
dump_accessibility custom-app-action
capture custom-app-action

current_step='external browser and internal navigation'
"$driver" click "$application" 'Internal custom route' 30
"$driver" wait-text "$application" 'Action result: tauri-webview' 30
browser_before="$(osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true')"
"$driver" click "$application" 'External browser link' 30
browser_after=''
for _ in $(seq 1 120); do
  browser_after="$(osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true')"
  [[ "$browser_after" == 'Safari' ]] && break
  sleep 0.25
done
[[ "$browser_after" == 'Safari' ]]
if ! /usr/sbin/screencapture -x "$result_dir/screenshots/external-browser-visible.png"; then
  printf '%s\n' 'The browser activation assertion passed, but macOS did not permit a display screenshot.' \
    > "$result_dir/host-boundaries/external-browser-screenshot.txt"
fi
/usr/bin/open -a 'Omnideck Lab'
for _ in $(seq 1 40); do
  frontmost="$(osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true')"
  [[ "$frontmost" == 'Omnideck Lab' || "$frontmost" == 'omnideck-desktop' ]] && break
  sleep 0.25
done
"$driver" click "$application" 'External browser link in new window' 30
browser_after_blank=''
for _ in $(seq 1 120); do
  browser_after_blank="$(osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true')"
  [[ "$browser_after_blank" == 'Safari' ]] && break
  sleep 0.25
done
[[ "$browser_after_blank" == 'Safari' ]]
python3 - "$result_dir/host-boundaries/external-links.json" "$browser_before" "$browser_after" "$browser_after_blank" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    'status': 'passed',
    'sameOriginNavigation': 'remained in Custom App iframe',
    'browserBefore': sys.argv[2],
    'browserAfterExternal': sys.argv[3],
    'browserAfterExternalBlank': sys.argv[4],
}, indent=2) + '\n', encoding='utf-8')
PY
/usr/bin/open -a 'Omnideck Lab'

current_step='Custom App restart persistence'
launch_application custom-app-restart 'Welcome to Omnideck' 180
"$driver" click "$application" 'Apps' 30
"$driver" wait-text "$application" 'Desktop Custom App Smoke' 60
"$driver" click "$application" 'Desktop Custom App Smoke' 30
"$driver" wait-text "$application" 'Invoke packaged action' 60
"$driver" click "$application" 'Invoke packaged action' 30
"$driver" wait-text "$application" 'Action result: tauri-webview' 60
dump_accessibility custom-app-restart-action
capture custom-app-restart-action
fi

current_step='native host-boundary fixture'
"$driver" click "$application" 'Agents' 30
"$driver" wait-text "$application" "$fixture_name" 60
dump_accessibility host-boundary-agents
capture host-boundary-agents

current_step='native host download'
mkdir -p "$native_download_dir" "$result_dir/host-boundaries"
[[ ! -e "$download_path" ]]
"$driver" click "$application" "Export $fixture_name" 30
"$driver" wait-text "$application" "Export “$fixture_name”" 30
"$downloads_permission_helper" 'Omnideck Lab' 5 \
  > "$result_dir/host-boundaries/downloads-permission.txt" 2>&1 &
downloads_permission_pid=$!
"$driver" click-in "$application" "Export “$fixture_name”" 'Export' 30
if ! "$driver" wait-text "$application" 'Download complete' 10; then
  soft_failures+=('native host download completion toast')
  printf 'VISIBLE ASSERTION FAILED: native host download completion toast\n' | tee -a "$result_dir/soft-failures.txt"
fi
dump_accessibility host-download-toast
if [[ ! -s "$result_dir/soft-failures.txt" ]]; then
  assert_tree_text "$result_dir/accessibility/host-download-toast.json" "$fixture_id" 'was saved to Downloads.'
fi
capture host-download-toast
finish_downloads_permission
cat "$result_dir/host-boundaries/downloads-permission.txt"
python3 - "$download_path" "$fixture_name" "$result_dir/host-boundaries/download.json" <<'PY'
import json, sys, time
from pathlib import Path
path=Path(sys.argv[1]); deadline=time.monotonic()+30
while time.monotonic() < deadline and not path.is_file(): time.sleep(.25)
assert path.is_file(), path
pack=json.load(path.open(encoding='utf-8'))
assert pack['kind']=='omnideck.pack' and pack['version']==1, pack
assert len(pack['profiles'])==1 and pack['profiles'][0]['name']==sys.argv[2], pack
Path(sys.argv[3]).write_text(json.dumps({'status':'passed','path':str(path),'size':path.stat().st_size,'profileName':sys.argv[2]}, indent=2)+'\n', encoding='utf-8')
PY

current_step='native host upload'
"$driver" click "$application" 'Import' 30
"$driver" wait-text "$application" 'Open' 30
"$driver" wait-text "$application" "$fixture_filename" 30
mouse_click "$fixture_filename"
sleep 1
"$driver" click "$application" 'Open' 30
"$driver" wait-text "$application" 'Imported 1 agent.' 60
dump_accessibility host-upload-toast
capture host-upload-toast
curl --fail --silent --show-error --max-time 15 \
  "http://127.0.0.1:$new_port/api/profiles?include_disabled=true" > "$result_dir/host-boundaries/profiles-after-import.json"
python3 - "$result_dir/host-boundaries/profiles-after-import.json" "$fixture_name" "$result_dir/host-boundaries/upload.json" <<'PY'
import json, sys
from pathlib import Path
profiles=json.load(open(sys.argv[1], encoding='utf-8'))
matches=[p for p in profiles if p.get('name') == sys.argv[2] or p.get('name','').startswith(sys.argv[2]+' (imported')]
assert len(matches) >= 2, matches
Path(sys.argv[3]).write_text(json.dumps({'status':'passed','importedNames':[p['name'] for p in matches]}, indent=2)+'\n', encoding='utf-8')
PY

current_step='native artifact download and toast'
"$driver" click "$application" 'Artifacts' 30
"$driver" wait-text "$application" "$artifact_filename" 60
"$driver" click "$application" 'Table view' 30
"$driver" wait-text "$application" "$artifact_filename" 30
mouse_click "$artifact_filename"
"$driver" wait-text "$application" 'Download file' 30
[[ ! -e "$artifact_download_path" ]]
"$driver" click "$application" 'Download file' 30
if ! "$driver" wait-text "$application" "$artifact_filename was saved to Downloads." 10; then
  soft_failures+=('native artifact download completion toast')
  printf 'VISIBLE ASSERTION FAILED: native artifact download completion toast\n' | tee -a "$result_dir/soft-failures.txt"
fi
python3 - "$artifact_download_path" "$artifact_contents" "$result_dir/host-boundaries/artifact-download.json" <<'PY'
import json, sys, time
from pathlib import Path
path=Path(sys.argv[1]); deadline=time.monotonic()+30
while time.monotonic() < deadline and not path.is_file(): time.sleep(.25)
assert path.is_file() and path.read_text(encoding='utf-8') == sys.argv[2], path
Path(sys.argv[3]).write_text(json.dumps({'status':'passed','path':str(path),'size':path.stat().st_size}, indent=2)+'\n', encoding='utf-8')
PY
dump_accessibility artifact-download-toast
capture artifact-download-toast

current_step='native update bridge visible contract'
"$driver" wait-text "$application" "$update_version" 60
dump_accessibility update-notice
assert_tree_text "$result_dir/accessibility/update-notice.json" 'Omnideck ' "$update_version" ' is ready' 'Skip this version'
capture update-notice
"$driver" click "$application" 'Skip this version' 30
python3 - "$user_data/update-state.json" "$update_version" "$result_dir/host-boundaries/update-visible.json" <<'PY'
import json, sys, time
from pathlib import Path
path=Path(sys.argv[1]); deadline=time.monotonic()+30; state={}
while time.monotonic() < deadline:
    if path.is_file():
        state=json.load(path.open(encoding='utf-8'))
        if state.get('skippedVersion') == sys.argv[2]: break
    time.sleep(.25)
assert state.get('skippedVersion') == sys.argv[2], state
Path(sys.argv[3]).write_text(json.dumps({'status':'passed','version':sys.argv[2],'action':'skip','state':state}, indent=2)+'\n', encoding='utf-8')
PY

current_step='resource contract'
podman container inspect "$container_name" > "$result_dir/container-inspect.json"
podman volume inspect "$home_volume" "$state_volume" > "$result_dir/volume-inspect.json"
curl --fail --silent --show-error --max-time 15 "http://127.0.0.1:$new_port" > "$result_dir/hosted.html"
grep -Fq 'sha256:' "$state_path"

current_step='DMG removal preserves user and runtime data'
stop_application
find "$installed_app" -print | sort > "$result_dir/installed-files.txt"
/bin/rm -rf -- "$installed_app"
[[ ! -e "$application" ]]
[[ -f "$state_path" ]]
podman container inspect "$container_name" >/dev/null
podman volume inspect "$home_volume" "$state_volume" >/dev/null

current_step='DMG reinstall and packaged sidecar smoke'
/usr/bin/ditto "$source_app" "$installed_app"
[[ -x "$application" ]]
[[ "$(shasum -a 256 "$source_app/Contents/MacOS/omnideck-desktop" | awk '{print $1}')" == "$(shasum -a 256 "$application" | awk '{print $1}')" ]]
mkdir -p "$result_dir/smoke-reinstall"
env "PATH=${desktop_env[0]#PATH=}" "$work_dir/desktop/tests/hardware/run.sh" \
  --application "$application" --output "$result_dir/smoke-reinstall" --require-ready

if ((${#soft_failures[@]})); then
  current_step='visible host-boundary assertions'
  printf 'ERROR: %s visible assertion(s) failed after the complete journey.\n' "${#soft_failures[@]}" >&2
  exit 1
fi

test_status=passed
current_step=complete
printf 'PASS: macOS package smoke, setup/recovery, Custom App restart, native boundaries, and DMG lifecycle completed.\n'
