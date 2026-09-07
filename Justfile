# Justfile for omnideck
#
# Dev model:
#   - `just build` builds the container image from the current source.
#     Rebuild only when container/Dockerfile or baked-in deps change.
#   - `just dev` starts a long-running dev container, syncs and reinstalls the
#     Python source, builds the UI, and launches the app. State lives at
#     ~/.omnideck/.
#   - `just restart-app` / `just rebuild-ui` sync the latest source and
#     bounce the relevant bit. No bind mount on /opt/omnideck — the
#     container can't write into your repo.
#   - `just e2e` spawns a throwaway container on :9090 with ephemeral state,
#     syncs source, builds UI, runs playwright, tears down.

set dotenv-load

UI_DIR  := "server/ui"
_ctr    := "omnideck_virtual_computer"
_image  := "omnideck:latest"

# Default — show available commands
default:
    @just --list


# =============================================================================
# Setup & deps
# =============================================================================

# One-command setup for new developers (host-side deps only).
setup home_dir=`echo "$HOME/.omnideck"`:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "🤖 Setting up OMNIDECK..."

    command -v uv >/dev/null || { echo "❌ Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
    command -v node >/dev/null || echo "⚠️  Node.js not installed — UI work will not work locally"

    [ -d .venv ] && echo "📦 .venv exists — skipping" || uv venv .venv
    echo "📚 Installing Python deps..."
    uv sync --all-extras
    uv pip install -e .

    if command -v node >/dev/null && command -v npm >/dev/null; then
        echo "🎨 Installing UI deps..."
        (cd {{UI_DIR}} && ([ -f package-lock.json ] && npm ci || npm install))
    fi

    echo "🎭 Installing Playwright browsers..."
    uv run playwright install chromium

    mkdir -p "{{home_dir}}/home" "{{home_dir}}/state"

    uv run python -c "import agents, tools, utils; print('✅ Imports OK')"
    echo ""
    echo "🎉 Ready. Build the image:  just build"
    echo "   Then start developing:   just dev"

# Re-sync Python deps after pulling or editing pyproject.toml
sync:
    uv sync --all-extras

# Add a runtime dependency
add package:
    uv add {{package}}

# Add a dev dependency
add-dev package:
    uv add --dev {{package}}

# Remove a dependency
remove package:
    uv remove {{package}}


# =============================================================================
# Container image
# =============================================================================

# Show or save the container engine used by development recipes.
engine choice="":
    @bash scripts/container-engine.sh --select "{{choice}}"

# Build the container image. Only needed when container/Dockerfile changes.
build:
    @just _build-image {{_image}}


# =============================================================================
# Dev loop
# =============================================================================

# Start dev container, sync source, build UI, launch app on :8080 (idempotent)
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    engine=$(just _engine)
    just _require-image
    state="$HOME/.omnideck"
    mkdir -p "$state/home" "$state/state"
    if ! "$engine" ps -q -f name=^{{_ctr}}$ 2>/dev/null | grep -q .; then
        "$engine" rm -f {{_ctr}} 2>/dev/null || true
        env_args=(); [ -f .env ] && env_args=(--env-file .env)
        runtime_args=()
        if [[ "$engine" == docker ]]; then
            runtime_args+=(--log-driver=local --log-opt max-size=50m --log-opt max-file=3)
        fi
        case "${OMNIDECK_GPU:-0}" in
            0|false|none) ;;
            1|true|all)
                if [[ "$engine" == docker ]]; then
                    runtime_args+=(--gpus all)
                else
                    runtime_args+=(--device nvidia.com/gpu=all)
                fi
                ;;
            *) echo "❌ OMNIDECK_GPU must be 0, 1, none, or all" >&2; exit 2 ;;
        esac
        "$engine" run -d --restart=unless-stopped --name {{_ctr}} \
            "${runtime_args[@]}" \
            --shm-size=256m --network=host \
            -e PYTHONDONTWRITEBYTECODE=1 \
            -e DEV_MODE=true \
            "${env_args[@]}" \
            -v "$state/home:/home/omnideck:rw,z" \
            -v "$state/state:/var/lib/omnideck:rw,z" \
            {{_image}}
        echo "🚀 Container started with $engine"
    else
        echo "ℹ️  Container already running"
    fi
    just _sync-src {{_ctr}}
    just _install-python {{_ctr}}
    just _ui-build {{_ctr}}
    just _bounce-services {{_ctr}}
    just _wait-ready 8080
    echo "✅ Ready on http://localhost:8080"

