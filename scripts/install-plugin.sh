#!/usr/bin/env bash
set -euo pipefail

# Cortex plugin postInstall driver.
#
# Usage: install-plugin.sh [--postgres]
#        CORTEX_BACKEND=postgres install-plugin.sh   (equivalent)
#
# Two responsibilities:
#   1. Install Cortex. Default backend is SQLite — zero-config: Python
#      deps only, no PostgreSQL/pgvector system install, no eager
#      embedding-model download (the model fetches lazily on first use).
#      Runs scripts/setup.py in SQLite mode on every OS and persists the
#      choice to ~/.claude/methodology/backend.json (read at launch by
#      scripts/launcher.py -> mcp_server/infrastructure/backend_marker.py).
#      PostgreSQL is an explicit opt-in (--postgres / CORTEX_BACKEND) —
#      it dispatches by OS to scripts/setup.sh (macOS/Linux: PostgreSQL +
#      pgvector + schema + model pre-cache) or scripts/setup.py (Windows
#      via Git Bash). An EXISTING PostgreSQL install is auto-detected
#      (env URL, prior marker, or a reachable local cortex database) and
#      kept — an upgrade never silently downgrades a Postgres install
#      to SQLite.
#   2. Remove stale other Cortex installations.
# source: ADR-0740
#
# Stale targets removed:
#   - uv tool install:  hypermnesia-mcp  (current PyPI distribution name)
#       and the legacy neuro-cortex-memory, plus the shims they drop in
#       ~/.local/bin: cortex-doctor, cortex-hook, hypermnesia-mcp,
#       neuro-cortex-memory
#   - pip / pip3 site-packages copies of: hypermnesia-mcp,
#       neuro-cortex-memory, cortex-mcp
#   - Older plugin versions sitting in
#       ~/.claude/plugins/cache/cortex-plugins/hypermnesia-mcp/<X.Y.Z>
#       (only when this script runs from inside the cache, so dev installs
#       at ~/Developments/Cortex never trigger cache pruning)
#
# What is NEVER touched:
#   - User dev clones outside ~/.claude/plugins/cache/
#   - The plugin version that is currently being installed
#   - PostgreSQL data, the cortex database, or any user memories
#
# Idempotent. Safe to re-run.

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

# source: ADR-0740
if command -v cygpath >/dev/null 2>&1; then
    PLUGIN_ROOT="$(cygpath -m "$PLUGIN_ROOT")"
fi

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
say()  { echo -e "${GREEN}[cortex-install]${NC} $1"; }
warn() { echo -e "${YELLOW}[cortex-install]${NC} $1"; }
fail() { echo -e "${RED}[cortex-install]${NC} $1" >&2; exit 1; }

# ── Read current version from the plugin manifest ──────────────────────

PLUGIN_JSON="$PLUGIN_ROOT/.claude-plugin/plugin.json"
if [ ! -f "$PLUGIN_JSON" ]; then
    fail "plugin.json not found at $PLUGIN_JSON"
fi
PY=$(command -v python3 || command -v python || true)
[ -n "$PY" ] || fail "python3 not found in PATH"

# Read CURRENT_VERSION through an environment variable.
# source: ADR-0740
CURRENT_VERSION=$(CORTEX_PLUGIN_JSON_PATH="$PLUGIN_JSON" "$PY" -c "
import json, os
print(json.load(open(os.environ['CORTEX_PLUGIN_JSON_PATH']))['version'])
")

say "Installing Cortex v${CURRENT_VERSION}"

# ── Phase 0: backend selection ──────────────────────────────────────────
#
# Default: sqlite (zero-config). PostgreSQL only when explicitly
# requested (--postgres flag, CORTEX_BACKEND, CORTEX_MEMORY_STORE_BACKEND)
# or when an existing PostgreSQL install is detected — never downgrade.

MARKER_PATH="${HOME}/.claude/methodology/backend.json"

# Explicit request beats detection: a user who asks for a backend gets it.
REQUESTED=""
for arg in "$@"; do
    case "$arg" in
        --postgres) REQUESTED="postgresql" ;;
        *) fail "Unknown argument: $arg (usage: install-plugin.sh [--postgres])" ;;
    esac
