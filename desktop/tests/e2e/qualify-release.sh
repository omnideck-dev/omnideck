#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
desktop_root="$(cd "${script_dir}/../.." && pwd)"
repo_root="$(cd "${desktop_root}/.." && pwd)"
source "${script_dir}/_lab.sh"
release="latest"
lanes_csv="appimage,deb,rpm,atomic,windows"
assume_yes=0
keep_downloads=0
remote_native=0
cross_distro_smoke=0

usage() {
  cat <<'EOF'
Usage: ./desktop/tests/e2e/qualify-release.sh [OPTIONS]

Download and qualify one published Desktop release across every available
local VM lane. All evidence for the qualification is grouped in one purgeable
run directory. Native architectures not present in the local x64 lab remain
explicit unless the dedicated-hardware workflow is requested.

Options:
  --release latest|TAG       Published release (default: latest, prereleases included)
  --lanes LIST               Comma-separated local lanes (default: appimage,deb,rpm,atomic,windows)
  --remote-native            Also dispatch and wait for missing ARM64/macOS hardware lanes
  --cross-distro-smoke       Run non-native AppImage/DEB/RPM launch-smoke cells in Linux VMs
  --keep-downloads           Retain downloaded package bytes after the run
  --yes                      Accept all destructive disposable-guest resets
  -h, --help                 Show this help
EOF
}

while (($#)); do
  case "$1" in
    --release) release="${2:?--release requires a value}"; shift 2 ;;
    --lanes) lanes_csv="${2:?--lanes requires a value}"; shift 2 ;;
    --remote-native) remote_native=1; shift ;;
    --cross-distro-smoke) cross_distro_smoke=1; shift ;;
    --keep-downloads) keep_downloads=1; shift ;;
    --yes) assume_yes=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

require_lab
for dependency in gh node python3 sha256sum; do
  command -v "${dependency}" >/dev/null 2>&1 || { printf '%s is required.\n' "${dependency}" >&2; exit 2; }
done

# Reuse the release selector so `latest` includes published prereleases.
# shellcheck source=../../scripts/release-test/_common.sh
source "${desktop_root}/scripts/release-test/_common.sh"
selected_release="$(select_release "${release}")"
bare_version="${selected_release#v}"
[[ "${selected_release}" =~ ^v[0-9A-Za-z._-]+$ ]] || { printf 'Unsafe release tag: %s\n' "${selected_release}" >&2; exit 2; }

IFS=',' read -r -a requested_lanes <<<"${lanes_csv}"
declare -A selected=()
for lane in "${requested_lanes[@]}"; do
  case "${lane}" in
    appimage|deb|rpm|atomic|windows) selected["${lane}"]=1 ;;
    *) printf 'Unsupported qualification lane: %s\n' "${lane}" >&2; exit 2 ;;
  esac
done

if [[ "${assume_yes}" != "1" ]]; then
  [[ -t 0 ]] || { printf 'Re-run interactively or pass --yes.\n' >&2; exit 2; }
  printf 'This qualifies %s and resets only stopped disposable guests: %s\n' "${selected_release}" "${lanes_csv}"
  printf 'Type %s to continue: ' "${selected_release}"
  read -r confirmation
  [[ "${confirmation}" == "${selected_release}" ]] || { printf 'Canceled.\n'; exit 1; }
fi

