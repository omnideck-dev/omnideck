#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
desktop_dir=$(cd -- "${script_dir}/.." && pwd)
repository_dir=$(cd -- "${desktop_dir}/.." && pwd)
workspace_parent=$(cd -- "${repository_dir}/.." && pwd)
cli_source=${OMNIDECK_CLI_SOURCE:-"${workspace_parent}/cli"}
runtime_dir="${desktop_dir}/build/runtime"

if [ ! -f "${cli_source}/go.mod" ]; then
  echo "Omnideck CLI source was not found at ${cli_source}." >&2
  echo "Clone omnideck-dev/cli beside this repository or set OMNIDECK_CLI_SOURCE." >&2
  exit 1
fi

mkdir -p "${runtime_dir}"

# Build the Linux helper in a Go container first. The Electron build itself
# remains in the Node container below; passing the result as prebuilt keeps the
# npm predist hook identical to native macOS/Windows/CI builds.
docker run --rm \
  --platform linux/amd64 \
  --env "HOST_USER_ID=$(id -u)" \
  --env "HOST_GROUP_ID=$(id -g)" \
  --mount "type=bind,src=${cli_source},dst=/cli,readonly" \
  --mount "type=bind,src=${runtime_dir},dst=/out" \
  --mount "type=volume,src=omnideck-linux-go-cache,dst=/go/pkg/mod" \
  --workdir /cli \
  golang:1.25.12-bookworm \
  bash -euo pipefail -c '
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
      -buildvcs=false -trimpath -o /out/omnideck-cli .
    chown "${HOST_USER_ID}:${HOST_GROUP_ID}" /out/omnideck-cli
  '

docker run --rm \
  --platform linux/amd64 \
  --env "HOST_USER_ID=$(id -u)" \
  --env "HOST_GROUP_ID=$(id -g)" \
  --env "OMNIDECK_CLI_PREBUILT=/workspace/desktop/build/runtime/omnideck-cli" \
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
