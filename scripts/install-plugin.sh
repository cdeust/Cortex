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
#      (env URL, prior marker, or the launcher's first-launch rule for a
#      HOME with earlier Cortex state, ADR-1104) and kept — an upgrade
#      never silently downgrades a Postgres install to SQLite. A fresh
#      HOME is SQLite even when a local cortex database answers (#704).
#      A managed marker (the plugin's own server, written by Setup after
#      it started, ADR-1114) is kept as written. Unless the environment
#      decides (ADR-1114 7(a)), the installer then installs the
#      dependencies without a system PostgreSQL.
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

# run_setup_py + SETUP_PY_FAILURE: report the check scripts/setup.py
# actually failed instead of naming a component that passed.
# source: issue #621
source "$PLUGIN_ROOT/scripts/lib/setup_py_step.sh"

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
# "Existing" is the launcher's rule (ADR-1104): a HOME with no earlier
# Cortex state is never PostgreSQL by detection (issue #704).

MARKER_PATH="${HOME}/.claude/methodology/backend.json"

# An explicit request beats detection; the environment, when it decides,
# must agree with it (the guard below refuses a contradicting request).
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
# The host option and DATABASE_URL are one setting: the option fills an
# empty URL, trimmed, before anything reads it, so setup.sh (which reads
# DATABASE_URL, not CORTEX_MEMORY_DATABASE_URL) provisions the database
# the option names.
# source: scripts/launcher_backend.py, map_database_option (ADR-1104)
OPTION_URL="${CLAUDE_PLUGIN_OPTION_DATABASE_URL:-}"
OPTION_URL="${OPTION_URL#"${OPTION_URL%%[![:space:]]*}"}"
OPTION_URL="${OPTION_URL%"${OPTION_URL##*[![:space:]]}"}"
if [ -n "$OPTION_URL" ] && ! [[ "${DATABASE_URL:-}" =~ [^[:space:]] ]]; then
    export DATABASE_URL="$OPTION_URL"
fi

# Whether the environment decides, by the launch's own test: a blank URL
# decides nothing, CORTEX_MEMORY_STORE_BACKEND decides either way. Empty
# when nothing decides, else the backend it selects. The installer's own
# `-n` tests disagreed with the launch on all three (issue #704). Any
# non-blank CORTEX_MEMORY_STORE_BACKEND decides at launch, so no marker is
# read; the engine compares it exactly (memory_store.py), and a value that
# is not a backend there ("auto", "Postgres", "SQLITE") opens PostgreSQL
# with a configured URL and SQLite without one. That backend is chosen
# here, never the raw value, which read_backend_marker would reject; a
# blank value is absent, as environment_decides strips it (reviews of #1042). A native Windows Python ends the line with CRLF: tr drops the
# \r ($(...) drops only the \n).
# source: ADR-1114, decision 7(a); backend_marker.environment_decides
# source: memory_store.py, _construct_store (an unknown backend falls through)
# source: scripts/lib/setup_py_step.sh (the same tr -d '\r')
# The line also names the variable that decides, in the launch's order, so
# a refused request says what to unset. Only CORTEX_MEMORY_STORE_BACKEND or
# CORTEX_BACKEND can contradict a request: a URL alone selects postgresql,
# and a sqlite request is CORTEX_BACKEND, which a URL comes after.
# source: backend_marker.resolve_backend_env (precedence of the four variables)
ENV_DECISION=$(PYTHONPATH="$PLUGIN_ROOT" "$PY" -c "
import os
from mcp_server.infrastructure.backend_marker import VALID_BACKENDS, environment_decides, resolve_backend_env
env = dict(os.environ)
chosen = env.get('CORTEX_MEMORY_STORE_BACKEND', '')
url = env.get('DATABASE_URL', '').strip() or env.get('CORTEX_MEMORY_DATABASE_URL', '').strip()
named = resolve_backend_env(env, None).get('CORTEX_MEMORY_STORE_BACKEND')
deciding = [k for k in ('CORTEX_MEMORY_STORE_BACKEND', 'CORTEX_BACKEND', 'DATABASE_URL', 'CORTEX_MEMORY_DATABASE_URL')
            if (named if k == 'CORTEX_BACKEND' else env.get(k, '').strip())]
if chosen.strip() and chosen not in VALID_BACKENDS:
    print('postgresql' if url else 'sqlite', deciding[0])
elif environment_decides(env):
    print(chosen.strip() and chosen or named or 'postgresql', deciding[0])
" | tr -d '\r') || fail "could not read whether the environment decides the backend (ADR-1114 7(a))"
ENV_BACKEND="${ENV_DECISION%% *}"
ENV_VARIABLE="${ENV_DECISION#* }"

# source: ADR-0740
detect_existing_postgres() {
    if [ -f "$MARKER_PATH" ] && grep -q '"backend"[[:space:]]*:[[:space:]]*"postgresql"' "$MARKER_PATH" 2>/dev/null; then
        say "Existing PostgreSQL install detected (marker: $MARKER_PATH)"
        return 0
    fi
    # A saved SQLite choice is a decision too: decide() assumes no marker,
    # so it must not rewrite one (settle_backend reads the marker first).
    # source: ADR-1104, decision 1 (the marker wins over the first launch)
    if [ -f "$MARKER_PATH" ] && grep -q '"backend"[[:space:]]*:[[:space:]]*"sqlite"' "$MARKER_PATH" 2>/dev/null; then
        say "Existing SQLite install kept (marker: $MARKER_PATH)"
        return 1
    fi
    # Nothing above decides: the launcher's own first-launch rule decides,
    # so installer and launcher cannot disagree. A HOME with no earlier
    # Cortex state is SQLite with no connection attempted, even when a
    # local `cortex` database answers (issue #704).
    # source: ADR-1104, decision 1 and Consequences
    local decided
    # The directory of the marker this installer writes, resolved with
    # Path.home() inside Python as the marker write below does (a Git Bash
    # path means nothing to a native Windows Python).
    decided=$(PYTHONPATH="$PLUGIN_ROOT" "$PY" -c "
import pathlib
from mcp_server.infrastructure.backend_resolution import decide
path = pathlib.Path.home() / '.claude' / 'methodology' / 'backend.json'
backend, why = decide(path.parent, path.name)
print(backend + ' (' + why + ')')
") || fail "could not decide the backend (launcher rule, ADR-1104)"
    say "Backend decided by the launcher rule: $decided"
    case "$decided" in
        postgresql*) return 0 ;;
    esac
    return 1
}

# A managed marker carries the server's root and Setup's identity; only
# Setup writes it, after the server started (ADR-1114). decide() assumes
# no marker, so a reinstall must neither re-decide nor rewrite it (#704).
# The environment, when it decides, is read before it (ENV_BACKEND).
# source: ADR-1114, decisions 5 and 7(a), 7(b)
saved_managed_marker() {
    [ -f "$MARKER_PATH" ] && grep -q '"backend"[[:space:]]*:[[:space:]]*"managed"' "$MARKER_PATH" 2>/dev/null
}

# An explicit request the environment contradicts would install a backend
# no launch opens: the environment decides at launch before any marker is
# read, so the request is refused here, never silently overridden either way.
# source: ADR-1114, decision 7(a); issue #704 (precedence, review of #1040)
if [ -n "$REQUESTED" ] && [ -n "$ENV_BACKEND" ] && [ "$REQUESTED" != "$ENV_BACKEND" ]; then
    fail "This run asks for $REQUESTED (--postgres or CORTEX_BACKEND), but the environment makes every launch open $ENV_BACKEND (CORTEX_MEMORY_STORE_BACKEND, CORTEX_BACKEND, DATABASE_URL, CORTEX_MEMORY_DATABASE_URL or the plugin's database_url option; ADR-1114 7(a)). The variable that decides is $ENV_VARIABLE: unset it, or ask for $ENV_BACKEND."
fi
if [ -n "$REQUESTED" ]; then
    BACKEND="$REQUESTED"
elif [ -n "$ENV_BACKEND" ]; then
    say "Backend decided by the environment (ADR-1114 7(a)): $ENV_BACKEND"
    BACKEND="$ENV_BACKEND"
elif saved_managed_marker; then
    say "Existing managed PostgreSQL kept (marker: $MARKER_PATH)"
    BACKEND="managed"
elif detect_existing_postgres; then
    BACKEND="postgresql"
else
    BACKEND="sqlite"
fi
say "Backend: $BACKEND"

# setup.sh and setup.py read DATABASE_URL only, and default it to the local
# cortex database. A URL named in CORTEX_MEMORY_DATABASE_URL alone selects
# PostgreSQL, so it is copied into an empty DATABASE_URL first, trimmed, as
# the launch copies it: Setup provisions the database the user named.
# source: mcp_server/infrastructure/backend_resolution.py, settle_backend
NAMED_URL="${CORTEX_MEMORY_DATABASE_URL:-}"
NAMED_URL="${NAMED_URL#"${NAMED_URL%%[![:space:]]*}"}"
NAMED_URL="${NAMED_URL%"${NAMED_URL##*[![:space:]]}"}"
if [ "$BACKEND" = "postgresql" ] && [ -n "$NAMED_URL" ] \
    && ! [[ "${DATABASE_URL:-}" =~ [^[:space:]] ]]; then
    export DATABASE_URL="$NAMED_URL"
fi

# Remember what the marker said before we overwrite it: if BACKEND is a
# switch away from a previously-persisted, presumably-working backend and
# the new backend's setup then fails, we must restore the old value
# rather than leave the marker pointing at a backend that was never
# actually stood up (that reproduces issue #633's own bug in reverse).
# source: issue #638
# The whole file is kept, not only its backend: a managed marker is
# valid only with the root Setup wrote (read_backend_marker, issue #704).
# The trailing "x" keeps the file's final newlines through $(...).
PREVIOUS_BACKEND=""
PREVIOUS_MARKER_TEXT=""
if [ -f "$MARKER_PATH" ]; then
    PREVIOUS_BACKEND=$(sed -n 's/.*"backend"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p' "$MARKER_PATH" 2>/dev/null | head -1)
    PREVIOUS_MARKER_TEXT=$(cat "$MARKER_PATH" 2>/dev/null; printf x)
    PREVIOUS_MARKER_TEXT="${PREVIOUS_MARKER_TEXT%x}"
fi

# A managed marker that the environment overrides (a configured URL or a
# CORTEX_* backend, not a request of this run) is only ignored at launch,
# so the installer leaves it as Setup wrote it: rewriting it would lose
# the server's root once the override is gone (issue #704).
# source: ADR-1114, decision 7(a)
KEEP_MARKER=""
if [ "$BACKEND" = "managed" ] || { [ -z "$REQUESTED" ] && [ "$PREVIOUS_BACKEND" = "managed" ]; }; then
    KEEP_MARKER=1
    [ "$BACKEND" = "managed" ] || say "Managed marker kept as Setup wrote it: the environment decides this run"
fi

# Resolve the marker path with Path.home() inside Python.
# source: ADR-1088
MARKER_WRITTEN=""
[ -n "$KEEP_MARKER" ] || MARKER_WRITTEN=$(CORTEX_BACKEND_MARKER_VALUE="$BACKEND" \
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

# Only meaningful when PREVIOUS_BACKEND was a real, different, prior
# choice: a fresh install (no prior marker) or a same-backend reinstall
# both leave nothing to restore, which is issue #633's own exact case
# and must stay untouched by this.
# source: issue #638
restore_previous_marker() {
    if [ -n "$PREVIOUS_BACKEND" ] && [ "$PREVIOUS_BACKEND" != "$BACKEND" ] && [ -z "$KEEP_MARKER" ]; then
        # A failed write is said, with Python's own error: a "restored" line
        # over a marker that was not restored is a silent fallback.
        if CORTEX_BACKEND_MARKER_TEXT="$PREVIOUS_MARKER_TEXT" "$PY" -c "
import os, pathlib
path = pathlib.Path.home() / '.claude' / 'methodology' / 'backend.json'
path.write_text(os.environ['CORTEX_BACKEND_MARKER_TEXT'], encoding='utf-8', newline='')
"; then
            warn "Backend switch to $BACKEND failed — restored working marker to $PREVIOUS_BACKEND"
        else
            warn "Backend switch to $BACKEND failed and the earlier marker ($PREVIOUS_BACKEND) could not be restored to $MARKER_PATH"
        fi
    fi
}

# source: ADR-0740
if [ "$BACKEND" = "managed" ]; then
    # Dependencies only: the managed server, its extensions and schema
    # are Setup's (launcher_pg_provision), not a system PostgreSQL.
    # source: ADR-1114
    run_setup_py env CORTEX_SETUP_MANAGED_PG=1 \
        "$PY" "$PLUGIN_ROOT/scripts/setup.py" \
        || fail "scripts/setup.py failed. ${SETUP_PY_FAILURE} Re-run manually: CORTEX_SETUP_MANAGED_PG=1 \"$PY\" \"$PLUGIN_ROOT/scripts/setup.py\""
elif [ "$BACKEND" = "sqlite" ]; then
    run_setup_py env CORTEX_MEMORY_STORE_BACKEND=sqlite \
        "$PY" "$PLUGIN_ROOT/scripts/setup.py" \
        || { restore_previous_marker; fail "scripts/setup.py failed. ${SETUP_PY_FAILURE} Re-run manually: CORTEX_MEMORY_STORE_BACKEND=sqlite \"$PY\" \"$PLUGIN_ROOT/scripts/setup.py\""; }
else
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)
            say "Detected Windows ($(uname -s)) — delegating to cross-platform scripts/setup.py"
            # setup.py lowercases CORTEX_MEMORY_STORE_BACKEND, so a SQLITE the
            # launch refuses (it compares exactly) would skip PostgreSQL here:
            # Setup gets the backend decided above, as the sqlite branch does.
            # source: issue #704, Codex review of #1042
            run_setup_py env CORTEX_MEMORY_STORE_BACKEND="$BACKEND" \
                "$PY" "$PLUGIN_ROOT/scripts/setup.py" \
                || { restore_previous_marker; fail "scripts/setup.py failed. ${SETUP_PY_FAILURE} Re-run manually: CORTEX_MEMORY_STORE_BACKEND=$BACKEND \"$PY\" \"$PLUGIN_ROOT/scripts/setup.py\". If a PostgreSQL check is among them, install PostgreSQL (https://www.postgresql.org/download/windows/) plus pgvector (https://github.com/pgvector/pgvector#windows) and start the PostgreSQL service first."; }
            ;;
        Darwin|Linux)
            bash "$PLUGIN_ROOT/scripts/setup.sh" \
                || { restore_previous_marker; fail "scripts/setup.sh failed while switching to PostgreSQL."; }
            ;;
        *)
            restore_previous_marker
            fail "Unsupported OS: $(uname -s). Cortex supports macOS, Linux, and Windows (via Git Bash). To retry manually once you've confirmed your shell environment, run: \"$PY\" \"$PLUGIN_ROOT/scripts/setup.py\" (cross-platform) — see also https://github.com/cdeust/Cortex#readme"
            ;;
    esac
fi

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

# Setup: install every dependency set and the embedding model now, with the
# progress shown and a non-zero exit when it fails (claude --init-only alone
# is silent and always exits 0). Needs the plugin installed in Claude Code.
# source: ADR-1108
if command -v claude >/dev/null 2>&1; then
    INIT_RC=0
    "$PY" "$PLUGIN_ROOT/scripts/init_plugin.py" || INIT_RC=$?
    case "$INIT_RC" in
        0) ;;
        2) warn "The plugin is not installed in Claude Code; skipping its Setup step" ;;
        *) fail "Cortex's runtime did not install (see above). Re-run: \"$PY\" \"$PLUGIN_ROOT/scripts/init_plugin.py\"" ;;
    esac
fi

if [ "$BACKEND" = "sqlite" ]; then
    say "Cortex v${CURRENT_VERSION} ready (SQLite, zero-config). Restart Claude Code to activate."
    say "Optional PostgreSQL upgrade: bash \"$PLUGIN_ROOT/scripts/install-plugin.sh\" --postgres"
else
    say "Cortex v${CURRENT_VERSION} ready (PostgreSQL). Restart Claude Code to activate."
fi
