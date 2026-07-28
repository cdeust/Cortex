#!/usr/bin/env python3
"""Cortex — Cross-platform setup script.

Works on Windows, macOS, and Linux. Installs Python dependencies and,
per backend, sets up the database schema and pre-caches the embedding
model.

Usage:
    python3 scripts/setup.py                                # PostgreSQL path
    CORTEX_MEMORY_STORE_BACKEND=sqlite python3 scripts/setup.py   # SQLite path

SQLite mode (the Claude Code plugin's zero-config DEFAULT since the
sqlite-first install change; scripts/install-plugin.sh invokes this
script with CORTEX_MEMORY_STORE_BACKEND=sqlite on every OS):
    Skips PostgreSQL provisioning, schema setup, and the eager
    embedding-model pre-cache entirely. The store schema auto-creates on
    first open (SqliteMemoryStore._init_schema) and the embedding model
    downloads lazily on first encode (~100 MB, one-time — source:
    embedding_engine._ensure_model; size figure per PRIVACY.md /
    scripts/setup.sh step 5). Result: Python deps + verification only.
    This same flag is what gives the Windows postInstall path CI
    coverage on a runner with no PostgreSQL server (source: issue #113).

PostgreSQL mode (default when the flag is unset — the --postgres opt-in
path of scripts/install-plugin.sh on Windows, and the manual
cross-platform path):
    PostgreSQL must already be installed and running:
      https://www.postgresql.org/download/windows/
      Also install pgvector: https://github.com/pgvector/pgvector#windows
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
PLUGIN_DATA = os.environ.get("CLAUDE_PLUGIN_DATA", str(PROJECT_DIR))
DEPS_DIR = os.path.join(PLUGIN_DATA, "deps")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")

# SQLite mode: see module docstring. Any other CORTEX_MEMORY_STORE_BACKEND
# value (unset, "postgresql", "auto") keeps the normal PostgreSQL-required path.
SKIP_POSTGRES = (
    os.environ.get("CORTEX_MEMORY_STORE_BACKEND", "").strip().lower() == "sqlite"
)


def _redact_db_url(url: str) -> str:
    """Mask the password in a database URL before printing.

    Prefer the shared utility when the package is installed; fall back to an
    inline urllib.parse implementation so setup.py is safe to run before
    ``pip install`` has completed (the package may not yet be on sys.path).

    Pre:  url is a str.
    Post: password component of url (if any) is replaced with "***".
    """
    try:
        # engineering choice: import the canonical implementation when
        # available so both code paths stay in sync.
        from mcp_server.shared.redaction import redact_url  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode

        return redact_url(url)
    except ImportError:
        pass
    # Inline stdlib fallback (reached only pre-install, before mcp_server is
    # importable). Mirrors redact_url in redaction.py: masks userinfo AND
    # ?password=/pgpassword query params, and preserves IPv6 host brackets.
    _pw_keys = ("password", "pgpassword")
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return url
    if not parsed.scheme:
        return url
    query = parsed.query
    if query:
        pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
        if any(k.lower() in _pw_keys for k, _ in pairs):
            query = urllib.parse.urlencode(
                [(k, "***" if k.lower() in _pw_keys else v) for k, v in pairs]
            )
    if not parsed.password and query == parsed.query:
        return url
    netloc = parsed.netloc
    if parsed.password:
        user = parsed.username or ""
        host = parsed.hostname or ""
        if ":" in host:  # IPv6 literal — re-wrap in brackets
            host = f"[{host}]"
        port = parsed.port
        netloc = (
            f"{user}:***@{host}:{port}" if port is not None else f"{user}:***@{host}"
        )
    return urllib.parse.urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, query, parsed.fragment)
    )


# Colors (skip on Windows unless WT/modern terminal)
if sys.platform == "win32" and "WT_SESSION" not in os.environ:
    GREEN, YELLOW, RED, NC = "", "", "", ""
else:
    GREEN, YELLOW, RED, NC = "\033[0;32m", "\033[1;33m", "\033[0;31m", "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}[ok]{NC} {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}[!!]{NC} {msg}")


def fail(msg: str) -> None:
    print(f"{RED}[FAIL]{NC} {msg}")
    sys.exit(1)


def step(msg: str) -> None:
    print(f"\n{YELLOW}==={NC} {msg} {YELLOW}==={NC}")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


# ── Step 1: Python version check ──────────────────────────────────────


# source: pyproject.toml requires-python = ">=3.10"
_MIN_PY_MAJOR = 3
_MIN_PY_MINOR = 10

# source: structural — the probe counts the two required extensions
# ('vector', 'pg_trgm'); both present == 2 rows
_REQUIRED_PG_EXTENSIONS = 2


def check_python() -> None:
    step("Python")
    v = sys.version_info
    if v.major < _MIN_PY_MAJOR or (
        v.major == _MIN_PY_MAJOR and v.minor < _MIN_PY_MINOR
    ):
        fail(f"Python 3.10+ required (found {v.major}.{v.minor})")
    ok(f"Python {v.major}.{v.minor}.{v.micro}")


# ── Step 2: PostgreSQL check ──────────────────────────────────────────


def _parse_db_host_port(url: str) -> tuple[str, str]:
    """Extract host and port from a PostgreSQL DSN using stdlib urllib.parse.

    Pre:  url is a non-empty str with a postgresql:// or postgres:// scheme.
    Post: returns (host, port) as strings; falls back to ("localhost", "5432")
          for any component that is absent or unparseable.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "localhost"
        port = str(parsed.port) if parsed.port else "5432"
    except ValueError:
        host, port = "localhost", "5432"
    return host, port


