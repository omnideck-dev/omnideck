#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
desktop_root="$(cd "${script_dir}/.." && pwd)"
cli_root="${1:-${OMNIDECK_CLI_WORKTREE:-}}"
shift || true
command_string="${*:-pnpm exec tauri build --bundles appimage --target x86_64-unknown-linux-gnu}"
builder_image="${OMNIDECK_CLI_BUILDER_IMAGE:-omnideck-cli-builder:local}"
target_triple="${OMNIDECK_DESKTOP_TARGET:-x86_64-unknown-linux-gnu}"
sidecar="${desktop_root}/src-tauri/binaries/omnideck-cli-${target_triple}"
manifest="${desktop_root}/src-tauri/binaries/vendor-manifest.json"

[[ -n "${cli_root}" ]] || {
  printf 'Pass the CLI worktree path or set OMNIDECK_CLI_WORKTREE.\n' >&2
  exit 2
}
[[ -d "${cli_root}" ]] || { printf 'CLI worktree does not exist: %s\n' "${cli_root}" >&2; exit 2; }
[[ "${target_triple}" == "x86_64-unknown-linux-gnu" ]] || {
  printf 'This local Linux helper currently supports x86_64-unknown-linux-gnu only.\n' >&2
  exit 2
}
[[ -f "${sidecar}" ]] || { printf 'Release sidecar is missing: %s\n' "${sidecar}" >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { printf 'Docker is required.\n' >&2; exit 2; }
docker image inspect "${builder_image}" >/dev/null 2>&1 || {
  printf 'Build %q from .devcontainer/Dockerfile first.\n' "${builder_image}" >&2
  exit 2
}
command -v node >/dev/null 2>&1 || { printf 'Node.js is required to read the vendor identity.\n' >&2; exit 2; }

vendor_version="$(node -e "const m=require(process.argv[1]); process.stdout.write(m.version)" "${manifest}")"
vendor_commit="$(node -e "const m=require(process.argv[1]); process.stdout.write(m.commit)" "${manifest}")"
source_commit="$(git -C "${cli_root}" rev-parse --short HEAD)"
candidate_dir="$(mktemp -d /tmp/omnideck-desktop-local-cli.XXXXXX)"
cp -- "${sidecar}" "${candidate_dir}/release-sidecar"

restore_sidecar() {
  cp -- "${candidate_dir}/release-sidecar" "${sidecar}"
  chmod 755 "${sidecar}"
}

cleanup() {
  local status=$?
  if restore_sidecar; then
    :
  else
    status=$?
  fi
  case "${candidate_dir}" in
    /tmp/omnideck-desktop-local-cli.??????)
      if ! rm -rf -- "${candidate_dir}"; then
        status=1
      fi
      ;;
    *)
      printf 'Refusing to remove unexpected temporary path: %s\n' "${candidate_dir}" >&2
      status=1
      ;;
  esac
  exit "${status}"
}
trap cleanup EXIT

printf 'Building local CLI source %s in %s.\n' "${source_commit}" "${builder_image}"
docker run --rm --entrypoint /bin/zsh \
  --user "$(id -u):$(id -g)" \
  --env GOCACHE=/tmp/omnideck-go-build \
  --env GOPATH=/tmp/omnideck-go \
  --volume "${cli_root}:/workspace" \
  --volume "${candidate_dir}:/out" \
  --workdir /workspace "${builder_image}" \
  -c "go build -trimpath -buildvcs=false -ldflags '-X main.version=${vendor_version} -X main.commit=${vendor_commit} -X main.date=local-fixed-cli-${source_commit}' -o /out/omnideck ."

cp -- "${candidate_dir}/omnideck" "${sidecar}"
chmod 755 "${sidecar}"
sha256sum "${sidecar}"
"${sidecar}" --version

cd "${desktop_root}/.."
OMNIDECK_DESKTOP_BUILDER_SKIP_BUILD=1 \
  "${desktop_root}/scripts/run-linux-builder.sh" "${command_string}"
