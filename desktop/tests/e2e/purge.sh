#!/usr/bin/env bash

set -Eeuo pipefail

lab_dir="${OMNIDECK_VM_LAB_DIR:-}"
assume_yes=0

usage() {
  cat <<'EOF'
Usage: ./desktop/tests/e2e/purge.sh [--yes] RUN_DIRECTORY

Delete one marked Desktop VM E2E run folder and any retained disposable disk
or Windows TPM state listed by that run. RUN_DIRECTORY must be a direct child
of the external lab's artifacts/desktop-e2e directory.
EOF
}

if [[ "${1:-}" == "--yes" ]]; then
  assume_yes=1
  shift
fi
run_dir_input="${1:-}"
[[ -n "${run_dir_input}" && $# == 1 ]] || { usage >&2; exit 2; }
[[ -n "${lab_dir}" ]] || { printf 'Set OMNIDECK_VM_LAB_DIR to the external VM lab root.\n' >&2; exit 2; }
lab_dir="$(cd "${lab_dir}" && pwd -P)"

artifact_root="$(realpath -e "${lab_dir}/artifacts/desktop-e2e")"
run_dir="$(realpath -e "${run_dir_input}")"
[[ "$(dirname "${run_dir}")" == "${artifact_root}" ]] || {
  printf 'Refusing to purge a path outside %s: %s\n' "${artifact_root}" "${run_dir}" >&2
  exit 1
}
[[ -f "${run_dir}/run.json" ]] || { printf 'Missing Desktop E2E marker: %s/run.json\n' "${run_dir}" >&2; exit 1; }

run_name="$(basename "${run_dir}")"
manifest="${run_dir}/discarded-created.txt"
printf 'Run artifacts: '
du -sh -- "${run_dir}"
if [[ -s "${manifest}" ]]; then
  printf 'Retained disposable VM state:\n'
  while IFS= read -r path; do
    [[ -n "${path}" && -e "${path}" ]] && du -sh -- "${path}"
  done < "${manifest}"
fi

if [[ "${assume_yes}" != "1" ]]; then
  [[ -t 0 ]] || { printf 'Re-run interactively or pass --yes.\n' >&2; exit 2; }
  printf 'Type %s to permanently purge this run: ' "${run_name}"
  read -r confirmation
  [[ "${confirmation}" == "${run_name}" ]] || { printf 'Canceled.\n'; exit 1; }
fi

if [[ -f "${manifest}" ]]; then
  while IFS= read -r path; do
    [[ -n "${path}" && -e "${path}" ]] || continue
    [[ "$(dirname "${path}")" == "${lab_dir}/discarded" ]] || {
      printf 'Refusing unexpected discarded parent: %s\n' "${path}" >&2
      exit 1
    }
    case "$(basename "${path}")" in
      appimage.qcow2.*|deb.qcow2.*|rpm.qcow2.*|atomic.qcow2.*|windows.qcow2.*)
        [[ -f "${path}" ]] || { printf 'Expected a discarded disk file: %s\n' "${path}" >&2; exit 1; }
        unlink "${path}"
        ;;
      windows-tpm.*)
        [[ -d "${path}" ]] || { printf 'Expected discarded TPM state: %s\n' "${path}" >&2; exit 1; }
        rm -r -- "${path}"
        ;;
      *)
        printf 'Refusing unexpected discarded name: %s\n' "${path}" >&2
        exit 1
        ;;
    esac
  done < "${manifest}"
fi

rm -r -- "${run_dir}"
printf 'Purged Desktop VM E2E run: %s\n' "${run_name}"
