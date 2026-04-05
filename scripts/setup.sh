#!/usr/bin/env bash
set -euo pipefail

# Cortex — Single-command setup
# Installs PostgreSQL + pgvector, Python deps, DB schema, embedding model.
# Usage: bash scripts/setup.sh
#
# What this does:
#   1. Detects OS (macOS / Linux)
#   2. Installs PostgreSQL 17 + pgvector if missing
#   3. Starts PostgreSQL service
#   4. Installs Python dependencies (psycopg, sentence-transformers, flashrank)
#   5. Creates database + extensions + schema
#   6. Pre-caches embedding model (~100MB download)
#   7. Verifies everything works

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DEPS_DIR="${CLAUDE_PLUGIN_DATA:-$PROJECT_DIR}/deps"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[ok]${NC} $1"; }
warn() { echo -e "${YELLOW}[!!]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }
step() { echo -e "\n${YELLOW}===${NC} $1 ${YELLOW}===${NC}"; }

# ── OS Detection ────────────────────────────────────────────────────────

detect_os() {
    case "$(uname -s)" in
        Darwin) echo "macos" ;;
        Linux)  echo "linux" ;;
        *)      echo "unknown" ;;
    esac
}

OS=$(detect_os)
if [ "$OS" = "unknown" ]; then
    fail "Unsupported OS: $(uname -s). Cortex supports macOS and Linux."
fi

echo "Cortex setup — detected OS: $OS"

# ── Step 1: PostgreSQL ──────────────────────────────────────────────────

step "PostgreSQL"

install_postgresql_macos() {
    if ! command -v brew &>/dev/null; then
        fail "Homebrew not found. Install from https://brew.sh"
    fi

    if ! brew list postgresql@17 &>/dev/null 2>&1; then
        echo "Installing PostgreSQL 17..."
        brew install postgresql@17
    fi
    ok "PostgreSQL 17 installed"

    # Ensure it's in PATH
    if ! command -v pg_isready &>/dev/null; then
        export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
    fi

    # Start service
    if ! pg_isready -q 2>/dev/null; then
        echo "Starting PostgreSQL..."
        brew services start postgresql@17
        # Wait for startup
        for i in $(seq 1 10); do
            if pg_isready -q 2>/dev/null; then break; fi
            sleep 1
        done
    fi

    if pg_isready -q 2>/dev/null; then
        ok "PostgreSQL running"
    else
        fail "PostgreSQL failed to start. Try: brew services restart postgresql@17"
    fi
}

install_postgresql_linux() {
    if ! command -v psql &>/dev/null; then
        echo "Installing PostgreSQL..."
        if command -v apt-get &>/dev/null; then
            sudo apt-get update -qq
            sudo apt-get install -y -qq postgresql postgresql-server-dev-all
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y postgresql-server postgresql-devel
            sudo postgresql-setup --initdb 2>/dev/null || true
        else
            fail "No supported package manager (apt/dnf). Install PostgreSQL manually."
        fi
    fi
    ok "PostgreSQL installed"

    # Start service
    if ! pg_isready -q 2>/dev/null; then
        echo "Starting PostgreSQL..."
        sudo systemctl start postgresql 2>/dev/null || sudo service postgresql start 2>/dev/null
        sleep 2
    fi

    if pg_isready -q 2>/dev/null; then
        ok "PostgreSQL running"
    else
        fail "PostgreSQL failed to start. Check: sudo systemctl status postgresql"
    fi
}

if [ "$OS" = "macos" ]; then
    install_postgresql_macos
else
    install_postgresql_linux
fi

# ── Step 2: pgvector extension ──────────────────────────────────────────

step "pgvector extension"

install_pgvector_macos() {
    if ! brew list pgvector &>/dev/null 2>&1; then
        echo "Installing pgvector..."
        brew install pgvector
    fi
    ok "pgvector installed"
}

install_pgvector_linux() {
    # Check if pgvector is already available
    if psql -d postgres -tAc "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'" 2>/dev/null | grep -q 1; then
        ok "pgvector available"
        return
    fi

    echo "Installing pgvector..."
    if command -v apt-get &>/dev/null; then
        # Try the package first (available on Ubuntu 24.04+)
        PG_VERSION=$(psql -tAc "SHOW server_version_num" -d postgres 2>/dev/null | head -c2)
        if sudo apt-get install -y -qq "postgresql-${PG_VERSION}-pgvector" 2>/dev/null; then
            ok "pgvector installed via apt"
            return
        fi
    fi

    # Build from source as fallback
    if command -v git &>/dev/null && command -v make &>/dev/null; then
        echo "Building pgvector from source..."
        TMPDIR=$(mktemp -d)
        git clone --branch v0.8.0 https://github.com/pgvector/pgvector.git "$TMPDIR/pgvector" 2>/dev/null
        cd "$TMPDIR/pgvector"
        make && sudo make install
        cd "$PROJECT_DIR"
        rm -rf "$TMPDIR"
        ok "pgvector built from source"
    else
        fail "Cannot install pgvector. Install git and make, or see: https://github.com/pgvector/pgvector#installation"
    fi
}

