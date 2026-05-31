#!/usr/bin/env bash
set -euo pipefail

# Cortex plugin postInstall driver.
#
# Two responsibilities:
#   1. Install Cortex (delegates to scripts/setup.sh: PostgreSQL + pgvector,
#      Python deps, DB schema, embedding model).
#   2. Remove stale OTHER versions of Cortex installed elsewhere on the
#      machine, so the freshly-installed plugin is the single source of
#      truth.
#
# Stale targets removed:
#   - uv tool install:  neuro-cortex-memory  (PyPI distribution name)
#       and the shims it drops in ~/.local/bin: cortex-doctor,
#       cortex-hook, neuro-cortex-memory
#   - pip / pip3 site-packages copies of: neuro-cortex-memory, cortex-mcp
#   - Older cortex versions sitting in
#       ~/.claude/plugins/cache/cortex-plugins/cortex/<X.Y.Z>
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

CURRENT_VERSION=$("$PY" -c "import json; print(json.load(open('$PLUGIN_JSON'))['version'])")

say "Installing Cortex v${CURRENT_VERSION}"

# ── Phase 1: install (delegates to setup.sh) ───────────────────────────

bash "$PLUGIN_ROOT/scripts/setup.sh"

# ── Phase 2: prune stale OTHER versions ────────────────────────────────

say "Scanning for stale Cortex installs"

PRUNED=0

# 2a) Stale uv tool: neuro-cortex-memory (PyPI distribution name).
#     `uv tool uninstall` also removes the venv at
#     ~/.local/share/uv/tools/neuro-cortex-memory and the shims at
#     ~/.local/bin/{cortex-doctor,cortex-hook,neuro-cortex-memory}.
if command -v uv >/dev/null 2>&1; then
    if uv tool list 2>/dev/null | grep -q '^neuro-cortex-memory '; then
        warn "Removing stale uv tool: neuro-cortex-memory"
        uv tool uninstall neuro-cortex-memory >/dev/null 2>&1 \
            && PRUNED=$((PRUNED + 1)) \
            || warn "uv tool uninstall failed — leaving in place"
    fi
fi

# 2b) Stale pip / pip3 packages. Two known PyPI names that ship Cortex.
for pkg in neuro-cortex-memory cortex-mcp; do
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
CACHE_ROOT="${HOME}/.claude/plugins/cache/cortex-plugins/cortex"
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
for shim in cortex-doctor cortex-hook neuro-cortex-memory; do
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

say "Cortex v${CURRENT_VERSION} ready. Restart Claude Code to activate."