def check_postgresql() -> None:
    step("PostgreSQL")

    # Derive the target host/port from DATABASE_URL so that a remote DSN is
    # probed correctly.  When DATABASE_URL is unset the module-level constant
    # already defaults to postgresql://localhost:5432/cortex, so the parsed
    # values are ("localhost", "5432") and behaviour is unchanged.
    host, port = _parse_db_host_port(DATABASE_URL)

    # Check pg_isready
    result = run(["pg_isready", "-h", host, "-p", port])
    if result.returncode != 0:
        if sys.platform == "win32":
            warn(
                "PostgreSQL not running. Install from: https://www.postgresql.org/download/windows/"
            )
            warn("Then start the PostgreSQL service from Windows Services.")
        elif sys.platform == "darwin":
            warn(
                "PostgreSQL not running. Install with: "
                "brew install postgresql@17 && brew services start postgresql@17"
            )
        else:
            warn(
                "PostgreSQL not running. Install with: "
                "sudo apt install postgresql && sudo systemctl start postgresql"
            )
        fail(
            "PostgreSQL must be running before setup. Start it and re-run this script."
        )

    ok("PostgreSQL running")


# ── Step 3: Python dependencies ───────────────────────────────────────


def install_deps() -> None:
    step("Python dependencies")

    os.makedirs(DEPS_DIR, exist_ok=True)

    packages = [
        "fastmcp>=2.0.0",
        "pydantic>=2.0.0",
        "pydantic-settings>=2.0.0",
        "numpy>=1.24.0",
        "psycopg[binary]>=3.1",
        "pgvector>=0.3",
        "sentence-transformers>=2.2.0",
        "flashrank>=0.2.0",
        "datasets>=2.14.0",
        "networkx>=3.0",
        "tree-sitter>=0.24.0",
        "tree-sitter-language-pack>=0.24.0",
    ]

    print("Installing Python packages...")
    result = run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "--target",
            DEPS_DIR,
            *packages,
        ]
    )

    if result.returncode != 0:
        warn(f"pip install had issues: {result.stderr[:200]}")
    else:
        ok("Python packages installed")


# ── Step 4: Database setup ────────────────────────────────────────────


def setup_database() -> None:
    step("Database & schema")

    # Add deps and project to path
    sys.path.insert(0, DEPS_DIR)
    sys.path.insert(0, str(PROJECT_DIR))
    os.environ["PYTHONPATH"] = f"{PROJECT_DIR}{os.pathsep}{DEPS_DIR}"
    os.environ["DATABASE_URL"] = DATABASE_URL

    setup_script = SCRIPT_DIR / "setup_db.py"
    result = run([sys.executable, str(setup_script)], env=os.environ.copy())

    try:
        data = json.loads(result.stdout)
        status = data.get("status", "unknown")
    except (json.JSONDecodeError, ValueError):
        status = "unknown"

    if status == "ready":
        memories = data.get("memories", 0)
        ok(f"Database ready ({memories} memories)")
    else:
        msg = (
            data.get("message", result.stderr[:200])
            if isinstance(data, dict)
            else result.stdout[:200]
        )
        fail(f"Database setup failed: {msg}")


# ── Step 5: Embedding model ──────────────────────────────────────────


def cache_embedding_model() -> None:
    step("Embedding model")

    sys.path.insert(0, DEPS_DIR)
    print("Pre-caching sentence-transformers model (one-time ~100MB download)...")

    result = run(
        [
            sys.executable,
            "-c",
            "from sentence_transformers import SentenceTransformer; "
            "m = SentenceTransformer('all-MiniLM-L6-v2'); "
            "print(f'Model loaded: {m.encode([\"test\"]).shape[1]}D embeddings')",
        ],
        env={**os.environ, "PYTHONPATH": f"{PROJECT_DIR}{os.pathsep}{DEPS_DIR}"},
    )

    if result.returncode == 0:
        ok("Embedding model cached")
    else:
        warn("Model cache failed — will download on first use")


# ── Step 6: Verify ───────────────────────────────────────────────────


def _sqlite_checks() -> list[tuple[str, bool]]:
    """SQLite-mode checks when PostgreSQL provisioning was skipped.

    Pre:  SKIP_POSTGRES is True.
    Post: returns one (name, passed) pair confirming the sqlite3 stdlib
          module — the only storage dependency this mode needs at
          install time (the store schema auto-creates on first open) —
          is importable.
    """
    try:
        import sqlite3  # noqa: PLC0415, F401 — optional-feature probe: ImportError here is a handled degraded mode

        return [("sqlite3 stdlib", True)]
    except ImportError:
        return [("sqlite3 stdlib", False)]


