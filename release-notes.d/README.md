# Release-note fragments

Every pull request must add a fragment here or explicitly use the
`release-note:none` label with a reason. See
[the release-note policy](../docs/release-notes.md) for the complete contract.

Use a unique lowercase kebab-case filename and this format:

```markdown
---
target: app
type: changed
area: setup
---

Setup now selects another available local port automatically when the saved
port is already in use.
```

`target` is `app` for the container-served omnideck product or `desktop` for
the native host, setup, and installers. Choose the artifact whose release
delivers the change.

Valid types are `added`, `changed`, `deprecated`, `removed`, `fixed`,
and `security`. Do not edit this README as a substitute for a fragment.

App fragments stay here after release. The Monday workflow combines only new
app fragments since the previous release tag. Once an app fragment has shipped,
add a new fragment for a correction; do not edit, rename, or delete it.
Desktop fragments are still consumed by desktop release preparation.
