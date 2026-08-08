# Desktop release contract

The release contract treats the published desktop packages as artifacts, not
as source-build output. It verifies the exact ten-package matrix, one matching
sha256sum-compatible checksum per package, nonempty package files, container
format signatures, and AppImage executable architectures.

Run it against a directory containing the release assets:

```sh
node desktop/tests/releasecontract/verify-release.mjs \
  --directory download \
  --version v0.1.0-alpha.8 \
  --report artifacts/desktop-release-contract/report.json
```

This is a static, non-installing contract. It does not prove that an installer
can be installed, that a GUI can reach a display server, or that the bundled
sidecar can execute. Those requirements belong to
[`../hardware`](../hardware/README.md) and
[`../manual`](../manual/README.md).

The tag workflow runs this contract before publication. The manually
dispatched `Test a published desktop release` workflow downloads the public
assets, verifies GitHub attestations, and runs it again after publication.