run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$-${selected_release#v}"
safe_run_id="$(printf '%s' "${run_id}" | tr -cd '[:alnum:]_.-')"
source_commit="$(git -C "${desktop_root}" rev-parse --short=12 HEAD)"
run_root="$("${lab_dir}/lab.sh" artifact-path desktop release "${safe_run_id}")"
download_dir="${run_root}/downloads"
lane_root="${run_root}/lanes"
remote_root="${run_root}/remote"
status_file="${run_root}/lane-status.tsv"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p "${download_dir}" "${lane_root}" "${remote_root}"
: > "${status_file}"
"${lab_dir}/lab.sh" evidence-init "${run_root}" desktop release "${safe_run_id}" \
  "${source_commit}" multi qualification "release=${selected_release}" "lanes=${lanes_csv}"

record() {
  local name="$1" status="$2" requirement="$3" evidence="$4" detail="$5"
  detail="${detail//$'\t'/ }"
  detail="${detail//$'\n'/ }"
  printf '%s\t%s\t%s\t%s\t%s\n' "${name}" "${status}" "${requirement}" "${evidence}" "${detail}" >> "${status_file}"
}

finalized=0
finish_report() {
  local original_status=$?
  set +e
  if [[ "${keep_downloads}" != "1" && -d "${download_dir}" ]]; then
    find "${download_dir}" -depth -mindepth 1 -delete
    rmdir "${download_dir}" 2>/dev/null || true
  fi
  python3 "${script_dir}/qualification_report.py" \
    --release "${selected_release}" \
    --run-id "${safe_run_id}" \
    --started-at "${started_at}" \
    --status-file "${status_file}" \
    --output "${run_root}"
  report_status=$?
  final_status="${report_status}"
  [[ "${original_status}" == "0" ]] || final_status="${original_status}"
  if [[ "${final_status}" == "0" ]]; then
    "${lab_dir}/lab.sh" evidence-finish "${run_root}" passed || final_status=1
  else
    "${lab_dir}/lab.sh" evidence-finish "${run_root}" failed || true
  fi
  finalized=1
  printf 'Published-release qualification evidence: %s\n' "${run_root}"
  exit "${final_status}"
}
trap '[[ "${finalized}" == "1" ]] || finish_report' EXIT

preflight_failed=0
cross_preflight_recorded=0
for lane in appimage deb rpm atomic windows; do
  if [[ -z "${selected[${lane}]:-}" ]]; then
    if [[ "${cross_distro_smoke}" != "1" || "${lane}" == "windows" ]]; then
      continue
    fi
  fi
  lane_status="$("${lab_dir}/lab.sh" status "${lane}")"
  if ! grep -Eq "^${lane} stopped " <<<"${lane_status}"; then
    if [[ -n "${selected[${lane}]:-}" ]]; then
      record "${lane}-x64-vm" blocked required "lanes/${lane}" "guest is already running; ownership was preserved"
    fi
    if [[ "${cross_distro_smoke}" == "1" && "${lane}" != "windows" && "${cross_preflight_recorded}" == "0" ]]; then
      record linux-cross-distro-smoke-matrix blocked required cross-distro-smoke "${lane} guest is already running; ownership was preserved"
      cross_preflight_recorded=1
    fi
    preflight_failed=1
  fi
done
if [[ "${preflight_failed}" == "1" ]]; then
  for lane in appimage deb rpm atomic windows; do
    [[ -n "${selected[${lane}]:-}" ]] || continue
    if ! grep -Fq "${lane}-x64-vm" "${status_file}"; then
      record "${lane}-x64-vm" blocked required "lanes/${lane}" "qualification did not start because another selected guest was occupied"
    fi
  done
  if [[ "${cross_distro_smoke}" == "1" && "${cross_preflight_recorded}" == "0" ]]; then
    record linux-cross-distro-smoke-matrix blocked required cross-distro-smoke "qualification did not start because another selected guest was occupied"
  fi
  record artifact-matrix blocked required reports/release-contract.json "guest preflight failed before package download"
  finish_report
fi

printf 'Downloading the complete ten-package matrix for %s.\n' "${selected_release}"
contract_status=0
gh release download "${selected_release}" \
  --repo "${RELEASE_REPOSITORY}" \
  --pattern 'omnideck*' \
  --dir "${download_dir}" \
  > "${run_root}/download.log" 2>&1 || contract_status=$?
if [[ "${contract_status}" == "0" ]]; then
  mkdir -p "${run_root}/reports"
  node "${desktop_root}/tests/releasecontract/verify-release.mjs" \
    --directory "${download_dir}" \
    --version "${selected_release}" \
    --report "${run_root}/reports/release-contract.json" \
    > "${run_root}/release-contract.log" 2>&1 || contract_status=$?
fi
if [[ "${contract_status}" == "0" ]]; then
  while IFS= read -r -d '' package; do
    gh attestation verify "${package}" --repo "${RELEASE_REPOSITORY}" \
      >> "${run_root}/attestations.log" 2>&1 || { contract_status=$?; break; }
  done < <(find "${download_dir}" -maxdepth 1 -type f ! -name '*.sha256' -print0 | sort -z)
fi
if [[ "${contract_status}" != "0" ]]; then
  record artifact-matrix failed required reports/release-contract.json "download, checksum, format, architecture, or provenance verification failed"
  for lane in appimage deb rpm atomic windows; do
    [[ -n "${selected[${lane}]:-}" ]] || continue
    record "${lane}-x64-vm" blocked required "lanes/${lane}" "published artifact contract failed"
  done
  finish_report
fi
record artifact-matrix passed required reports/release-contract.json "all ten packages, checksums, formats, architectures, and attestations verified"

gh api \
  -H 'Accept: application/vnd.github.raw+json' \
  "/repos/${RELEASE_REPOSITORY}/contents/desktop/src-tauri/binaries/vendor-manifest.json?ref=${selected_release}" \
  > "${run_root}/release-vendor-manifest.json"
release_cli_version="$(node -e 'const m=require(process.argv[1]); process.stdout.write(m.version)' "${run_root}/release-vendor-manifest.json")"
release_cli_commit="$(node -e 'const m=require(process.argv[1]); process.stdout.write(m.commit)' "${run_root}/release-vendor-manifest.json")"

artifact_for_lane() {
  case "$1" in
    appimage|atomic) printf '%s/omnideck_%s_amd64.AppImage\n' "${download_dir}" "${bare_version}" ;;
    deb) printf '%s/omnideck_%s_amd64.deb\n' "${download_dir}" "${bare_version}" ;;
    rpm) printf '%s/omnideck-%s-1.x86_64.rpm\n' "${download_dir}" "${bare_version}" ;;
    windows) printf '%s/omnideck_%s_x64-setup.exe\n' "${download_dir}" "${bare_version}" ;;
  esac
}

