#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
desktop_root="$(cd "${script_dir}/.." && pwd)"
repo_root="$(cd "${desktop_root}/.." && pwd)"
image="${OMNIDECK_DESKTOP_WINDOWS_BUILDER_IMAGE:-omnideck-desktop-windows-builder:local}"

command -v docker >/dev/null 2>&1 || {
  printf 'Docker is required for the containerized Windows desktop builder.\n' >&2
  exit 2
}

if [[ "${OMNIDECK_DESKTOP_WINDOWS_BUILDER_SKIP_BUILD:-0}" != "1" ]]; then
  docker build --tag "${image}" \
    --file "${desktop_root}/containers/windows-builder/Dockerfile" \
    "${repo_root}"
fi

docker image inspect "${image}" >/dev/null 2>&1 || {
  printf 'Builder image %q is not available.\n' "${image}" >&2
  exit 2
}

command_string="${*:-pnpm exec tauri build --bundles nsis --target x86_64-pc-windows-gnu}"
uid="$(id -u)"
gid="$(id -g)"

docker run --rm \
  --user "${uid}:${gid}" \
  --env HOME=/tmp/omnideck-desktop-home \
  --env CARGO_HOME=/tmp/omnideck-cargo \
  --env RUSTUP_HOME=/usr/local/rustup \
  --env XDG_CACHE_HOME=/tmp/omnideck-cache \
  --volume "${repo_root}:/workspace" \
  --workdir /workspace/desktop \
  "${image}" \
  bash -c "mkdir -p \"\${HOME}\" \"\${CARGO_HOME}\" \"\${XDG_CACHE_HOME}\" && pnpm install --frozen-lockfile && ${command_string}"
