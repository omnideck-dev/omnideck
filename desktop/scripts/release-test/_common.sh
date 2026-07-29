#!/usr/bin/env bash

RELEASE_REPOSITORY="omnideck-dev/omnideck"
TEST_NAMESPACE="release-test-default"
SYNTHETIC_IMAGE_REF="ghcr.io/omnideck-dev/omnideck@sha256:0000000000000000000000000000000000000000000000000000000000000000"
GH_AUTH_CONFIG_DIR="${GH_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/gh}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

validate_profile_name() {
  if [[ ! "$1" =~ ^[a-z0-9][a-z0-9-]{0,17}$ ]]; then
    echo "Profile names may contain up to 18 lowercase letters, numbers, and hyphens." >&2
    exit 1
  fi
}

select_release() {
  local requested="$1"
  local selected
  require_command gh
  gh auth status >/dev/null

  if [[ "$requested" == "choose" ]]; then
    echo "Recent omnideck releases:" >&2
    gh release list \
      --repo "$RELEASE_REPOSITORY" \
      --limit 10 \
      --json tagName,publishedAt,isDraft \
      --jq '.[] | select(.isDraft == false) | "\(.tagName)  \(.publishedAt)"' >&2
    read -r -p "Release tag: " selected
  elif [[ "$requested" == "latest" ]]; then
    selected="$(
      gh release list \
        --repo "$RELEASE_REPOSITORY" \
        --limit 20 \
        --json tagName,publishedAt,isDraft \
        --jq 'map(select(.isDraft == false)) | sort_by(.publishedAt) | reverse | .[0].tagName'
    )"
  else
    selected="$requested"
  fi

  if [[ ! "$selected" =~ ^v[0-9A-Za-z._-]+$ ]]; then
    echo "Could not select a valid release tag." >&2
    exit 1
  fi
  printf '%s\n' "$selected"
}

require_isolated_release() {
  local selected="$1"
  if [[ "$selected" =~ ^v0\.1\.0-alpha\.([0-9]+)$ ]] \
    && (( BASH_REMATCH[1] < 4 )); then
    echo "Release $selected predates isolated release-test resources." >&2
    echo "Choose v0.1.0-alpha.4 or newer so testing cannot touch a normal omnideck environment." >&2
    exit 1
  fi
}

confirm_reset() {
  local description="$1"
  local skip_confirmation="$2"
  if [[ "$skip_confirmation" == "true" ]]; then
    return
  fi
  echo "$description"
  read -r -p "Type ${TEST_NAMESPACE} to continue: " answer
  if [[ "$answer" != "$TEST_NAMESPACE" ]]; then
    echo "Cancelled."
    exit 0
  fi
}

find_podman() {
  if command -v podman >/dev/null 2>&1; then
    command -v podman
    return
  fi
  for candidate in /opt/podman/bin/podman /usr/local/bin/podman /opt/homebrew/bin/podman; do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
}

configure_test_environment() {
  local profile_root="$1"
  export OMNIDECK_DESKTOP_USER_DATA="$profile_root"
  export OMNIDECK_DESKTOP_TEST_NAMESPACE="$TEST_NAMESPACE"
  export GH_CONFIG_DIR="$GH_AUTH_CONFIG_DIR"
  export XDG_CACHE_HOME="$profile_root/runtime/cache"
  export XDG_CONFIG_HOME="$profile_root/runtime/config"
  export XDG_DATA_HOME="$profile_root/runtime/data"
  export REGISTRY_AUTH_FILE="$profile_root/runtime/auth/auth.json"
}

# Everything the reset paths are allowed to destroy is derived from the
# namespace, so a name that is not one of these belongs to somebody else.
test_container_name() { printf 'omnideck-desktop-%s\n' "$TEST_NAMESPACE"; }
test_home_volume_name() { printf 'omnideck-desktop-home-%s\n' "$TEST_NAMESPACE"; }
test_state_volume_name() { printf 'omnideck-desktop-state-%s\n' "$TEST_NAMESPACE"; }
test_machine_name() { printf 'omnideck-runtime-%s\n' "$TEST_NAMESPACE"; }

is_test_resource() {
  local name="$1"
  [[ "$name" == "$(test_container_name)" ]] \
    || [[ "$name" == "$(test_home_volume_name)" ]] \
    || [[ "$name" == "$(test_state_volume_name)" ]] \
    || [[ "$name" == "$(test_machine_name)" ]]
}

