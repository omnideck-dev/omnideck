# Manual and agent-operated desktop release tests

These procedures cover behavior that hosted CI cannot safely or reliably
prove: OS trust prompts, runtime installation and elevation, restart/resume,
real desktop integration, visual quality, and destructive recovery.

Run them with the real published packages on disposable VMs or dedicated test
machines. Never run the Windows reset on a development or personal computer.
An agent must inventory the exact host before a mutating step and stop if the
procedure could alter resources that were not created for the test.

Required procedures:

- [Setup UX principles](../setup-ux-principles.md)
- [Setup progress UX mockup](setup-progress-mockup.html)
- [Local VM lab controls](local-vm-lab.md)
- [Published artifact and trust experience](published-artifact.md)
- [Clean-machine first run](clean-first-run.md)
- [Hosted application behavior](hosted-app-behavior.md)
- [Recovery and package lifecycle](recovery-lifecycle.md)
- [Visual and platform fit](visual-platform.md)

The helpers under [`../../scripts/release-test`](../../scripts/release-test/README.md)
download a selected release, verify its checksum and GitHub provenance, prepare
the requested scenario, and launch it. They do not turn a visual/manual
procedure into an automated pass.

Every execution must record:

```text
Release/tag:
Source commit:
Artifact filename:
Artifact SHA-256:
OS and exact version:
CPU architecture:
Package format:
Display server / desktop environment:
WebView or WebKit version:
Podman/runtime baseline:
Clean machine or reused state:
Scenario:
Start/end timestamps:
Result: pass | fail | blocked
Screenshots/video/log locations:
Observed trust warnings:
Starting resource inventory:
Final resource inventory:
Residual processes/files:
Issue links:
Tester:
```

Record unavailable hardware or an unexecuted step as `blocked`; never infer a
pass from a successful cross-build. Redact tokens, registry credentials, and
sensitive home-directory details before attaching evidence.

Electron upgrade continuity is not part of this suite. Frozen Electron setup
fixtures exist only to catch setup UI drift.
