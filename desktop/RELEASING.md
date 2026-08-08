# Releasing OmniDeck desktop

This file is the authoritative procedure for tagging, approving, publishing,
and qualifying a desktop release. [`TESTING.md`](TESTING.md) owns test layers,
supported matrices, evidence, and promotion gates. Human/agent procedures live
under [`tests/manual`](tests/manual/README.md).

Desktop versions use Semantic Versioning. Prerelease suffixes select alpha,
beta, or release-candidate channels; stable versions contain no suffix. Tags
and published assets are immutable.

## Prepare the candidate

1. Update `package.json` and `src-tauri/tauri.conf.json` to the same version.
2. Update the pinned CLI vendor manifest deliberately; never weaken its archive,
   binary, SBOM, version, commit, or architecture checks.
3. Set `container-version.txt` to the intended container release and confirm it
   exists. The workflow resolves the mutable tag to one immutable digest for all
   package builds.
4. Add `docs/releases/v<version>.md` with user-visible changes, upgrade notes,
   known limitations, unsigned-build guidance where applicable, and explicit
   build-only or blocked platform coverage.
5. From `desktop/`, run:

   ```sh
   pnpm install --frozen-lockfile
   pnpm run verify
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
static release contract.

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

Preview packages may be unsigned. SmartScreen and Gatekeeper warnings must be
documented for testers and recorded separately from functional defects.
Signing, notarization, and publisher identity must be resolved before a stable
release can satisfy the stable gate.