# Prints every container, volume and machine on the host and marks which ones a
# reset would remove. This is the check that matters before running anything
# destructive: if a name you care about is listed as preserved, it stays.
report_resource_inventory() {
  local podman_path
  podman_path="$(find_podman || true)"
  if [[ -z "$podman_path" ]]; then
    echo "Podman is not installed, so there is nothing to inventory."
    return
  fi

  local kind listing name
  for kind in container volume machine; do
    case "$kind" in
      container) listing="$("$podman_path" ps --all --format '{{.Names}}' 2>/dev/null || true)" ;;
      volume) listing="$("$podman_path" volume ls --format '{{.Name}}' 2>/dev/null || true)" ;;
      machine) listing="$("$podman_path" machine list --format '{{.Name}}' 2>/dev/null || true)" ;;
    esac
    echo "${kind}s:"
    if [[ -z "$listing" ]]; then
      echo "  (none)"
      continue
    fi
    while IFS= read -r name; do
      [[ -z "$name" ]] && continue
      # podman marks the active machine with a trailing asterisk.
      name="${name%\*}"
      if is_test_resource "$name"; then
        echo "  REMOVE    $name"
      else
        echo "  preserved $name"
      fi
    done <<< "$listing"
  done
}

remove_test_container() {
  local podman_path
  podman_path="$(find_podman || true)"
  if [[ -z "$podman_path" ]]; then
    return
  fi
  "$podman_path" rm --force "omnideck-desktop-${TEST_NAMESPACE}" >/dev/null 2>&1 || true
}

remove_test_resources() {
  local podman_path
  podman_path="$(find_podman || true)"
  if [[ -z "$podman_path" ]]; then
    return
  fi

  "$podman_path" rm --force "omnideck-desktop-${TEST_NAMESPACE}" >/dev/null 2>&1 || true
  "$podman_path" volume rm --force \
    "omnideck-desktop-home-${TEST_NAMESPACE}" \
    "omnideck-desktop-state-${TEST_NAMESPACE}" >/dev/null 2>&1 || true
  "$podman_path" machine stop "omnideck-runtime-${TEST_NAMESPACE}" >/dev/null 2>&1 || true
  "$podman_path" machine rm --force "omnideck-runtime-${TEST_NAMESPACE}" >/dev/null 2>&1 || true
}

# Removes the podman package while leaving image and volume storage on disk.
# Distribution package managers keep ~/.local/share/containers untouched, so
# reinstalling brings existing containers and volumes back exactly as they were.
# `remove` is deliberate: `purge` and `autoremove` reach beyond podman itself.
uninstall_podman_linux() {
  local dry_run="$1"
  local distro_id
  distro_id="$(
    sed -n 's/^ID=//p' /etc/os-release 2>/dev/null | tr -d '"' | head -n 1
  )"

  local -a command=()
  case "$distro_id" in
    ubuntu | debian | linuxmint | pop) command=(apt-get remove -y podman) ;;
    fedora | rhel | centos | rocky | almalinux) command=(dnf remove -y podman) ;;
    arch | manjaro) command=(pacman -R --noconfirm podman) ;;
    opensuse* | sles) command=(zypper --non-interactive remove podman) ;;
    alpine) command=(apk del podman) ;;
    *)
      echo "No known uninstall command for this distribution ($distro_id)." >&2
      echo "Remove the podman package by hand, then run this script again." >&2
      return 1
      ;;
  esac

  echo "Uninstalling podman: sudo ${command[*]}"
  if [[ "$dry_run" == "true" ]]; then
    return 0
  fi
  sudo "${command[@]}"
}

# The macOS installer ships no uninstaller, so the payload directory goes and
# the receipt is forgotten. Machine disk images live under the user's container
# storage and are left alone, so a reinstall finds them again.
uninstall_podman_macos() {
  local dry_run="$1"
  local receipt
  echo "Uninstalling podman: sudo rm -rf /opt/podman"
  if [[ "$dry_run" != "true" ]]; then
    sudo rm -rf /opt/podman
  fi
  while IFS= read -r receipt; do
    [[ -z "$receipt" ]] && continue
    echo "Forgetting installer receipt: $receipt"
    if [[ "$dry_run" != "true" ]]; then
      sudo pkgutil --forget "$receipt" >/dev/null
    fi
  done < <(pkgutil --pkgs 2>/dev/null | grep -i podman || true)
}

