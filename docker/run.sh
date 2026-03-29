#!/usr/bin/env bash
set -euo pipefail

# Cortex Docker one-liner — handles credential extraction automatically.
#
# Usage:
#   ./docker/run.sh /path/to/project
#   ./docker/run.sh .                    # current directory
#   ./docker/run.sh /path/to/project -p "recall what we decided"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# ── Parse args ────────────────────────────────────────────────────────────

WORKSPACE="${1:-.}"
shift || true

# Resolve to absolute path
WORKSPACE="$(cd "$WORKSPACE" && pwd)"

# ── Build image if needed ─────────────────────────────────────────────────

if ! docker image inspect cortex-runtime >/dev/null 2>&1; then
    echo "[cortex] Building Docker image (first time only, ~5 min)..."
    docker build -t cortex-runtime -f "$REPO_DIR/docker/Dockerfile" "$REPO_DIR"
fi

# ── Refresh credentials from macOS keychain ───────────────────────────────

CREDS_FILE="$HOME/.claude/.credentials.json"
if command -v security >/dev/null 2>&1; then
    KEYCHAIN_TOKEN=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null || true)
    if [ -n "$KEYCHAIN_TOKEN" ]; then
        echo "$KEYCHAIN_TOKEN" > "$CREDS_FILE"
        chmod 600 "$CREDS_FILE"
    fi
fi

# ── Run ───────────────────────────────────────────────────────────────────

exec docker run --rm -it \
    -v "$WORKSPACE":/workspace \
    -v cortex-pgdata:/var/lib/postgresql/17/data \
    -v "$HOME/.claude":/home/cortex/.claude-host:ro \
    -v "$HOME/.claude.json":/home/cortex/.claude-host-json/.claude.json:ro \
    cortex-runtime "$@"
