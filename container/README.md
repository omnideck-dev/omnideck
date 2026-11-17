# Container Scripts

Scripts in this directory run **inside** the dev container (`omnideck_virtual_computer`), not on the host.

## Files

| File | Description |
|------|-------------|
| `Dockerfile` | Container image definition |

## How they get into the container

These scripts are baked into the image — the Dockerfile copies the whole repo to `/opt/omnideck/`, so they live at `/opt/omnideck/container/`. That's app source (root-owned), outside the agent's sandboxed home at `/home/omnideck/`, so agents can't read or modify them.

`just dev` (and `just restart-app`/`just rebuild-ui`) sync the latest host source into `/opt/omnideck/` via tar-pipe, so edits here take effect on the next sync without an image rebuild.

## Rebuilding

```bash
just build   # rebuild the image from container/Dockerfile (only when the Dockerfile changes)
just dev     # start the dev container + sync source
```