# Sync latest Python source and bounce supervisor + app so they reload it.
restart-app:
    #!/usr/bin/env bash
    set -euo pipefail
    just _require-running
    just _sync-src {{_ctr}}
    just _install-python {{_ctr}}
    just _bounce-services {{_ctr}}
    just _wait-ready 8080
    echo "✅ App restarted"

# Sync latest UI source and rebuild dist/ inside the container
rebuild-ui:
    #!/usr/bin/env bash
    set -euo pipefail
    just _require-running
    just _sync-src {{_ctr}}
    just _ui-build {{_ctr}}
    echo "✅ UI rebuilt — refresh browser"

# Stop the dev container (keeps state in ~/.omnideck/)
stop:
    @bash scripts/container-engine.sh stop {{_ctr}} 2>/dev/null || echo "ℹ️  Not running"

# Open a bash shell in the running dev container
shell:
    @bash scripts/container-engine.sh exec -it {{_ctr}} bash

# Follow app + inference logs side by side
logs:
    #!/usr/bin/env bash
    set -euo pipefail
    engine=$(just _engine)
    just _require-running
    "$engine" logs -f {{_ctr}} 2>&1 | sed 's/^/[app] /' &
    "$engine" exec {{_ctr}} tail -f /tmp/inference_server.log 2>/dev/null | sed 's/^/[inference] /' &
    wait


# =============================================================================
# Testing
# =============================================================================

# Run unit tests (tests/unit/)
unit:
    PYTHONPATH=. uv run pytest tests/unit/

# Run browser-tools tests (real headed Chrome against local fixture pages)
test-browser-tools *args:
    #!/usr/bin/env bash
    set -euo pipefail
    if command -v xvfb-run >/dev/null 2>&1; then
        # Keep headed test windows isolated from the developer's desktop.
        PYTHONPATH=. xvfb-run -a uv run pytest tests/browser_tools/ -n 4 {{args}}
    elif [[ -n "${DISPLAY:-}" ]]; then
        PYTHONPATH=. uv run pytest tests/browser_tools/ -n 4 {{args}}
    else
        echo "A display or xvfb-run is required for headed browser-tool tests." >&2
        exit 1
    fi

# Run tests matching a specific file or path
test-file file:
    PYTHONPATH=. uv run pytest {{file}}

# Run local integration tests. Tests needing an external app opt in via OMNIDECK_URL.
integration:
    PYTHONPATH=. uv run pytest tests/integration/

# Coverage report
test-cov:
    PYTHONPATH=. uv run pytest tests/unit/ --cov-report=html --cov-report=term

# Watch mode (pytest-watch)
test-watch:
    PYTHONPATH=. uv run ptw tests/unit/

# Run UI tests (Vitest)
test-ui *args:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{UI_DIR}}
    [ -d node_modules ] || ([ -f package-lock.json ] && npm ci || npm install)
    if [ "$#" -eq 0 ]; then npm run test; else npm run test -- "$@"; fi

