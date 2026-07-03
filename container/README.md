# Container Scripts

Scripts in this directory run **inside** the dev container (`omnideck_virtual_computer`), not on the host.

## Files

| File | Description |
|------|-------------|
| `Dockerfile` | Container image definition (CUDA, Python, Node, ML stack) |
| `inference_server.py` | Persistent HTTP server that keeps ML models loaded in VRAM between requests. Supports both blocking (`/generate`) and streaming (`/generate-stream`) endpoints with TAESD preview decoding. Auto-shuts down after 10 minutes idle. |
| `inference_client.py` | Thin client that auto-starts the server and provides `generate()` and `generate_stream()` functions for use by custom tools and the `generate_image` host tool. |

## How they get into the container

These scripts are baked into the image — the Dockerfile copies the whole repo to `/opt/omnideck/`, so they live at `/opt/omnideck/container/`. That's app source (root-owned), outside the agent's sandboxed home at `/home/omnideck/`, so agents can't read or modify them.

`just dev` (and `just restart-app`/`just rebuild-ui`) sync the latest host source into `/opt/omnideck/` via tar-pipe, so edits here take effect on the next sync without an image rebuild.

## Rebuilding

```bash
just build   # rebuild the image from container/Dockerfile (only when the Dockerfile changes)
just dev     # start the dev container + sync source
```
