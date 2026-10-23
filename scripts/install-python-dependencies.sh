#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
requirements=$(mktemp)
trap 'rm -f "$requirements"' EXIT

# Install exactly the audited runtime graph, retaining unrelated system tools.
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file "$requirements" >/dev/null
uv pip install --system --no-cache --require-hashes --requirements "$requirements"
