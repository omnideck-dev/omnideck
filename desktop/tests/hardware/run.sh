#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
desktop_root="$(CDPATH= cd -- "$script_dir/../.." && pwd)"
application=""
output_directory="${OMNIDECK_DESKTOP_SMOKE_OUTPUT_DIR:-}"
timeout_seconds=45
require_ready=false

usage() {
  echo "Usage: $0 --application PATH [--output DIR] [--timeout SECONDS] [--require-ready]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --application) application="${2:?Missing application path}"; shift 2 ;;
    --output) output_directory="${2:?Missing output directory}"; shift 2 ;;
    --timeout) timeout_seconds="${2:?Missing timeout}"; shift 2 ;;
    --require-ready) require_ready=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

[[ -n "$application" ]] || { usage >&2; exit 1; }
[[ -x "$application" ]] || { echo "Application is not executable: $application" >&2; exit 1; }
[[ "$timeout_seconds" =~ ^[0-9]+$ ]] || { echo "Timeout must be an integer." >&2; exit 1; }
(( timeout_seconds >= 5 && timeout_seconds <= 300 )) || { echo "Timeout must be between 5 and 300 seconds." >&2; exit 1; }
command -v node >/dev/null 2>&1 || { echo "Node.js is required to validate the packaged smoke proof." >&2; exit 1; }

if pgrep -f '(^|/)omnideck-desktop([[:space:]]|$)' >/dev/null 2>&1; then
  echo "Close every existing omnideck-desktop process before running packaged smoke." >&2
  exit 1
fi
if [[ "$(uname -s)" == "Linux" && -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  echo "A real X11 or Wayland session is required for native desktop smoke." >&2
  exit 1
fi

run_id="${GITHUB_RUN_ID:-local-$$}"
if [[ -z "$output_directory" ]]; then
  output_directory="$desktop_root/../artifacts/desktop-hardware/$(uname -s | tr '[:upper:]' '[:lower:]')-$run_id"
fi
mkdir -p "$output_directory/user-data"
proof_path="$output_directory/smoke-proof.json"
report_path="$output_directory/report.json"
stdout_path="$output_directory/host.stdout.log"
stderr_path="$output_directory/host.stderr.log"
rm -f -- "$proof_path"

application="$(CDPATH= cd -- "$(dirname -- "$application")" && pwd)/$(basename -- "$application")"
OMNIDECK_DESKTOP_SMOKE_FILE="$proof_path" \
OMNIDECK_DESKTOP_USER_DATA="$output_directory/user-data" \
  "$application" >"$stdout_path" 2>"$stderr_path" &
application_pid=$!

cleanup() {
  if kill -0 "$application_pid" >/dev/null 2>&1; then
    kill "$application_pid" >/dev/null 2>&1 || true
    wait "$application_pid" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

deadline=$((SECONDS + timeout_seconds))
while [[ ! -f "$proof_path" ]]; do
  if ! kill -0 "$application_pid" >/dev/null 2>&1; then
    echo "The desktop host exited before writing a packaged smoke proof." >&2
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "The desktop host did not write a packaged smoke proof within $timeout_seconds seconds." >&2
    exit 1
  fi
  sleep 0.25
done

validation=(
  node "$script_dir/validate-proof.mjs"
  --proof "$proof_path"
  --application "$application"
  --report "$report_path"
)
if [[ "$require_ready" == "true" ]]; then
  validation+=(--require-ready)
fi
"${validation[@]}"
echo "Evidence: $report_path"
