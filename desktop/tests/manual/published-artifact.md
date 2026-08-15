# Published artifact and trust experience

## Purpose

Verify the package users actually download, including browser reputation and
the operating system's unsigned-preview warning.

## Procedure

1. Record the target release, source commit, OS, architecture, and package
   format.
2. Download the package and its `.sha256` through a normal browser from the
   GitHub prerelease. Do not substitute a local build or Actions artifact.
3. Verify the SHA-256 independently and run `gh attestation verify` against the
   package. Record both results.
4. Record browser download warnings. Confirm the filename, version, format,
   architecture, and icon are correct.
5. Open the package through the normal user path. Record Gatekeeper on native
   macOS and any Linux desktop/package-manager warning. Windows SmartScreen is
   driven and captured by the clean Windows E2E lane; review it manually only
   when diagnosing a failure or qualifying a target without that lane.
6. Confirm any warning is attributable to the documented unsigned alpha status,
   not corruption, a wrong architecture, or malformed packaging.
7. Complete installation or copy the `.app` to `/Applications` as the platform
   expects. For AppImage, set only its executable bit.

## Pass criteria

Checksum and provenance pass, the OS recognizes the intended package, the
documented unsigned-build bypass reaches installation, and no unexpected
publisher, architecture, corruption, or duplicate-launch warning appears.