for lane in appimage deb rpm atomic windows; do
  [[ -n "${selected[${lane}]:-}" ]] || continue
  lane_dir="${lane_root}/${lane}"
  mkdir -p "${lane_dir}"
  artifact="$(artifact_for_lane "${lane}")"
  lane_arguments=(--vm "${lane}" --artifact "${artifact}" --profile release-clean --yes)
  if [[ "${lane}" == "windows" ]]; then
    lane_arguments+=(--baseline clean)
  fi
  printf 'Running published %s lane against %s.\n' "${lane}" "$(basename "${artifact}")"
  lane_status=0
  OMNIDECK_DESKTOP_VM_E2E_OUTPUT_DIR="${lane_dir}" \
  OMNIDECK_DESKTOP_VM_E2E_CLI_VERSION="${release_cli_version}" \
  OMNIDECK_DESKTOP_VM_E2E_CLI_COMMIT="${release_cli_commit}" \
    "${script_dir}/run.sh" "${lane_arguments[@]}" \
      > >(tee "${lane_dir}/host.log") 2>&1 || lane_status=$?
  if [[ "${lane_status}" == "0" ]]; then
    record "${lane}-x64-vm" passed required "lanes/${lane}" "published package completed its native VM journey"
  else
    record "${lane}-x64-vm" failed required "lanes/${lane}" "native VM journey exited ${lane_status}"
  fi
done

