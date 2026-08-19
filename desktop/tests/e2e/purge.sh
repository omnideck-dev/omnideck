#!/usr/bin/env bash

set -Eeuo pipefail

lab_dir="${OMNIDECK_VM_LAB_DIR:-}"
assume_yes=0
[[ "${1:-}" != --yes ]] || { assume_yes=1; shift; }
run_dir="${1:-}"
[[ -n "$run_dir" && $# == 1 ]] || { printf 'Usage: %s [--yes] RUN_DIRECTORY\n' "$0" >&2; exit 2; }
[[ -n "$lab_dir" && -x "$lab_dir/lab.sh" ]] || { printf 'Set OMNIDECK_VM_LAB_DIR to the external VM lab root.\n' >&2; exit 2; }
arguments=(runs purge "$run_dir")
[[ "$assume_yes" != 1 ]] || arguments+=(--yes)
exec "$lab_dir/lab.sh" "${arguments[@]}"