# Spin up a throwaway container with fresh state for manual testing on :9090.
# Ctrl-C tears it down. State is ephemeral — nothing persists after exit.
manual-test:
    #!/usr/bin/env bash
    set -euo pipefail
    engine=$(just _engine)
    # Per-branch image so concurrent worktrees don't clobber each other.
    # Container layer caching makes subsequent rebuilds fast (~5-15s steady state).
    branch_tag=$(git rev-parse --abbrev-ref HEAD | tr '/.' '-')
    image="omnideck:e2e-${branch_tag}"
    just _build-image "$image"
    name="omnideck_manual_test"
    port=9091
    state=$(mktemp -d)
    mkdir -p "$state/home" "$state/state"
    cleanup() {
        "$engine" exec -u 0 "$name" chown -R "$(id -u):$(id -g)" \
            /home/omnideck /var/lib/omnideck 2>/dev/null || true
        "$engine" stop "$name" 2>/dev/null || true
        rm -rf "$state" 2>/dev/null || true
    }
    trap cleanup EXIT

    "$engine" rm -f "$name" 2>/dev/null || true
    env_args=(); [ -f .env ] && env_args=(--env-file .env)
    gpu_args=()
    case "${OMNIDECK_GPU:-0}" in
        0|false|none) ;;
        1|true|all)
            if [[ "$engine" == docker ]]; then
                gpu_args=(--gpus all)
            else
                gpu_args=(--device nvidia.com/gpu=all)
            fi
            ;;
        *) echo "❌ OMNIDECK_GPU must be 0, 1, none, or all" >&2; exit 2 ;;
    esac

    "$engine" run -d --rm --name "$name" \
        "${gpu_args[@]}" \
        --shm-size=256m --network=host \
        -e PORT=$port \
        -e DISPLAY=:$port \
        -e ENABLE_DESKTOP=false \
        "${env_args[@]}" \
        -v "$state/home:/home/omnideck:rw,z" \
        -v "$state/state:/var/lib/omnideck:rw,z" \
        "$image"

    just _sync-src "$name"
    just _ui-build "$name"
    "$engine" restart "$name" >/dev/null

    ready=false
    for i in $(seq 1 30); do
        if curl -s "http://localhost:$port/api/settings" >/dev/null 2>&1; then
            ready=true; break
        fi
        sleep 2
    done
    if [ "$ready" = false ]; then
        echo "❌ App didn't start on :$port"
        "$engine" logs "$name" 2>&1 | tail -30
        exit 1
    fi

    echo "✅ Ready on http://localhost:$port  (Ctrl-C to tear down)"
    "$engine" logs -f "$name"


# Run Playwright e2e in a throwaway container with fresh state + latest source
e2e *args:
    #!/usr/bin/env bash
    set -euo pipefail
    engine=$(just _engine)
    # Per-branch image so concurrent worktrees don't clobber each other.
    # Container layer caching makes subsequent rebuilds fast (~5-15s steady state).
    branch_tag=$(git rev-parse --abbrev-ref HEAD | tr '/.' '-')
    # The build context is the working tree (uncommitted edits included), so the
    # built image already carries the code under test — we run it as-is, no
    # source overlay. E2E_IMAGE + E2E_SKIP_BUILD let CI skip the build and run a
    # prebuilt image (e.g. the published main image) directly instead.
    image="${E2E_IMAGE:-omnideck:e2e-${branch_tag}}"
    if [ "${E2E_SKIP_BUILD:-0}" = "1" ]; then
        echo "⏭️  Reusing image ${image} (E2E_SKIP_BUILD=1)"
    else
        just _build-image "$image"
    fi
    name="${E2E_CONTAINER:-omnideck_e2e}"
    port="${E2E_PORT:-9090}"
    state=$(mktemp -d)
    mkdir -p "$state/home" "$state/state"
    cleanup() {
        # Chown state files to host uid so we can rm -rf them.
        # Container writes them as omnideck (uid 1000) or root.
        "$engine" exec -u 0 "$name" chown -R "$(id -u):$(id -g)" \
            /home/omnideck /var/lib/omnideck 2>/dev/null || true
        "$engine" stop "$name" 2>/dev/null || true
        rm -rf "$state" 2>/dev/null || true
    }
    trap cleanup EXIT

    "$engine" rm -f "$name" 2>/dev/null || true
    env_args=(); [ -f .env ] && env_args=(--env-file .env)

    # DISPLAY=:$port — derive from port so multiple containers (dev, manual-test,
    # e2e) sharing the host network namespace can't collide on X abstract sockets.
    # ENABLE_DESKTOP=false (explicit) skips xfce + VNC + noVNC so ports 5900/6080
    # stay free for a concurrently-running dev container.
    # PORT=$port picks a non-8080 app port so the two aiohttp servers coexist.
    # MOCK_LLM=1 swaps in the in-process FakeProvider so the suite runs
    # without a real LLM backend (no Ollama, no GPU). Tests drive agent behaviour
    # via the directive protocol the fake understands.
    # --network=host is kept for the browser-tool test (Chrome under the container).
    "$engine" run -d --rm --name "$name" \
        --shm-size=256m --network=host \
        -e PORT=$port \
        -e DISPLAY=:$port \
        -e ENABLE_DESKTOP=false \
        -e MOCK_LLM=1 \
        "${env_args[@]}" \
        -v "$state/home:/home/omnideck:rw,z" \
        -v "$state/state:/var/lib/omnideck:rw,z" \
        "$image"

    # Wait for the app to come up on the e2e port
    ready=false
    for i in $(seq 1 30); do
        if curl -s "http://localhost:$port/api/settings" >/dev/null 2>&1; then
            ready=true; break
        fi
        sleep 2
    done
    if [ "$ready" = false ]; then
        echo "❌ App didn't start on :$port"
        "$engine" logs "$name" 2>&1 | tail -30
        exit 1
    fi
    curl -fsS -X PUT "http://localhost:$port/api/settings" \
        -H "Content-Type: application/json" \
        -H "X-Requested-With: XMLHttpRequest" \
        -d '{"custom_tools_enabled":true}' >/dev/null

    targets="{{args}}"
    OMNIDECK_URL="http://localhost:$port" OMNIDECK_CONTAINER="$name" PYTHONPATH=. uv run pytest ${targets:-tests/e2e/}


