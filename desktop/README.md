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

Static release-asset checks live under `tests/releasecontract`, read-only native
package smoke lives under `tests/hardware`, and guided real-OS procedures live
under `tests/manual`. Existing release download/reset helpers remain under
`scripts/release-test`.
