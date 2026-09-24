#!/usr/bin/env bash
# Returns this computer to a pre-install state so the desktop application can be
# tested from scratch: podman is uninstalled and the isolated test machine is
# destroyed. Containers, volumes and images that belong to anything else stay
# exactly where they are.
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$script_dir/_common.sh"

profile="default"
dry_run="false"
skip_confirmation="false"
inventory_only="false"

usage() {
  cat <<'USAGE'
Usage: reset-host.sh [--profile NAME] [--dry-run] [--inventory] [--yes]

  --profile NAME  Test profile whose machine is destroyed (default: default)
  --inventory     Only list containers, volumes and machines, changing nothing
  --dry-run       Show every step without running it
  --yes           Skip the confirmation prompt (disposable machines only)

Uninstalls podman and removes the isolated test machine. Container and volume
storage is preserved, so existing containers reappear once podman is
reinstalled. Run with --inventory first to see exactly what is affected.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) profile="${2:?Missing profile name}"; shift 2 ;;
    --dry-run) dry_run="true"; shift ;;
    --inventory) inventory_only="true"; shift ;;
    --yes) skip_confirmation="true"; shift ;;
    --help | -h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

validate_profile_name "$profile"
TEST_NAMESPACE="release-test-${profile}"

if [[ "$inventory_only" == "true" ]]; then
  report_resource_inventory
  exit 0
fi

reset_host_dependencies "$dry_run" "$skip_confirmation"
