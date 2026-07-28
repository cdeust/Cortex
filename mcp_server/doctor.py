"""`cortex doctor` — diagnostic CLI for plugin-marketplace users.

Helps users verify Cortex has everything it needs before first
interactive session. The check list is backend-aware
(``active_checks()``): on the zero-config SQLite default the PostgreSQL
driver/connection/extension checks are replaced by a SQLite store-open
check, so a healthy SQLite install reports green instead of four false
failures.

PostgreSQL backend checks:
  * Python version >= 3.10
  * psycopg + pgvector Python packages import
  * DATABASE_URL reachable, PG >= 15
  * pgvector + pg_trgm extensions installed
  * memories table exists (schema auto-init ran)
  * cache dir ~/.claude/methodology is writable
  * POOL_INTERACTIVE_MAX matches I10 invariant

SQLite backend checks:
  * Python version >= 3.10
  * SQLite store opens and its schema initializes
  * cache dir ~/.claude/methodology is writable
  * POOL_INTERACTIVE_MAX matches I10 invariant

Exit 0 on full green. Exit 1 with a numbered list of fixes otherwise.

Invocation:
    python -m mcp_server.doctor
    hypermnesia-mcp doctor       (once entry point is wired)

Source: docs/program/phase-5-pool-admission-design.md §7 (marketplace
readiness), I10 invariant.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Callable

from mcp_server.observability import silent_failure
from mcp_server.shared.platform import home_dir


class Check:
    __slots__ = ("name", "ok", "detail", "fix", "optional")

    def __init__(
        self,
        name: str,
        ok: bool,
        detail: str,
        fix: str = "",
        optional: bool = False,
    ) -> None:
        self.name = name
        self.ok = ok
        self.detail = detail
        self.fix = fix
        # optional=True means "capability probe" — failure warns but
        # doesn't cause doctor to exit non-zero. Core checks (PG
        # connection, Python version) stay required.
        self.optional = optional


def _python_version() -> Check:
    ver = sys.version_info
    if ver >= (3, 10):
        return Check(
            "Python >= 3.10", True, f"Python {ver.major}.{ver.minor}.{ver.micro}"
        )
    return Check(
        "Python >= 3.10",
        False,
        f"Python {ver.major}.{ver.minor}.{ver.micro}",
        "Upgrade Python: install Python 3.10+ via the official installer "
        "(https://www.python.org/downloads/) or your platform's package manager.",
    )


def _pg_driver() -> Check:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return Check(
            "psycopg driver",
            False,
            "not installed",
            "Install the postgresql extra: `pip install hypermnesia-mcp[postgresql]`",
        )
    try:
        import psycopg_pool  # noqa: F401
    except ImportError:
        return Check(
            "psycopg_pool",
            False,
            "not installed (required for Phase 5 ConnectionPool)",
            "Upgrade to v3.13.0+: `pip install -U hypermnesia-mcp[postgresql]`",
        )
    try:
        import pgvector  # noqa: F401
    except ImportError:
        return Check(
            "pgvector python binding",
            False,
            "not installed",
            "Install postgresql extra (see above).",
        )
    return Check("PG Python drivers", True, "psycopg, psycopg_pool, pgvector imported")


def _database_url() -> Check:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return Check(
            "DATABASE_URL",
            False,
            "not set",
            "Set in shell or plugin env: export DATABASE_URL=postgresql://localhost:5432/cortex",
        )
    return Check("DATABASE_URL", True, url)


def _pg_connection() -> Check:
    try:
        import psycopg
    except ImportError:
        return Check("PG connection", False, "psycopg not installed", "")
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return Check("PG connection", False, "DATABASE_URL not set", "")
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            row = conn.execute("SELECT version()").fetchone()
            return Check("PG connection", True, row[0] if row else "ok")
    except Exception as exc:
        return Check(
            "PG connection",
            False,
            f"{type(exc).__name__}: {exc}",
            "Start PostgreSQL and createdb: `brew services start postgresql@17 && createdb cortex`",
        )


def _pg_extensions() -> Check:
    try:
        import psycopg
    except ImportError:
        return Check(
            "pgvector + pg_trgm extensions", False, "psycopg not installed", ""
        )
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return Check("pgvector + pg_trgm extensions", False, "DATABASE_URL not set", "")
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            rows = conn.execute(
                "SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm')"
            ).fetchall()
            names = {r[0] for r in rows}
            missing = {"vector", "pg_trgm"} - names
            if missing:
                return Check(
                    "pgvector + pg_trgm extensions",
                    False,
                    f"missing: {sorted(missing)}",
                    'psql -d cortex -c "CREATE EXTENSION IF NOT EXISTS vector; '
                    'CREATE EXTENSION IF NOT EXISTS pg_trgm;"',
                )
            return Check("pgvector + pg_trgm extensions", True, "both installed")
    except Exception as exc:
        return Check(
            "pgvector + pg_trgm extensions",
            False,
            f"{type(exc).__name__}: {exc}",
            "",
        )


def _methodology_dir() -> Check:
    # home_dir() honors $HOME on every OS; Path.expanduser() ignores it on
    # Windows. source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.1
    path = home_dir() / ".claude" / "methodology"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok")
        probe.unlink()
        return Check("~/.claude/methodology writable", True, str(path))
    except Exception as exc:
        return Check(
            "~/.claude/methodology writable",
            False,
            f"{type(exc).__name__}: {exc}",
            f"Check directory permissions: `ls -la {path.parent}`",
        )


def _codebase_pipeline() -> Check:
    """Optional: detect the ai-automatised-pipeline MCP server.

    Cortex integrates with it to turn codebase analysis into wiki pages +
    memories + KG entities via the ``ingest_codebase`` tool. Not required
    for core memory operations — users who don't do codebase ingestion
    can ignore this check. Gated to ``optional=True`` so doctor still
    exits 0 on its absence.

    Detection strategy (cheapest first):
      1. ``cortex-pipeline`` or ``automatised-pipeline`` on PATH
      2. A ``cargo`` install cache under ~/.cargo/bin
      3. A sibling git clone at ../anthropic/ai-automatised-pipeline
    """
    candidates = [
        "cortex-pipeline",
        "automatised-pipeline",
        "ai-automatised-pipeline",
    ]
    for cmd in candidates:
        path = shutil.which(cmd)
        if path:
            return Check(
                "codebase-pipeline (optional)",
                True,
                path,
                optional=True,
            )

    # Sibling git checkout is a common dev layout.
    sibling = Path.cwd().parent / "anthropic" / "ai-automatised-pipeline"
    cargo_toml = sibling / "Cargo.toml"
    if cargo_toml.exists():
        return Check(
            "codebase-pipeline (optional)",
            True,
            f"source checkout at {sibling} (run `cargo install --path .` to install)",
            optional=True,
        )

    return Check(
        "codebase-pipeline (optional)",
        False,
        "not installed (ingest_codebase tool will be disabled)",
        "Optional — install only if you want codebase → wiki/memory/KG "
        "ingestion. Clone + build:\n"
        "       git clone https://github.com/cdeust/ai-automatised-pipeline\n"
        "       cd ai-automatised-pipeline && cargo install --path .\n"
        "     Cortex memory / recall works fine without this component.",
        optional=True,
    )


def _i10_config() -> Check:
    """Verify pool config respects I10 invariant without opening a pool."""
    try:
        from mcp_server.handlers.admission import DEFAULT_SEMAPHORE
        from mcp_server.infrastructure.memory_config import get_memory_settings

        s = get_memory_settings()
        ok = (
            s.POOL_INTERACTIVE_MAX >= DEFAULT_SEMAPHORE["interactive"] + 1
            and s.POOL_BATCH_MAX >= DEFAULT_SEMAPHORE["batch"] + 1
        )
        detail = (
            f"interactive={s.POOL_INTERACTIVE_MAX} (>= {DEFAULT_SEMAPHORE['interactive'] + 1}), "
            f"batch={s.POOL_BATCH_MAX} (>= {DEFAULT_SEMAPHORE['batch'] + 1})"
        )
        fix = (
            "Increase CORTEX_MEMORY_POOL_INTERACTIVE_MAX or "
            "CORTEX_MEMORY_POOL_BATCH_MAX until I10 is satisfied."
        )
        return Check("I10 pool capacity", ok, detail, fix if not ok else "")
    except Exception as exc:
        return Check("I10 pool capacity", False, f"{type(exc).__name__}: {exc}", "")


def _sqlite_store() -> Check:
    """SQLite backend: the store opens and its schema initializes.

    One check replaces the four PG checks (driver, URL, connection,
    extensions): SqliteMemoryStore's constructor runs the DDL +
    migrations, so a successful open proves the whole storage path.
    """
    try:
        from mcp_server.infrastructure.memory_config import get_memory_settings
        from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

        path = get_memory_settings().SQLITE_FALLBACK_PATH
        store = SqliteMemoryStore(db_path=path)
        try:
            total = int(store.count_memories().get("total") or 0)
        finally:
            store.close()
        return Check("SQLite store", True, f"{path} ({total} memories)")
    except Exception as exc:
        return Check(
            "SQLite store",
            False,
            f"{type(exc).__name__}: {exc}",
            "Check that ~/.claude/methodology is writable and memory.db is "
            "not corrupt (back it up, then delete it to let the schema "
            "re-initialize).",
        )


CHECKS: list[Callable[[], Check]] = [
    _python_version,
    _pg_driver,
    _database_url,
    _pg_connection,
    _pg_extensions,
    _methodology_dir,
    _i10_config,
    _codebase_pipeline,  # optional — doesn't fail doctor
]

SQLITE_CHECKS: list[Callable[[], Check]] = [
    _python_version,
    _sqlite_store,
    _methodology_dir,
    _i10_config,
    _codebase_pipeline,  # optional — doesn't fail doctor
]


def active_checks() -> list[Callable[[], Check]]:
    """Backend-appropriate check list (single point of truth).

    Resolves the backend exactly like the launcher/hooks do
    (env var, then the installer's backend marker — see
    ``infrastructure.backend_marker.effective_backend``), so doctor
    diagnoses the same store the server would actually open. Any
    resolution failure falls back to the PostgreSQL list — the
    stricter, historical behaviour.
    """
    try:
        from mcp_server.infrastructure.backend_marker import effective_backend

        if effective_backend(os.environ) == "sqlite":
            return SQLITE_CHECKS
    except Exception as exc:  # noqa: BLE001 — PG check list is the documented fallback
        silent_failure.note("doctor.backend_resolution", exc)
    return CHECKS


def run() -> int:
    """Entry point. Dispatches to subcommand if given, else full check.

    Subcommands:
      (none)   Full setup verification (Python, PG, extensions, etc.)
      mcp      MCP startup diagnostics (Discord-debug-friendly)
               Flags:
                 --json   Emit machine-readable JSON report
                 --copy   Prepend a "paste me in Discord" header to the
                          human output (useful for issue templates)
    """
    argv = sys.argv[1:]
    if argv and argv[0] == "mcp":
        from mcp_server.doctor_mcp import run_mcp

        flags = argv[1:]
        json_output = "--json" in flags
        copy_header = "--copy" in flags
        return run_mcp(json_output=json_output, copy_header=copy_header)
    return _run_full_check()


def _run_full_check() -> int:
    """Full setup verification (legacy `cortex-doctor` behaviour)."""
    checks = [c() for c in active_checks()]
    width = max(len(c.name) for c in checks) + 2

    print("Cortex doctor — setup verification")
    print("=" * 60)
    required_fails: list[Check] = []
    optional_warnings: list[Check] = []
    for c in checks:
        if c.ok:
            mark = "OK  "
        elif c.optional:
            mark = "WARN"
        else:
            mark = "FAIL"
        print(f"  [{mark}] {c.name.ljust(width)} {c.detail}")
        if not c.ok:
            if c.optional:
                optional_warnings.append(c)
            else:
                required_fails.append(c)

    print("=" * 60)
    if not required_fails and not optional_warnings:
        print("All checks passed. Cortex is ready.")
        return 0

    if required_fails:
        print(f"{len(required_fails)} required check(s) failed. Fixes:")
        for i, c in enumerate(required_fails, 1):
            print(f"  {i}. {c.name}:")
            if c.fix:
                print(f"     → {c.fix}")
            else:
                print(f"     → Review output above: {c.detail}")

    if optional_warnings:
        print(
            f"\n{len(optional_warnings)} optional capability "
            f"{'is' if len(optional_warnings) == 1 else 'are'} unavailable "
            "(Cortex core features still work):"
        )
        for i, c in enumerate(optional_warnings, 1):
            print(f"  {i}. {c.name}:")
            if c.fix:
                print(f"     → {c.fix}")
            else:
                print(f"     → Review output above: {c.detail}")

    return 1 if required_fails else 0


if __name__ == "__main__":
    sys.exit(run())
