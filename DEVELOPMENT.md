# Development Guide

## Architecture

Omnideck runs as a single container. The app server (aiohttp + React), desktop environment (Xfce + VNC), browser (Chrome), and inference models all live inside one image. Ollama runs on the host and is accessed via `--network=host`.

```
Container (everything runs as omnideck)
  App server (aiohttp :8080)
    agents/ — LLM agent implementations
    tools/  — tool modules the agent invokes
    server/ — HTTP API + React UI
  Desktop (Xfce + VNC :5900 + noVNC :6080)
    Chrome, Firefox, terminal, file manager
  Inference (GPU models for image/music/video/grounding)

Host
  Ollama — LLM inference (accessed at localhost:11434 via --network=host)
  Docker or Podman — container runtime
```

### Key Paths

| Path | Owner | Purpose |
|------|-------|---------|
| `/opt/omnideck` | root | App source (baked into image; overwritten by tar-pipe on `just dev`/`restart-app`/`rebuild-ui`) |
| `/home/omnideck` | omnideck | Agent workspace, downloads, generated files |
| `/var/lib/omnideck` | omnideck | Conversations, memory, custom tools, routines |

## Dev Workflow

```sh
just build          # Build image (only when Dockerfile changes)
just dev            # Start dev container, sync source, build UI, launch on :8080
just restart-app    # Sync Python source, bounce the app
just rebuild-ui     # Sync UI source, rebuild dist/
just stop           # Stop container (state persists in ~/.omnideck/)
just shell          # Bash inside the container
just logs           # Tail app + inference logs
```

The Justfile automatically uses the available native container engine. When
both Docker and Podman are installed, Docker remains the default for backward
compatibility. Save a different repository-wide preference once with
`just engine podman` or `just engine docker`; the choice is stored in the
clone's local Git config and shared by all of its worktrees. `just engine auto`
clears it. `CONTAINER_ENGINE` is available as a temporary per-command override.

GPU access is disabled by default so the development recipes work on machines
without an NVIDIA runtime. Set `OMNIDECK_GPU=1` to enable all configured GPUs;
the Justfile supplies the native Docker or Podman argument.

`just dev` **copies** your repo into the container via a tar-pipe — no bind mount. Source changes on the host don't appear until you run `just restart-app` or `just rebuild-ui`. This keeps the container unable to write back into your repo.

**Note:** `just restart-app` only bounces the Python process. `.env` changes require `just stop && just dev`.

### Config

- `config.yaml` — all configuration. Uses `${ENV_VAR:-default}` syntax. Single source of truth for env vars.
- `.env` — local dev overrides (gitignored). Passed via `--env-file`.

### Feature Flags

| Feature | Env Var | Requires |
|---------|---------|----------|
| Image generation | `ENABLE_IMAGE_GEN=1` | GPU + HF_TOKEN |
| Music generation | `ENABLE_MUSIC_GEN=1` | GPU |
| Desktop agent | `ENABLE_DESKTOP=1` | — |
| Visual grounding | `ENABLE_GROUNDING=1` | GPU |

Custom Tools and Apps are user-controlled from **Settings → System → Experimental**.

## Testing

```
tests/
  unit/          # Host-only, no external services
  e2e/           # Playwright browser tests against a running app
  integration/   # Needs a running container with Ollama
```

```sh
just unit           # Unit tests
just e2e            # E2E in a throwaway container on :9090
just integration    # Integration tests (needs OMNIDECK_URL)
just test-file <p>  # Specific file
just test-ui        # Vitest UI tests
```

`just e2e` is self-contained: it builds a per-branch image, spawns a throwaway
container on :9090, runs Playwright, and tears down. CI sets `E2E_SKIP_BUILD=1`
to run an image it already built and pulled by digest.

## Code Quality

```sh
just lint       # Ruff + ESLint correctness checks
just typecheck  # mypy + typed React event boundary
just tool-docs  # agent tool schema/docstring contract
just format     # ruff fix + format
just check      # fast non-mutating agent gate
```

The gate is deliberately narrow: Ruff blocks syntax/name errors and high-confidence
bug patterns; ESLint blocks JavaScript runtime errors and Rules-of-Hooks violations.
Mypy covers production Python except optional hardware/runtime code, migrations, and
legacy broker internals; the JavaScript UI's strongly typed event boundary is checked
by TypeScript.

## Frontend (server/ui/)

- React 18 with JSX (not TypeScript)
- Vite for bundling, Vitest for testing
- CSS Modules (`*.module.css`)
- Function components with hooks

## Conventions

See `CLAUDE.md` for the full coding conventions. Key points:

- Python 3.12, `uv` for deps
- `logger.info("message %s", var)` — no f-strings in logging
- `__init__.py` is a facade — pure re-exports, no code
- Eager imports by default; lazy only for heavy optional deps (playwright, torch)
- Circular imports are a design bug — fix the graph, don't patch around it

## Container Build

```sh
just build     # Build omnideck:latest in the selected local engine
```

Local recipes deliberately use the selected engine's ordinary build command so
the image is immediately available to `just dev` and `just e2e`. Automated
multi-architecture image publication remains owned by GitHub Actions.

## Justfile Reference

Run `just` (no args) to see all available recipes. Key ones:

| Command | Purpose |
|---------|---------|
| `just engine [docker\|podman\|auto]` | Show or save the repository's container-engine preference |
| `just build` | Build the container image (only when container/Dockerfile changes) |
| `just dev` | Start dev container, sync source, build UI, launch app on :8080 |
| `just restart-app` | Sync latest Python source and bounce the app |
| `just rebuild-ui` | Sync latest UI source and rebuild dist/ |
| `just stop` | Stop the dev container (state at `~/.omnideck/` persists) |
| `just shell` | Bash shell inside the dev container |
| `just logs` | Tail app + inference logs |
| `just unit` | Run unit tests |
| `just integration` | Run integration tests (needs a running container) |
| `just test-file <path>` | Run tests for a specific file |
| `just e2e` | Run e2e tests in a throwaway container on :9090 |
| `just lint` | High-signal Python and React correctness lint |
| `just typecheck` | Type check production Python and the typed React event boundary |
| `just tool-docs` | Verify agent tool schema documentation |
| `just format` | Auto-format with ruff |
| `just check` | Fast non-mutating agent quality gate |
