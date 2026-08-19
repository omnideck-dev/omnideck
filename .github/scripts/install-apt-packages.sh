#!/usr/bin/env bash
set -Eeuo pipefail

if (( $# == 0 )); then
    echo "Usage: install-apt-packages.sh PACKAGE..." >&2
    exit 2
fi

readonly max_attempts=3
readonly command_timeout=300

run_apt() {
    local attempt
    for ((attempt = 1; attempt <= max_attempts; attempt++)); do
        echo "apt-get $* (attempt ${attempt}/${max_attempts})"
        if sudo timeout --signal=TERM --kill-after=30s "${command_timeout}s" \
            apt-get \
            -o Acquire::Retries=3 \
            -o DPkg::Lock::Timeout=120 \
            "$@"; then
            return 0
        fi

        if (( attempt == max_attempts )); then
            echo "apt-get $* failed after ${max_attempts} attempts" >&2
            return 1
        fi

        sleep $((attempt * 10))
    done
}

export DEBIAN_FRONTEND=noninteractive
run_apt update
run_apt install -y "$@"
