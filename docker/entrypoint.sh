#!/usr/bin/env bash
set -euo pipefail

CORTEX_HOME="/home/cortex"
CLAUDE_HOME="$CORTEX_HOME/.claude"
CLAUDE_MOUNT="$CORTEX_HOME/.claude-host"
CLAUDE_JSON_MOUNT="$CORTEX_HOME/.claude-host-json/.claude.json"
CLAUDE_JSON_HOME="$CORTEX_HOME/.claude.json"

log() { echo "[cortex] $*"; }

# ── Step 1: Start PostgreSQL ──────────────────────────────────────────────

PGDATA="/var/lib/postgresql/17/data"

# Initialize PG data dir if empty (first run with mounted volume)
if [[ ! -f "$PGDATA/PG_VERSION" ]]; then
    log "Initializing PostgreSQL data directory..."
    chown postgres:postgres "$PGDATA"
    su postgres -c "/usr/lib/postgresql/17/bin/initdb -D $PGDATA"
    echo "host all all 127.0.0.1/32 scram-sha-256" >> "$PGDATA/pg_hba.conf"
    echo "listen_addresses = 'localhost'" >> "$PGDATA/postgresql.conf"
fi

log "Starting PostgreSQL..."
chown -R postgres:postgres /run/postgresql /var/log/postgresql "$PGDATA" 2>/dev/null || true
su postgres -c "/usr/lib/postgresql/17/bin/pg_ctl \
  -D $PGDATA \
  -l /var/log/postgresql/postgresql.log \
  start -w -o '-k /run/postgresql'"

# Create role + database (idempotent)
su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='cortex'\" \
  | grep -q 1 || psql -c \"CREATE ROLE cortex LOGIN PASSWORD 'cortex' CREATEDB;\""
su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='cortex'\" \
  | grep -q 1 || psql -c \"CREATE DATABASE cortex OWNER cortex;\""
su postgres -c "psql -d cortex -c \
  'CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;'" \
  2>/dev/null || true

# Initialize schema
PYTHONPATH=/opt/cortex python3 -c "
from mcp_server.infrastructure.pg_schema import get_all_ddl
import psycopg
conn = psycopg.connect('${DATABASE_URL}', autocommit=True)
for ddl in get_all_ddl():
    try: conn.execute(ddl)
    except Exception: pass
conn.close()
" 2>/dev/null && log "Schema initialized" || log "Schema init skipped"

log "PostgreSQL ready"

# ── Step 2: Claude credentials (read-only mount → writable copy) ─────────

mkdir -p "$CLAUDE_HOME/debug" "$CLAUDE_HOME/todos" "$CLAUDE_HOME/plugins"

if [[ -d "$CLAUDE_MOUNT" ]]; then
    # Only copy credentials — NOT settings.json (contains host-specific hooks/paths)
    if [[ -f "$CLAUDE_MOUNT/.credentials.json" ]]; then
        log "Copying credentials from host mount..."
        cp "$CLAUDE_MOUNT/.credentials.json" "$CLAUDE_HOME/.credentials.json"
        chmod 600 "$CLAUDE_HOME/.credentials.json"
    fi
fi

# Copy ~/.claude.json — strip host MCP servers, hooks, and project configs
if [[ -f "$CLAUDE_JSON_MOUNT" && ! -f "$CLAUDE_JSON_HOME" ]]; then
    log "Copying .claude.json from host (stripping host MCP/hooks/projects)..."
    python3 << PYEOF
import json
with open("${CLAUDE_JSON_MOUNT}") as f:
    d = json.load(f)
for key in ("mcpServers", "hooks", "projects"):
    d.pop(key, None)
with open("${CLAUDE_JSON_HOME}", "w") as f:
    json.dump(d, f)
PYEOF
    chmod 600 "$CLAUDE_JSON_HOME"
fi

# Support CLAUDE_CODE_OAUTH_TOKEN env var
if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" && ! -f "$CLAUDE_HOME/.credentials.json" ]]; then
    log "Writing OAuth credentials from CLAUDE_CODE_OAUTH_TOKEN..."
    if echo "$CLAUDE_CODE_OAUTH_TOKEN" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        echo "$CLAUDE_CODE_OAUTH_TOKEN" > "$CLAUDE_HOME/.credentials.json"
    else
        python3 -c "
import json, sys, time
token = sys.argv[1]
creds = {'claudeAiOauth': {
    'accessToken': token, 'refreshToken': '',
    'expiresAt': int(time.time() * 1000) + 28800000
}}
with open('$CLAUDE_HOME/.credentials.json', 'w') as f:
    json.dump(creds, f)
" "$CLAUDE_CODE_OAUTH_TOKEN"
    fi
    chmod 600 "$CLAUDE_HOME/.credentials.json"
fi

# Credential check
if [[ ! -f "$CLAUDE_HOME/.credentials.json" && -z "${ANTHROPIC_API_KEY:-}" && -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
    log "WARNING: No Claude credentials. Set CLAUDE_CODE_OAUTH_TOKEN or mount ~/.claude"
fi

# ── Step 3: Register Cortex MCP server in .claude.json ────────────────────

python3 << 'PYEOF'
import json, os

config_path = "/home/cortex/.claude.json"
try:
    with open(config_path) as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    config = {}

config["mcpServers"] = {
    "cortex": {
        "command": "python3",
        "args": ["-m", "mcp_server"],
        "cwd": "/opt/cortex",
        "env": {
            "DATABASE_URL": "postgresql://cortex:cortex@localhost:5432/cortex",
            "PYTHONPATH": "/opt/cortex"
        }
    }
}

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)
PYEOF

log "MCP server configured"

# ── Step 4: Git + permissions ─────────────────────────────────────────────

chown -R cortex:cortex /workspace "$CORTEX_HOME" 2>/dev/null || true

# ── Step 4b: Install Cortex hooks (as cortex user so ~/.claude resolves correctly) ──

gosu cortex bash -c 'PYTHONPATH=/opt/cortex python3 /opt/cortex/scripts/install_hooks.py --plugin-root /opt/cortex' 2>/dev/null \
    && log "Hooks installed" || log "Hook install skipped"
gosu cortex git config --global --add safe.directory /workspace 2>/dev/null || true
gosu cortex git config --global user.email "${GIT_USER_EMAIL:-cortex@ai-architect.local}"
gosu cortex git config --global user.name "${GIT_USER_NAME:-Cortex}"

# ── Step 5: Launch ────────────────────────────────────────────────────────

log "Starting Claude Code..."
log "Workspace: /workspace"
echo ""

COMMAND="${1:-interactive}"

case "$COMMAND" in
    shell)
        shift || true
        exec gosu cortex /bin/bash "$@"
        ;;
    claude)
        shift || true
        exec gosu cortex claude --dangerously-skip-permissions "$@"
        ;;
    -p|--print)
        exec gosu cortex claude --dangerously-skip-permissions "$@"
        ;;
    interactive)
        exec gosu cortex claude --dangerously-skip-permissions
        ;;
    *)
        log "Starting Claude Code..."
        exec gosu cortex claude --dangerously-skip-permissions "$@"
        ;;
esac