done
case "${CORTEX_BACKEND:-}" in
    postgres|postgresql) REQUESTED="postgresql" ;;
    sqlite)              REQUESTED="${REQUESTED:-sqlite}" ;;
esac
# source: ADR-0740
if [ "${CORTEX_MEMORY_STORE_BACKEND:-}" = "sqlite" ] && [ -z "$REQUESTED" ]; then
    REQUESTED="sqlite"
fi

# source: ADR-0740
detect_existing_postgres() {
    if [ -n "${DATABASE_URL:-}" ] || [ -n "${CORTEX_MEMORY_DATABASE_URL:-}" ]; then
        say "Existing PostgreSQL config detected (DATABASE_URL/CORTEX_MEMORY_DATABASE_URL set)"
        return 0
    fi
    if [ -f "$MARKER_PATH" ] && grep -q '"backend"[[:space:]]*:[[:space:]]*"postgresql"' "$MARKER_PATH" 2>/dev/null; then
        say "Existing PostgreSQL install detected (marker: $MARKER_PATH)"
        return 0
    fi
    # source: ADR-0740
    if command -v psql >/dev/null 2>&1 \
        && psql -h 127.0.0.1 -p 5432 -d cortex -tAc "SELECT 1" >/dev/null 2>&1; then
        say "Existing local cortex database detected (127.0.0.1:5432)"
        return 0
    fi
    return 1
}

if [ -n "$REQUESTED" ]; then
    BACKEND="$REQUESTED"
elif detect_existing_postgres; then
    BACKEND="postgresql"
else
    BACKEND="sqlite"
fi
say "Backend: $BACKEND"

# source: ADR-0740
if [ "$BACKEND" = "sqlite" ]; then
    CORTEX_MEMORY_STORE_BACKEND=sqlite "$PY" "$PLUGIN_ROOT/scripts/setup.py" \
        || fail "scripts/setup.py failed. Re-run manually: CORTEX_MEMORY_STORE_BACKEND=sqlite \"$PY\" \"$PLUGIN_ROOT/scripts/setup.py\""
else
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)
            say "Detected Windows ($(uname -s)) — delegating to cross-platform scripts/setup.py"
            "$PY" "$PLUGIN_ROOT/scripts/setup.py" || fail "scripts/setup.py failed. PostgreSQL must be installed and running first (https://www.postgresql.org/download/windows/, then also install pgvector: https://github.com/pgvector/pgvector#windows). Once that is done, re-run manually: \"$PY\" \"$PLUGIN_ROOT/scripts/setup.py\""
            ;;
        Darwin|Linux)
            bash "$PLUGIN_ROOT/scripts/setup.sh"
            ;;
        *)
            fail "Unsupported OS: $(uname -s). Cortex supports macOS, Linux, and Windows (via Git Bash). To retry manually once you've confirmed your shell environment, run: \"$PY\" \"$PLUGIN_ROOT/scripts/setup.py\" (cross-platform) — see also https://github.com/cdeust/Cortex#readme"
            ;;
    esac
fi

# Persist only the backend name; resolve the marker path with Path.home() inside Python.
# source: ADR-0740
MARKER_WRITTEN=$(CORTEX_BACKEND_MARKER_VALUE="$BACKEND" \
CORTEX_BACKEND_MARKER_VERSION="$CURRENT_VERSION" "$PY" -c "
import json, os, pathlib
path = pathlib.Path.home() / '.claude' / 'methodology' / 'backend.json'
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({
    'backend': os.environ['CORTEX_BACKEND_MARKER_VALUE'],
    'written_by': 'install-plugin.sh',
    'plugin_version': os.environ['CORTEX_BACKEND_MARKER_VERSION'],
}, indent=2) + '\n', encoding='utf-8')
print(path)
") || warn "could not persist backend marker (launcher falls back to auto)"
[ -n "$MARKER_WRITTEN" ] && say "Backend persisted: $BACKEND -> $MARKER_WRITTEN"