if [ "$OS" = "macos" ]; then
    install_pgvector_macos
else
    install_pgvector_linux
fi

# ── Step 3: Python dependencies ─────────────────────────────────────────

step "Python dependencies"

if ! command -v python3 &>/dev/null; then
    fail "Python 3 not found. Install Python 3.10+."
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    fail "Python 3.10+ required (found $PY_VERSION)"
fi
ok "Python $PY_VERSION"

# Install all dependencies to project deps directory
echo "Installing Python packages..."
mkdir -p "$DEPS_DIR"

python3 -m pip install -q --target "$DEPS_DIR" \
    "fastmcp>=2.0.0" \
    "pydantic>=2.0.0" \
    "pydantic-settings>=2.0.0" \
    "numpy>=1.24.0" \
    "psycopg[binary]>=3.1" \
    "pgvector>=0.3" \
    "sentence-transformers>=2.2.0" \
    "flashrank>=0.2.0" \
    2>/dev/null

ok "Python packages installed"

# ── Step 4: Database setup ──────────────────────────────────────────────

step "Database & schema"

export PYTHONPATH="${PROJECT_DIR}:${DEPS_DIR}"
export DATABASE_URL="${DATABASE_URL:-postgresql://localhost:5432/cortex}"

# Run the existing setup_db.py which handles DB creation, extensions, and schema
SETUP_OUTPUT=$(python3 "$SCRIPT_DIR/setup_db.py" 2>/dev/null || true)
SETUP_STATUS=$(echo "$SETUP_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")

if [ "$SETUP_STATUS" = "ready" ]; then
    MEMORY_COUNT=$(echo "$SETUP_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('memories',0))" 2>/dev/null || echo "0")
    ok "Database ready ($MEMORY_COUNT memories)"
elif [ "$SETUP_STATUS" = "needs_install" ]; then
    fail "PostgreSQL setup failed. Check that PostgreSQL is running: pg_isready"
else
    # Try to get error message
    MSG=$(echo "$SETUP_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('message','Unknown error'))" 2>/dev/null || echo "$SETUP_OUTPUT")
    fail "Database setup failed: $MSG"
fi

# ── Step 5: Pre-cache embedding model ───────────────────────────────────

step "Embedding model"

echo "Pre-caching sentence-transformers model (one-time ~100MB download)..."
PYTHONPATH="${PROJECT_DIR}:${DEPS_DIR}" python3 -c "
try:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('all-MiniLM-L6-v2')
    # Verify it works
    emb = model.encode(['test'])
    print(f'Model loaded: {emb.shape[1]}D embeddings')
except Exception as e:
    print(f'Warning: model cache failed ({e}). Will download on first use.')
" 2>/dev/null

ok "Embedding model cached"

# ── Step 6: Verify ──────────────────────────────────────────────────────

step "Verification"

PYTHONPATH="${PROJECT_DIR}:${DEPS_DIR}" python3 -c "
import sys
checks = []

# Check PostgreSQL connection
try:
    import psycopg
    conn = psycopg.connect('${DATABASE_URL}', autocommit=True)
    conn.execute('SELECT 1')
    checks.append(('PostgreSQL connection', True))
except Exception as e:
    checks.append(('PostgreSQL connection', False))

# Check extensions
try:
    row = conn.execute(\"SELECT COUNT(*) FROM pg_extension WHERE extname IN ('vector', 'pg_trgm')\").fetchone()
    checks.append(('Extensions (pgvector, pg_trgm)', row[0] == 2))
except Exception:
    checks.append(('Extensions', False))

# Check stored procedures
try:
    row = conn.execute(\"SELECT COUNT(*) FROM pg_proc WHERE proname = 'recall_memories'\").fetchone()
    checks.append(('PL/pgSQL recall_memories()', row[0] > 0))
except Exception:
    checks.append(('PL/pgSQL procedures', False))

# Check embeddings
try:
    from sentence_transformers import SentenceTransformer
    checks.append(('sentence-transformers', True))
except ImportError:
    checks.append(('sentence-transformers', False))

# Check FlashRank
try:
    from flashrank import Ranker
    checks.append(('FlashRank reranker', True))
except ImportError:
    checks.append(('FlashRank reranker', False))

try:
    conn.close()
except Exception:
    pass

all_ok = True
for name, passed in checks:
    status = '\033[0;32m[ok]\033[0m' if passed else '\033[0;31m[FAIL]\033[0m'
    print(f'  {status} {name}')
    if not passed:
        all_ok = False

sys.exit(0 if all_ok else 1)
"

echo ""
echo -e "${GREEN}Cortex setup complete!${NC}"
echo ""
echo "Hooks are managed by plugin.json — no manual installation needed."
echo ""
echo "Next steps:"
echo "  1. Restart Claude Code to activate"
echo "  2. Start a conversation — Cortex works automatically"
echo "  3. Use /cortex-recall to search memories"
echo ""
echo "Database: ${DATABASE_URL:-postgresql://localhost:5432/cortex}"
echo "Deps:     ${DEPS_DIR}"