# Returns the host to the state the application expects on a first run: no
# podman, but every container, volume and image the user already had still on
# disk. Only the namespaced test machine is destroyed, because only test
# containers are ever created inside it.
reset_host_dependencies() {
  local dry_run="$1"
  local skip_confirmation="$2"
  local podman_path

  echo "Resources on this host:"
  report_resource_inventory
  echo
  echo "A reset removes only the entries marked REMOVE above, then uninstalls"
  echo "podman itself. Container storage is left in place, so anything marked"
  echo "preserved comes back when podman is reinstalled."
  echo

  if [[ "$dry_run" == "true" ]]; then
    echo "Dry run: nothing was changed."
    return 0
  fi

  confirm_reset "This uninstalls podman from this computer." "$skip_confirmation"

  podman_path="$(find_podman || true)"
  if [[ -n "$podman_path" ]]; then
    # The test machine has to go before the binary that manages it does.
    "$podman_path" machine stop "$(test_machine_name)" >/dev/null 2>&1 || true
    "$podman_path" machine rm --force "$(test_machine_name)" >/dev/null 2>&1 || true
  else
    echo "Podman is already absent; nothing to uninstall."
    return 0
  fi

  case "$(uname -s)" in
    Linux) uninstall_podman_linux "$dry_run" ;;
    Darwin) uninstall_podman_macos "$dry_run" ;;
    *)
      echo "Unsupported platform for dependency reset: $(uname -s)" >&2
      return 1
      ;;
  esac

  if find_podman >/dev/null 2>&1; then
    echo "Podman is still on PATH. Remove the remaining copy by hand." >&2
    return 1
  fi
  echo "Podman removed. The next launch will install it from scratch."
}

write_test_setup_state() {
  local profile_root="$1"
  local status="$2"
  local reason="$3"
  mkdir -p "$profile_root"
  printf '%s\n' \
    '{' \
    '  "schemaVersion": 1,' \
    "  \"status\": \"${status}\"," \
    "  \"reason\": \"${reason}\"," \
    '  "appVersion": "test-script",' \
    "  \"imageRef\": \"${SYNTHETIC_IMAGE_REF}\"," \
    '  "imageDigest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",' \
    '  "updatedAt": "test-script"' \
    '}' > "$profile_root/setup-state.json"
  chmod 600 "$profile_root/setup-state.json"
}

require_completed_setup() {
  local profile_root="$1"
  if [[ ! -f "$profile_root/setup-state.json" ]] \
    || ! grep -q '"status": "complete"' "$profile_root/setup-state.json"; then
    echo "This scenario needs a completed test profile first." >&2
    echo "Run the first-run scenario, finish setup, and then try again." >&2
    exit 1
  fi
}

prepare_test_scenario() {
  local scenario="$1"
  local profile_root="$2"
  local profiles_root="$3"
  local skip_confirmation="$4"

  case "$profile_root" in
    "$profiles_root"/*) ;;
    *)
      echo "Refusing to modify a profile outside $profiles_root" >&2
      exit 1
      ;;
  esac

  configure_test_environment "$profile_root"
  case "$scenario" in
    keep)
      ;;
    first-run)
      confirm_reset \
        "This removes only the isolated ${TEST_NAMESPACE} container, machine, volumes, and profile at: $profile_root" \
        "$skip_confirmation"
      remove_test_resources
      if [[ -d "$profile_root" ]]; then
        rm -rf -- "$profile_root"
      fi
      ;;
    resume)
      confirm_reset \
        "This removes the isolated test container, preserves cached work and volumes, and marks setup interrupted." \
        "$skip_confirmation"
      remove_test_container
      write_test_setup_state "$profile_root" "in-progress" "first-run"
      ;;
    update)
      require_completed_setup "$profile_root"
      confirm_reset \
        "This removes the isolated test container, preserves its volumes, and marks the pinned environment as older." \
        "$skip_confirmation"
      remove_test_container
      write_test_setup_state "$profile_root" "complete" "first-run"
      ;;
    doctor)
      require_completed_setup "$profile_root"
      confirm_reset \
        "This removes only the isolated test container so the next launch opens diagnostics." \
        "$skip_confirmation"
      remove_test_container
      ;;
    returning)
      require_completed_setup "$profile_root"
      ;;
    *)
      echo "Unknown scenario: $scenario" >&2
      exit 1
      ;;
  esac
}