# ── Phase 2: prune stale OTHER versions ────────────────────────────────

say "Scanning for stale Cortex installs"

PRUNED=0

# 2a) Stale uv tool: hypermnesia-mcp (current PyPI distribution name) and
#     the legacy neuro-cortex-memory. `uv tool uninstall` also removes the
#     venv at ~/.local/share/uv/tools/<name> and the shims at
#     ~/.local/bin/{cortex-doctor,cortex-hook,<name>}.
if command -v uv >/dev/null 2>&1; then
    for tool in hypermnesia-mcp neuro-cortex-memory; do
        if uv tool list 2>/dev/null | grep -q "^${tool} "; then
            warn "Removing stale uv tool: ${tool}"
            uv tool uninstall "${tool}" >/dev/null 2>&1 \
                && PRUNED=$((PRUNED + 1)) \
                || warn "uv tool uninstall ${tool} failed — leaving in place"
        fi
    done
fi

# 2b) Stale pip / pip3 packages. Two known PyPI names that ship Cortex.
for pkg in hypermnesia-mcp neuro-cortex-memory cortex-mcp; do
    for pip_cmd in pip3 pip; do
        if command -v "$pip_cmd" >/dev/null 2>&1; then
            if "$pip_cmd" show "$pkg" >/dev/null 2>&1; then
                warn "Removing stale $pip_cmd package: $pkg"
                "$pip_cmd" uninstall -y "$pkg" >/dev/null 2>&1 \
                    && PRUNED=$((PRUNED + 1)) \
                    || warn "$pip_cmd uninstall $pkg failed — leaving in place"
            fi
        fi
    done
done

# 2c) Stale plugin-cache versions.
#     Only acts when this script is itself running from inside the
#     plugin cache — a dev clone at ~/Developments/Cortex must never
#     trigger cache pruning.
CACHE_ROOT="${HOME}/.claude/plugins/cache/cortex-plugins/hypermnesia-mcp"
case "$PLUGIN_ROOT" in
    "$CACHE_ROOT"/*)
        if [ -d "$CACHE_ROOT" ]; then
            KEEP="$(basename "$PLUGIN_ROOT")"
            for dir in "$CACHE_ROOT"/*; do
                [ -d "$dir" ] || continue
                ver="$(basename "$dir")"
                [ "$ver" = "$KEEP" ] && continue
                warn "Removing stale plugin cache version: $ver"
                rm -rf "$dir" \
                    && PRUNED=$((PRUNED + 1)) \
                    || warn "rm -rf $dir failed — leaving in place"
            done
        fi
        ;;
    *)
        say "Running from dev clone ($PLUGIN_ROOT) — skipping plugin-cache prune"
        ;;
esac

# 2d) Orphan shims in ~/.local/bin pointing at a non-existent venv
#     (e.g. uv-tool python interpreter was removed but the shim survived).
for shim in cortex-doctor cortex-hook hypermnesia-mcp neuro-cortex-memory; do
    path="${HOME}/.local/bin/$shim"
    if [ -f "$path" ]; then
        # First line of a uv-tool shim is `#!/path/to/python`.
        interp=$(head -1 "$path" 2>/dev/null | sed -e 's|^#!||' | awk '{print $1}')
        if [ -n "$interp" ] && [ ! -x "$interp" ]; then
            warn "Removing orphan shim: $path (interpreter gone)"
            rm -f "$path" \
                && PRUNED=$((PRUNED + 1)) \
                || warn "rm -f $path failed — leaving in place"
        fi
    fi
done

if [ "$PRUNED" -eq 0 ]; then
    say "No stale Cortex installs found."
else
    say "Pruned $PRUNED stale Cortex install(s)."
fi

if [ "$BACKEND" = "sqlite" ]; then
    say "Cortex v${CURRENT_VERSION} ready (SQLite, zero-config). Restart Claude Code to activate."
    say "Optional PostgreSQL upgrade: bash \"$PLUGIN_ROOT/scripts/install-plugin.sh\" --postgres"
else
    say "Cortex v${CURRENT_VERSION} ready (PostgreSQL). Restart Claude Code to activate."
fi
