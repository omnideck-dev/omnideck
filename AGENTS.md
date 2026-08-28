# Repository guide

- Run `just check` and focused tests for the behavior you changed before handoff.
- Model-exposed Python tools need a useful summary and Google-style `Args:` entries for every parameter; verify them with `just tool-docs`.
- Desktop package and OS testing uses the disposable VM lab. Set `OMNIDECK_VM_LAB_DIR=/mnt/data/VMs/omnideck-release-lab` and read `desktop/TESTING.md` and `desktop/tests/e2e/README.md` for the VM entry points.
- UX mockups must depict the real product surface with realistic user-facing copy. Do not place implementation notes, proposed-behavior explanations, feature descriptions, or reviewer annotations inside the simulated product UI; keep any necessary review controls outside that surface.
