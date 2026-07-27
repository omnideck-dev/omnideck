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
