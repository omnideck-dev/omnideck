# omnideck Tauri desktop host

This directory contains the Tauri v2 desktop host that replaces the Electron
shell while preserving the existing setup experience.

The installer UI assets and copy are checked against the Electron source by the
policy tests. The hosted application runs in a separate webview with no Tauri
capability. The local setup webview receives only four typed lifecycle commands;
Rust owns every CLI argument, validates the CLI and JSON contracts, and limits
process output and execution time.

The hosted webview enables native clipboard access, keeps copy/paste keyboard
shortcuts available, refreshes with Ctrl/Cmd+R or F5, opens external HTTP(S)
links in the system browser, and denies all other new-window requests.

## Bundled CLI

The official `omnideck-dev/cli` `v0.10.0-alpha.2` release is bundled for x64
and ARM64 on Windows, macOS, and Linux. The executables are not committed to
this repository. `src-tauri/binaries/vendor-manifest.json` pins the release URL,
archive checksums, extracted-binary checksums, version, commit, and SBOM
checksums. Neither executables nor SBOM release assets are committed. Run
`pnpm run fetch:sidecars`, then `pnpm run verify:sidecars`, to download and
validate all six targets. Each native build command downloads only its target
before Tauri packages the executable into the installer.
`OMNIDECK_CLI_ARCHIVE_DIR` may point at a directory of previously downloaded
release archives for an offline or sandboxed build; the same pinned hashes are
still enforced.

## Validation

[`TESTING.md`](TESTING.md) defines the authoritative test layers, matrices, and
promotion gates. [`RELEASING.md`](RELEASING.md) defines tagging and publication.
Run `pnpm run verify` for the canonical local source gate. Native installer
builds are:

- `pnpm run build:windows` and `pnpm run build:windows:arm64`
- `pnpm run build:macos` and `pnpm run build:macos:x64`
- `pnpm run build:linux` and `pnpm run build:linux:arm64`

Windows produces NSIS, macOS produces DMG, and Linux produces AppImage, DEB,
and RPM packages. Every platform must run its native packaged smoke test before
a release; cross-compiling an installer is not a substitute for that gate.

When the host does not have Rust, Tauri's Linux dependencies, or a suitable
Node/pnpm toolchain, use the pinned containerized Linux builder. It keeps build
outputs owned by the invoking user and mounts this checkout only:

```sh
./desktop/scripts/run-linux-builder.sh "pnpm run verify"
./desktop/scripts/run-linux-builder.sh "pnpm run build:linux"
```

The builder pins the Node and Rust base-image digests and the pnpm version in
[`containers/linux-builder/Dockerfile`](containers/linux-builder/Dockerfile).
The resulting package is still a cross-build until it passes native Linux
smoke and manual evidence.

For a local Windows x64 candidate when a Windows build runner is unavailable,
use the pinned GNU cross-builder. It builds the fixed CLI in the separate CLI
container, temporarily stages it under the Windows target triple, and restores
the release sidecar when finished:

```sh
./desktop/scripts/build-with-local-cli-windows.sh /path/to/omnideck-cli
```

This produces an unsigned NSIS candidate under
`src-tauri/target/x86_64-pc-windows-gnu/release/bundle/nsis/`. The Windows CI
build remains the release build of record (`x86_64-pc-windows-msvc`); the local
GNU package is suitable for disposable VM diagnosis and manual testing only.

Static release-asset checks live under `tests/releasecontract`, read-only native
package smoke lives under `tests/hardware`, and guided real-OS procedures live
under `tests/manual`. Existing release download/reset helpers remain under
`scripts/release-test`.
