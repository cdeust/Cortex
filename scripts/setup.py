#!/usr/bin/env python3
"""Cortex — Cross-platform setup script.

Works on Windows, macOS, and Linux. Installs Python dependencies,
sets up the database schema, and pre-caches the embedding model.

PostgreSQL must be installed separately on Windows:
  https://www.postgresql.org/download/windows/
  Also install pgvector: https://github.com/pgvector/pgvector#windows

Usage:
    python3 scripts/setup.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
PLUGIN_DATA = os.environ.get("CLAUDE_PLUGIN_DATA", str(PROJECT_DIR))
DEPS_DIR = os.path.join(PLUGIN_DATA, "deps")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")

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


def check_python() -> None:
    step("Python")
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        fail(f"Python 3.10+ required (found {v.major}.{v.minor})")
    ok(f"Python {v.major}.{v.minor}.{v.micro}")


# ── Step 2: PostgreSQL check ──────────────────────────────────────────


def check_postgresql() -> None:
    step("PostgreSQL")

    # Check pg_isready
    result = run(["pg_isready"])
    if result.returncode != 0:
        if sys.platform == "win32":
            warn(
                "PostgreSQL not running. Install from: https://www.postgresql.org/download/windows/"
            )
            warn("Then start the PostgreSQL service from Windows Services.")
        elif sys.platform == "darwin":
            warn(
                "PostgreSQL not running. Install with: brew install postgresql@17 && brew services start postgresql@17"
            )
        else:
            warn(
                "PostgreSQL not running. Install with: sudo apt install postgresql && sudo systemctl start postgresql"
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


def verify() -> None:
    step("Verification")

    sys.path.insert(0, DEPS_DIR)
    checks = []

    # PostgreSQL
    try:
        import psycopg

        conn = psycopg.connect(DATABASE_URL, autocommit=True)
        conn.execute("SELECT 1")
        checks.append(("PostgreSQL connection", True))
    except Exception:
        checks.append(("PostgreSQL connection", False))
        conn = None

    # Extensions
    if conn:
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM pg_extension WHERE extname IN ('vector', 'pg_trgm')"
            ).fetchone()
            checks.append(("Extensions (pgvector, pg_trgm)", row[0] == 2))
        except Exception:
            checks.append(("Extensions", False))

        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM pg_proc WHERE proname = 'recall_memories'"
            ).fetchone()
            checks.append(("PL/pgSQL recall_memories()", row[0] > 0))
        except Exception:
            checks.append(("PL/pgSQL procedures", False))

        conn.close()

    # sentence-transformers
    try:
        import sentence_transformers  # noqa: F401

        checks.append(("sentence-transformers", True))
    except ImportError:
        checks.append(("sentence-transformers", False))

    # FlashRank
    try:
        from flashrank import Ranker  # noqa: F401

        checks.append(("FlashRank reranker", True))
    except ImportError:
        checks.append(("FlashRank reranker", False))

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
    print(f"  Database:    {DATABASE_URL}")

    check_python()
    check_postgresql()
    install_deps()
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
    print(f"Database: {DATABASE_URL}")
    print(f"Deps:     {DEPS_DIR}")


if __name__ == "__main__":
    main()
