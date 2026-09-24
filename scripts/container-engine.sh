#!/usr/bin/env bash

set -euo pipefail

config_key="omnideck.containerEngine"

fail() {
    echo "container engine: $*" >&2
    exit 2
}

is_podman_shim() {
    local version
    version=$(docker --version 2>&1 || true)
    case "$version" in
        *[Pp][Oo][Dd][Mm][Aa][Nn]*) return 0 ;;
        *) return 1 ;;
    esac
}

validate_engine() {
    local engine="$1"

    case "$engine" in
        docker)
            command -v docker >/dev/null 2>&1 || fail "Docker is selected but 'docker' is not installed"
            is_podman_shim && fail "'docker' is the Podman compatibility shim; select Podman instead"
            ;;
        podman)
            command -v podman >/dev/null 2>&1 || fail "Podman is selected but 'podman' is not installed"
            ;;
        *) fail "expected 'docker' or 'podman', got '$engine'" ;;
    esac
    return 0
}

saved_engine() {
    git config --local --get "$config_key" 2>/dev/null || true
}

resolve_engine() {
    local requested saved docker_available=false podman_available=false

    requested="${CONTAINER_ENGINE:-}"
    if [[ -n "$requested" ]]; then
        validate_engine "$requested"
        echo "$requested"
        return
    fi

    saved=$(saved_engine)
    if [[ -n "$saved" ]]; then
        validate_engine "$saved"
        echo "$saved"
        return
    fi

    if command -v docker >/dev/null 2>&1 && ! is_podman_shim; then
        docker_available=true
    fi
    if command -v podman >/dev/null 2>&1; then
        podman_available=true
    fi

    if [[ "$docker_available" == true ]]; then
        # Preserve the existing Docker default when both native engines exist.
        echo docker
    elif [[ "$podman_available" == true ]]; then
        echo podman
    else
        fail "install Docker or Podman, or set CONTAINER_ENGINE to an available engine"
    fi
}

select_engine() {
    local engine="${1:-}"

    if [[ -z "$engine" ]]; then
        local resolved saved source
        resolved=$(resolve_engine)
        saved=$(saved_engine)
        source="automatic detection"
        [[ -n "${CONTAINER_ENGINE:-}" ]] && source="CONTAINER_ENGINE"
        [[ -z "${CONTAINER_ENGINE:-}" && -n "$saved" ]] && source="repository preference"
        echo "Container engine: $resolved ($source)"
        return
    fi

    if [[ "$engine" == auto ]]; then
        git config --local --unset-all "$config_key" 2>/dev/null || true
        echo "Container engine preference cleared; using $(resolve_engine)"
        return
    fi

    validate_engine "$engine"
    git rev-parse --git-dir >/dev/null 2>&1 || fail "a Git worktree is required to save the preference"
    git config --local "$config_key" "$engine"
    echo "Container engine set to $engine for this repository"
}

case "${1:-}" in
    --show)
        resolve_engine
        ;;
    --select)
        shift
        select_engine "${1:-}"
        ;;
    --help)
        echo "usage: container-engine.sh [--show | --select [docker|podman|auto] | ENGINE_ARGS...]"
        ;;
    "")
        fail "no container-engine command was provided"
        ;;
    *)
        engine=$(resolve_engine)
        exec "$engine" "$@"
        ;;
esac