def _postgres_checks() -> list[tuple[str, bool]]:
    """PostgreSQL connection, extension, and stored-procedure checks.

    Pre:  SKIP_POSTGRES is False; DATABASE_URL points at a server that
          setup_database() has already provisioned.
    Post: returns (name, passed) pairs for the connection, the pgvector/
          pg_trgm extensions, and the recall_memories() stored procedure.
          Never raises — connection/query failures are reported as a
          failed check, not an exception.
    """
    checks: list[tuple[str, bool]] = []
    try:
        import psycopg  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

        conn = psycopg.connect(DATABASE_URL, autocommit=True)
        conn.execute("SELECT 1")
        checks.append(("PostgreSQL connection", True))
    except Exception:  # noqa: BLE001 — setup verification probe — failure becomes a failed check row, never an exception
        checks.append(("PostgreSQL connection", False))
        return checks

    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM pg_extension WHERE extname IN ('vector', 'pg_trgm')"
        ).fetchone()
        checks.append(
            ("Extensions (pgvector, pg_trgm)", row[0] == _REQUIRED_PG_EXTENSIONS)
        )
    except Exception:  # noqa: BLE001 — setup verification probe — failure becomes a failed check row, never an exception
        checks.append(("Extensions", False))

    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM pg_proc WHERE proname = 'recall_memories'"
        ).fetchone()
        checks.append(("PL/pgSQL recall_memories()", row[0] > 0))
    except Exception:  # noqa: BLE001 — setup verification probe — failure becomes a failed check row, never an exception
        checks.append(("PL/pgSQL procedures", False))

    conn.close()
    return checks


def _model_checks() -> list[tuple[str, bool]]:
    """Embedding/reranking dependency import checks (both backends).

    Post: returns (name, passed) pairs for sentence-transformers and
          FlashRank, independent of SKIP_POSTGRES.
    """
    checks: list[tuple[str, bool]] = []
    try:
        import sentence_transformers  # noqa: PLC0415, F401 — optional-feature probe: ImportError here is a handled degraded mode

        checks.append(("sentence-transformers", True))
    except ImportError:
        checks.append(("sentence-transformers", False))

    try:
        from flashrank import Ranker  # noqa: PLC0415, F401 — optional-feature probe: ImportError here is a handled degraded mode

        checks.append(("FlashRank reranker", True))
    except ImportError:
        checks.append(("FlashRank reranker", False))

    return checks


def verify() -> None:
    step("Verification")

    sys.path.insert(0, DEPS_DIR)

    # SQLite mode (see module docstring): no PostgreSQL server is
    # provisioned, so skip the PG-specific checks rather than reporting a
    # false failure for a step that was intentionally not run.
    checks = _sqlite_checks() if SKIP_POSTGRES else _postgres_checks()
    checks += _model_checks()

    all_ok = True
    for name, passed in checks:
        status = f"{GREEN}[ok]{NC}" if passed else f"{RED}[FAIL]{NC}"
        print(f"  {status} {name}")
        if not passed:
            all_ok = False

    if not all_ok:
        fail("Some checks failed — see above")


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    print(f"Cortex setup — {sys.platform}")
    print(f"  Plugin root: {PROJECT_DIR}")
    print(f"  Deps dir:    {DEPS_DIR}")
    print(f"  Database:    {_redact_db_url(DATABASE_URL)}")

    check_python()
    if SKIP_POSTGRES:
        ok(
            "SQLite backend (zero-config default) — no PostgreSQL install, "
            "no schema step (auto-creates on first use). Upgrade anytime: "
            "bash scripts/install-plugin.sh --postgres"
        )
    else:
        check_postgresql()
    install_deps()
    if SKIP_POSTGRES:
        # Lazy model policy for the zero-config path: the embedding model
        # downloads on first encode (embedding_engine._ensure_model), not
        # at install time — this keeps postInstall inside its time budget.
        print(
            "Embedding model: downloads on first use "
            "(~100 MB, one-time — see PRIVACY.md), then runs fully offline."
        )
    else:
        setup_database()
        cache_embedding_model()
    verify()

    print(f"\n{GREEN}Cortex setup complete!{NC}")
    print()
    print("Hooks are managed by plugin.json — no manual installation needed.")
    print()
    print("Next steps:")
    print("  1. Restart Claude Code to activate")
    print("  2. Start a conversation — Cortex works automatically")
    print("  3. Use /cortex-recall to search memories")
    print()
    if SKIP_POSTGRES:
        print("Database: SQLite — ~/.claude/methodology/memory.db")
    else:
        print(f"Database: {_redact_db_url(DATABASE_URL)}")
    print(f"Deps:     {DEPS_DIR}")


if __name__ == "__main__":
    main()
