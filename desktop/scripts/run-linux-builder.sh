#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
desktop_root="$(cd "${script_dir}/.." && pwd)"
repo_root="$(cd "${desktop_root}/.." && pwd)"
image="${OMNIDECK_DESKTOP_BUILDER_IMAGE:-omnideck-desktop-linux-builder:local}"

command -v docker >/dev/null 2>&1 || {
  printf 'Docker is required for the containerized Linux desktop builder.\n' >&2
  exit 2
}

if [[ "${OMNIDECK_DESKTOP_BUILDER_SKIP_BUILD:-0}" != "1" ]]; then
  docker build --tag "${image}" \
    --file "${desktop_root}/containers/linux-builder/Dockerfile" \
    "${repo_root}"
fi

docker image inspect "${image}" >/dev/null 2>&1 || {
  printf 'Builder image %q is not available.\n' "${image}" >&2
  exit 2
}

command_string="${*:-pnpm run verify}"
uid="$(id -u)"
gid="$(id -g)"
docker_args=(
  run --rm
  --user "${uid}:${gid}"
  --env HOME=/tmp/omnideck-desktop-home
  --env CARGO_HOME=/tmp/omnideck-cargo
  --env RUSTUP_HOME=/usr/local/rustup
  --env XDG_CACHE_HOME=/tmp/omnideck-cache
)
container_workdir=/workspace/desktop
stage_source=''
if [[ -n "${OMNIDECK_DESKTOP_BUILD_OUTPUT_DIR:-}" ]]; then
  mkdir -p "${OMNIDECK_DESKTOP_BUILD_OUTPUT_DIR}"
  build_output="$(realpath -e "${OMNIDECK_DESKTOP_BUILD_OUTPUT_DIR}")"
  container_workdir=/tmp
  stage_source='mkdir -p /tmp/workspace && tar -C /source --exclude=.git --exclude=.pnpm-store --exclude="*/node_modules" --exclude="*/target" -cf - . | tar -C /tmp/workspace -xf - && cd /tmp/workspace/desktop && '
  docker_args+=(--env CARGO_TARGET_DIR=/out --volume "${repo_root}:/source:ro" --volume "${build_output}:/out")
else
  docker_args+=(--volume "${repo_root}:/workspace")
fi
docker_args+=(--workdir "${container_workdir}" "${image}")

docker "${docker_args[@]}" \
  bash -c "${stage_source}mkdir -p \"\${HOME}\" \"\${CARGO_HOME}\" \"\${XDG_CACHE_HOME}\" && pnpm install --frozen-lockfile && ${command_string}"