# =============================================================================
# Quality (run on demand)
# =============================================================================

# Lint Python and React for high-confidence correctness defects
lint:
    uv run --extra dev ruff check .
    npm --prefix {{UI_DIR}} run lint

# Type check Python and the typed React event boundary
typecheck:
    uv run --extra dev mypy .
    npm --prefix {{UI_DIR}} run typecheck

# Verify every registered agent tool has schema-ready Google documentation
tool-docs:
    uv run --extra test pytest -p no:warnings tests/unit/agent_core/skills/test_tool_categories.py::test_agent_tools_have_schema_ready_google_docstrings

# Verify the shared release-note contract and any outstanding fragments
release-note-policy:
    node --test tests/release-notes.test.mjs
    node scripts/release-notes.mjs validate-fragments

# Verify CI event routing, bounded package setup, and hosted browser reuse
workflow-policy:
    node --test tests/workflow-contracts.test.mjs tests/container-engine.test.mjs

# Format (fix imports + format)
format:
    uv run --extra dev ruff check --fix .
    uv run --extra dev ruff format .

# Verify formatting without changing files
format-check:
    uv run --extra dev ruff format --check .

# Fast, non-mutating agent quality gate
check: lint typecheck tool-docs release-note-policy workflow-policy

# CI-style: check + unit tests
ci: check unit


# =============================================================================
# Evaluation tools
# =============================================================================

# Start the compaction evaluation web app
eval port='8081':
    PYTHONPATH=. PORT={{port}} uv run python -m tools.compaction_eval.app


# =============================================================================
# Cleanup
# =============================================================================

# Clean Python caches, .venv, and UI dist (leaves node_modules + state alone)
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true
    rm -rf .venv {{UI_DIR}}/dist
    @echo "✅ Cleaned Python caches, .venv, UI dist"


# =============================================================================
# Internal helpers (hidden from --list)
# =============================================================================

# Resolve the native container engine selected for this repository.
_engine:
    @bash scripts/container-engine.sh --show

# Build into the selected engine's local image store. Docker's Buildx selection
# is intentionally ignored: local development recipes need a locally loadable image.
_build-image image:
    #!/usr/bin/env bash
    set -euo pipefail
    engine=$(just _engine)
    echo "🏗️  Building {{image}} with $engine..."
    if [[ "$engine" == docker ]]; then
        env -u BUILDX_BUILDER docker build -f container/Dockerfile -t "{{image}}" .
    else
        podman build -f container/Dockerfile -t "{{image}}" .
    fi

