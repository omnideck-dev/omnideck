#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
desktop_dir=$(cd -- "${script_dir}/.." && pwd)
repository_dir=$(cd -- "${desktop_dir}/.." && pwd)

docker run --rm \
  --platform linux/amd64 \
  --env "HOST_USER_ID=$(id -u)" \
  --env "HOST_GROUP_ID=$(id -g)" \
  --mount "type=bind,src=${repository_dir},dst=/workspace" \
  --mount "type=volume,src=omnideck-linux-node-modules,dst=/workspace/desktop/node_modules" \
  --mount "type=volume,src=omnideck-linux-npm-cache,dst=/root/.npm" \
  --workdir /workspace/desktop \
  node:22-bookworm \
  bash -euo pipefail -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends binutils fakeroot rpm
    npm ci
    rm -rf /workspace/desktop/dist
    set +e
    npm run dist:linux -- --x64
    build_status=$?
    set -e
    if [ "${build_status}" -eq 0 ]; then
      shopt -s nullglob
      debs=(dist/*.deb)
      rpms=(dist/*.rpm)
      [ "${#debs[@]}" -eq 1 ]
      [ "${#rpms[@]}" -eq 1 ]
      dpkg-deb --info "${debs[0]}" >/dev/null
      rpm --query --package "${rpms[0]}" --info >/dev/null
      node scripts/checksums.cjs dist
    fi
    if [ -d /workspace/desktop/dist ]; then
      chown -R "${HOST_USER_ID}:${HOST_GROUP_ID}" /workspace/desktop/dist
    fi
    exit "${build_status}"
  '