if [[ "${cross_distro_smoke}" == "1" ]]; then
  cross_smoke_dir="${run_root}/cross-distro-smoke"
  mkdir -p "${cross_smoke_dir}"
  printf 'Running the non-native Linux package-open smoke matrix.\n'
  cross_smoke_status=0
  OMNIDECK_DESKTOP_VM_SMOKE_MATRIX_OUTPUT_DIR="${cross_smoke_dir}" \
  OMNIDECK_DESKTOP_VM_E2E_CLI_VERSION="${release_cli_version}" \
  OMNIDECK_DESKTOP_VM_E2E_CLI_COMMIT="${release_cli_commit}" \
    "${script_dir}/smoke-matrix.sh" \
      --appimage "$(artifact_for_lane appimage)" \
      --deb "$(artifact_for_lane deb)" \
      --rpm "$(artifact_for_lane rpm)" \
      --profile release-clean --yes > >(tee "${cross_smoke_dir}/host.log") 2>&1 || cross_smoke_status=$?
  if [[ "${cross_smoke_status}" == "0" ]]; then
    record linux-cross-distro-smoke-matrix passed required cross-distro-smoke "every non-native AppImage, DEB, and RPM launch-smoke cell passed"
  else
    record linux-cross-distro-smoke-matrix failed required cross-distro-smoke "cross-distro package smoke exited ${cross_smoke_status}"
  fi
else
  record linux-cross-distro-smoke-matrix not-run optional cross-distro-smoke "pass --cross-distro-smoke to run non-native AppImage, DEB, and RPM launch cells"
fi

record windows-arm64-static passed required reports/release-contract.json "package architecture, checksum, and provenance verified; no local ARM64 Windows VM exists"
record linux-arm64-static passed required reports/release-contract.json "AppImage, DEB, and RPM architectures, checksums, and provenance verified; no local ARM64 Linux VM exists"
record macos-x64-static passed required reports/release-contract.json "DMG structure, checksum, and provenance verified; no local macOS VM exists"
record macos-arm64-static passed required reports/release-contract.json "DMG structure, checksum, and provenance verified; no local macOS VM exists"

run_remote_lane() {
  local target="$1"
  local before_id run_id remote_status=0
  before_id="$(gh run list --repo "${RELEASE_REPOSITORY}" --workflow desktop-hardware.yml --limit 1 --json databaseId --jq '.[0].databaseId // 0')"
  gh workflow run desktop-hardware.yml \
    --repo "${RELEASE_REPOSITORY}" \
    --ref main \
    -f "version=${selected_release}" \
    -f "target=${target}" \
    -f require_ready=true \
    -f confirm=true
  run_id=""
  for _ in $(seq 1 60); do
    run_id="$(gh run list --repo "${RELEASE_REPOSITORY}" --workflow desktop-hardware.yml --event workflow_dispatch --limit 20 --json databaseId --jq "map(select(.databaseId > ${before_id})) | sort_by(.databaseId) | reverse | .[0].databaseId // empty")"
    [[ -n "${run_id}" ]] && break
    sleep 2
  done
  [[ -n "${run_id}" ]] || { record "${target}-native" failed required "remote/${target}" "workflow dispatch produced no discoverable run"; return; }
  gh run watch "${run_id}" --repo "${RELEASE_REPOSITORY}" --exit-status > "${remote_root}/${target}.log" 2>&1 || remote_status=$?
  if [[ "${remote_status}" == "0" ]]; then
    mkdir -p "${remote_root}/${target}"
    gh run download "${run_id}" --repo "${RELEASE_REPOSITORY}" --dir "${remote_root}/${target}" >> "${remote_root}/${target}.log" 2>&1 || remote_status=$?
  fi
  if [[ "${remote_status}" == "0" ]]; then
    record "${target}-native" passed required "remote/${target}" "dedicated-hardware workflow ${run_id} passed"
  else
    record "${target}-native" failed required "remote/${target}" "dedicated-hardware workflow ${run_id} failed or had no available runner"
  fi
}

if [[ "${remote_native}" == "1" ]]; then
  for target in windows-arm64 linux-arm64 macos-x64 macos-arm64; do
    run_remote_lane "${target}"
  done
else
  record windows-arm64-native not-run optional remote/windows-arm64 "pass --remote-native when a dedicated Windows ARM64 runner is online"
  record linux-arm64-native not-run optional remote/linux-arm64 "pass --remote-native when a dedicated Linux ARM64 runner is online"
  record macos-x64-native not-run optional remote/macos-x64 "pass --remote-native when a dedicated Intel macOS runner is online"
  record macos-arm64-native not-run optional remote/macos-arm64 "pass --remote-native when a dedicated Apple Silicon runner is online"
fi

finish_report
