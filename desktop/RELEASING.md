# Releasing OmniDeck desktop

This file is the authoritative procedure for tagging, approving, publishing,
and qualifying a desktop release. [`TESTING.md`](TESTING.md) owns test layers,
supported matrices, evidence, and promotion gates. Human/agent procedures live
under [`tests/manual`](tests/manual/README.md).

Desktop versions use Semantic Versioning. Prerelease suffixes select alpha,
beta, or release-candidate channels; stable versions contain no suffix. Tags
and published assets are immutable.

## Prepare the candidate

1. Update `package.json`, `src-tauri/tauri.conf.json`, the Rust package/lock,
   `src-tauri/src/state.rs`, and the checked-in runtime image manifest to the
   same version. Source policy tests lock these mirrors together.
2. Update the pinned CLI vendor manifest deliberately; never weaken its archive,
   binary, SBOM, version, commit, or architecture checks.
3. Set `container-version.txt` to the intended container release and confirm it
   exists. The workflow resolves the mutable tag to one immutable digest for all
   package builds. If a new app version must be published first, follow the
   [app release runbook](../docs/APP_RELEASING.md).
4. Generate `docs/releases/v<version>.md` from the outstanding release-note
   fragments, then curate it before review:

   ```sh
   VERSION=v0.1.0-beta.11
   node scripts/release-notes.mjs generate \
     --target desktop \
     --version "${VERSION}" \
     --output "docs/releases/${VERSION}.md"
   ```

   Keep the final copy focused on user-visible product and desktop changes,
   upgrade guidance, known limitations, and preview trust warnings. Link to the
   separately published app release when this desktop version changes its
   pinned app version; do not duplicate the app release body. Build,
   qualification, and VM-lab detail belongs in workflow evidence and testing
   documentation, not in the user-facing release body. Remove the fragments
   incorporated into the reviewed file. The release pull request uses
   `release-note:none` with a reason explaining that it only aggregates
   previously reviewed fragments.
