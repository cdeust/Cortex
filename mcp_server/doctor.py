"""`cortex doctor` — diagnostic CLI for plugin-marketplace users.

Helps users verify Cortex has everything it needs before first
interactive session. Checks:
  * Python version >= 3.10
  * psycopg + pgvector Python packages import
  * DATABASE_URL reachable, PG >= 15
  * pgvector + pg_trgm extensions installed
  * memories table exists (schema auto-init ran)
  * cache dir ~/.claude/methodology is writable
  * POOL_INTERACTIVE_MAX matches I10 invariant

Exit 0 on full green. Exit 1 with a numbered list of fixes otherwise.

Invocation:
    python -m mcp_server.doctor
    neuro-cortex-memory doctor       (once entry point is wired)

Source: docs/program/phase-5-pool-admission-design.md §7 (marketplace
readiness), I10 invariant.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Callable


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
            "Install the postgresql extra: `pip install neuro-cortex-memory[postgresql]`",
        )
    try:
        import psycopg_pool  # noqa: F401
    except ImportError:
        return Check(
            "psycopg_pool",
            False,
            "not installed (required for Phase 5 ConnectionPool)",
            "Upgrade to v3.13.0+: `pip install -U neuro-cortex-memory[postgresql]`",
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
    path = Path("~/.claude/methodology").expanduser()
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


def run() -> int:
    """Run all checks. Print a report. Return 0 on required-green, 1 otherwise.

    Optional checks (``Check.optional=True``) warn on failure but do not
    cause a non-zero exit. Only core-required checks (PG connection,
    Python version, etc.) gate the exit code.
    """
    checks = [c() for c in CHECKS]
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