# Fail if the image isn't built
_require-image:
    @bash scripts/container-engine.sh image inspect {{_image}} >/dev/null 2>&1 || { echo "❌ {{_image}} not found. Run: just build"; exit 1; }

# Fail if the dev container isn't running
_require-running:
    @bash scripts/container-engine.sh ps -q -f name=^{{_ctr}}$ 2>/dev/null | grep -q . || { echo "❌ Container not running. Run: just dev"; exit 1; }

# Tar-pipe working tree into container at /opt/omnideck.
# Excludes heavy/generated dirs so the stream stays small. Normalize archived
# source permissions so a restrictive host umask cannot prevent the separate
# `broker` user from importing the integrations package. Capital X preserves
# executable scripts without making ordinary source files executable.
_sync-src ctr:
    #!/usr/bin/env bash
    set -euo pipefail
    engine=$(just _engine)
    tar \
        --mode='u+rwX,go+rX' \
        --exclude='.git' \
        --exclude='.venv' \
        --exclude='.pytest_cache' \
        --exclude='.ruff_cache' \
        --exclude='.mypy_cache' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='*.pyo' \
        --exclude='{{UI_DIR}}/node_modules' \
        --exclude='{{UI_DIR}}/dist' \
        --exclude='htmlcov' \
        --exclude='.coverage*' \
        --exclude='playwright-report' \
        --exclude='test-results' \
        -cf - . | "$engine" exec -i {{ctr}} tar -xf - -C /opt/omnideck
    echo "📦 Source synced into {{ctr}}"

# Refresh the editable install after source sync so newly added top-level
# packages and pyproject changes are immediately importable in isolated Python.
_install-python ctr:
    @bash scripts/container-engine.sh exec {{ctr}} uv pip install --system --no-cache -e /opt/omnideck
    @echo "🐍 Python package refreshed in {{ctr}}"

# Build the UI on the host, then copy dist/ into the container. The container
# image ships no Node, so the build happens here and only the static assets are
# pushed in. Reinstalls host deps only when the lockfile drifts from the stamp.
_ui-build ctr:
    #!/usr/bin/env bash
    set -euo pipefail
    engine=$(just _engine)
    command -v npm >/dev/null || { echo "❌ Node.js/npm required on host to build the UI"; exit 1; }
    cd {{UI_DIR}}
    lock_hash=$(sha256sum package-lock.json 2>/dev/null | cut -d" " -f1 || echo none)
    stamp=node_modules/.deps-hash
    if [ ! -f "$stamp" ] || [ "$(cat "$stamp" 2>/dev/null)" != "$lock_hash" ]; then
        echo "📦 Installing UI deps (lockfile changed)..."
        if [ -f package-lock.json ]; then npm ci; else npm install; fi
        echo "$lock_hash" > "$stamp"
    fi
    npm run build
    echo "📦 Copying dist/ into {{ctr}}..."
    tar -cf - dist | "$engine" exec -i {{ctr}} tar -xf - -C /opt/omnideck/{{UI_DIR}}

# Bounce supervisor + app inside the dev container. The DEV_MODE entrypoint
# runs each in a respawn loop, so killing the inner Python lets the loop
# pick it back up with the freshly synced source.
_bounce-services ctr:
    @bash scripts/container-engine.sh exec {{ctr}} pkill -f "python3.12 -m integrations.supervisor" 2>/dev/null || true
    @bash scripts/container-engine.sh exec {{ctr}} pkill -f "python3.12 main.py" 2>/dev/null || true

# Poll until the app responds on the given port (up to ~60s)
_wait-ready port:
    #!/usr/bin/env bash
    for i in $(seq 1 30); do
        if curl -s "http://localhost:{{port}}/api/settings" >/dev/null 2>&1; then
            exit 0
        fi
        sleep 2
    done
    echo "⚠️  App didn't respond on :{{port}} within 60s (check 'just logs')"
    exit 1