5. From the repository root, run the pinned Docker-backed verifier. This is the
   canonical local gate and does not require Node, pnpm, Rust, or Cargo on the
   host:

   ```sh
   ./desktop/scripts/run-linux-builder.sh
   ```

   For a disconnected build, use the exact offline archive procedure in
   [`TESTING.md`](TESTING.md#canonical-source-verification).
6. Merge the intended source to `main` and confirm the required desktop CI and
   repository security checks are green on that commit.
7. Review the pre-publication evidence required by the intended channel and
   identify the machines/owners for public-artifact checks. Do not create a
   promotion tag based on a successful build alone.

## Tag and publish

Create a new annotated tag on the exact `main` commit. Never reuse, move, or
replace an existing tag:

```sh
git switch main
git pull --ff-only
git tag -a v0.1.0-alpha.9 -m "OmniDeck desktop v0.1.0-alpha.9"
git push origin v0.1.0-alpha.9
```

The `omnideck application` workflow rejects malformed tags, version mismatches,
missing release notes, and tags not contained in `main`. It repeats source
verification, pins the runtime image digest, builds all six target
architectures and ten package formats, creates package checksums, and runs the
static release contract. macOS tag jobs must first pass the protected
`desktop-signing` environment. They import the release-only Developer ID
identity into an ephemeral keychain, sign both DMGs, submit them to Apple's
notary service, staple the tickets, and reject any package that does not pass
Developer ID, hardened-runtime, timestamp, ticket, and Gatekeeper checks.

Publication pauses at the protected `release` environment. Before approval,
review the source, sidecar, runtime-image, build, release-contract, checksum,
and provenance results for the exact tag. Approving the environment authorizes
publication of those already-built assets; it is not a substitute for required
native or manual evidence.

Suffix tags publish as GitHub prereleases and never become `latest`. A stable
tag publishes only after its stable promotion gate is satisfied.

## Qualify the public assets

After publication, redownload and validate the public release rather than
reusing build-workspace files:

```sh
gh workflow run desktop-release-contract.yml \
  --ref main \
  -f version=v0.1.0-alpha.9
```

Then run the native packaged smoke workflow on available dedicated machines:

```sh
gh workflow run desktop-hardware.yml \
  --ref main \
  -f version=v0.1.0-alpha.9 \
  -f target=primary \
  -f confirm=true
```

Complete the channel's procedures under `tests/manual` using browser-downloaded
packages. Record unavailable hardware as blocked coverage and keep cross-build
confidence distinct from native execution.

If any required post-publication check fails, fix forward on `main` and publish
the next version. Do not replace assets or retag the failed release.

## Promotion

Promotion creates a new immutable tag and rebuild, even when the source commit
is unchanged:

```text
v0.1.0-alpha.9 -> v0.1.0-beta.1 -> v0.1.0-rc.1 -> v0.1.0
```

Apply the corresponding gate from [`TESTING.md`](TESTING.md#promotion-gates)
before tagging. Evidence belongs to the exact candidate commit and assets, not
merely to a version family or time spent in a channel.

## Signing status

Pull-request, `main`, and ordinary manual macOS packages use Tauri's complete
bundle-level ad-hoc signature. They are internal evidence only and cannot be
published. The macOS build mounts each generated DMG and requires its contained
application to pass strict recursive `codesign` verification; an
executable-only linker signature is a release failure.

Tag builds and manual runs with `signed_macos=true` use the protected
`desktop-signing` environment. The workflow derives the signing identity from
the imported certificate, requires Apple team `2FL6BUG8Q4`, and has Tauri
notarize and staple the package. The verifier then requires a Developer ID
Application authority, hardened runtime, secure timestamp, valid stapled
ticket, and successful Gatekeeper assessments for both the application and
DMG. The same Developer ID Application certificate signs the Intel and Apple
Silicon packages. A Developer ID Installer certificate is not used because the
release format is DMG rather than PKG.

### One-time GitHub environment setup

Create a Developer ID Application certificate for Apple team `2FL6BUG8Q4` on a
trusted Mac. Export the certificate and its private key from Keychain Access as
a password-protected PKCS#12 (`.p12`) file. Create a team App Store Connect API
key with permission to submit notarization requests and retain its issuer ID,
key ID, and one-time-download `.p8` private key.

Configure the `desktop-signing` GitHub environment so only `main` and `v*` tags
may deploy, and require a reviewer before its secrets are released. Store these
environment secrets:

| Secret | Value |
| --- | --- |
| `DESKTOP_MAC_CERTIFICATE_P12_BASE64` | One-line base64 of the `.p12` archive |
| `DESKTOP_MAC_CERTIFICATE_PASSWORD` | Password assigned when exporting the `.p12` |
| `DESKTOP_APPLE_API_KEY_ID` | App Store Connect API key ID |
| `DESKTOP_APPLE_API_ISSUER_ID` | App Store Connect API issuer UUID |
| `DESKTOP_APPLE_API_PRIVATE_KEY_BASE64` | One-line base64 of the `.p8` private key |

Generate the base64 values without writing them into the repository:

```sh
openssl base64 -A -in DeveloperIDApplication.p12
openssl base64 -A -in AuthKey_KEYID.p8
```

Do not store the unencoded files, their base64 representations, or the
certificate password in source control, release artifacts, workflow variables,
or pull-request text. The workflow decodes them only beneath `RUNNER_TEMP`,
uses an ephemeral keychain, and deletes the material before artifact upload.

Before creating a release tag, run a non-publishing proof from `main`:

```sh
gh workflow run desktop.yml --ref main -f signed_macos=true
```

Approve both macOS jobs in `desktop-signing`, then require the workflow and
artifact contract to pass. This proof exercises the same signing,
notarization, stapling, and trust checks as a tag without publishing a GitHub
Release.
