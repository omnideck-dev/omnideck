#!/usr/bin/env bash

set -Eeuo pipefail

lab_dir="${OMNIDECK_VM_LAB_DIR:-}"
assume_yes=0
[[ "${1:-}" != "--yes" ]] || { assume_yes=1; shift; }
run_input="${1:-}"
[[ -n "${run_input}" && $# == 1 ]] || { printf 'Usage: %s [--yes] RUN_DIRECTORY\n' "$0" >&2; exit 2; }
[[ -n "${lab_dir}" ]] || { printf 'Set OMNIDECK_VM_LAB_DIR to the external VM lab root.\n' >&2; exit 2; }
lab_dir="$(cd "${lab_dir}" && pwd -P)"
artifact_root="$(realpath -e "${lab_dir}/artifacts/desktop-release")"
run_dir="$(realpath -e "${run_input}")"
[[ "$(dirname "${run_dir}")" == "${artifact_root}" ]] || { printf 'Refusing path outside %s\n' "${artifact_root}" >&2; exit 1; }
[[ -f "${run_dir}/run.json" ]] || { printf 'Missing qualification marker: %s/run.json\n' "${run_dir}" >&2; exit 1; }

run_name="$(basename "${run_dir}")"
du -sh -- "${run_dir}"
if [[ "${assume_yes}" != "1" ]]; then
  [[ -t 0 ]] || { printf 'Re-run interactively or pass --yes.\n' >&2; exit 2; }
  printf 'Type %s to permanently purge this qualification: ' "${run_name}"
  read -r confirmation
  [[ "${confirmation}" == "${run_name}" ]] || { printf 'Canceled.\n'; exit 1; }
fi

while IFS= read -r manifest; do
  while IFS= read -r path; do
    [[ -n "${path}" && -e "${path}" ]] || continue
    [[ "$(dirname "${path}")" == "${lab_dir}/discarded" ]] || { printf 'Refusing unexpected discarded path: %s\n' "${path}" >&2; exit 1; }
    case "$(basename "${path}")" in
      appimage.qcow2.*|deb.qcow2.*|rpm.qcow2.*|atomic.qcow2.*|windows.qcow2.*) [[ -f "${path}" ]] && unlink "${path}" ;;
      windows-tpm.*) [[ -d "${path}" ]] && rm -r -- "${path}" ;;
      *) printf 'Refusing unexpected discarded name: %s\n' "${path}" >&2; exit 1 ;;
    esac
  done < "${manifest}"
done < <(find "${run_dir}/lanes" -mindepth 2 -maxdepth 2 -type f -name discarded-created.txt -print 2>/dev/null | sort)

rm -r -- "${run_dir}"
printf 'Purged Desktop release qualification: %s\n' "${run_name}"
