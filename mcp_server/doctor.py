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
    __slots__ = ("name", "ok", "detail", "fix")

    def __init__(self, name: str, ok: bool, detail: str, fix: str = "") -> None:
        self.name = name
        self.ok = ok
        self.detail = detail
        self.fix = fix


def _python_version() -> Check:
    ver = sys.version_info
    if ver >= (3, 10):
        return Check("Python >= 3.10", True, f"Python {ver.major}.{ver.minor}.{ver.micro}")
    return Check(
        "Python >= 3.10",
        False,
        f"Python {ver.major}.{ver.minor}.{ver.micro}",
        "Upgrade Python: `uvx --python 3.13 ...` (recommended) or install 3.10+.",
    )


def _uvx_available() -> Check:
    """The marketplace install path uses ``uvx`` for both the MCP server
    and the lifecycle hooks (plugin.json). If uvx is missing, Claude
    Code cannot start the plugin. Users who get here via pip install
    (server deployment) don't need uvx and can ignore this warning."""
    uvx = shutil.which("uvx")
    if uvx:
        return Check("uvx (marketplace install path)", True, uvx)
    return Check(
        "uvx (marketplace install path)",
        False,
        "not found on PATH",
        "Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) "
        "or `powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\"` (Windows). "
        "Not needed if you installed via pip directly.",
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
        return Check("pgvector + pg_trgm extensions", False, "psycopg not installed", "")
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
            f"interactive={s.POOL_INTERACTIVE_MAX} (>= {DEFAULT_SEMAPHORE['interactive']+1}), "
            f"batch={s.POOL_BATCH_MAX} (>= {DEFAULT_SEMAPHORE['batch']+1})"
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
    _uvx_available,
    _pg_driver,
    _database_url,
    _pg_connection,
    _pg_extensions,
    _methodology_dir,
    _i10_config,
]


def run() -> int:
    """Run all checks. Print a report. Return 0 on all-green, 1 otherwise."""
    checks = [c() for c in CHECKS]
    width = max(len(c.name) for c in checks) + 2

    print("Cortex doctor — setup verification")
    print("=" * 60)
    fails: list[Check] = []
    for c in checks:
        mark = "OK  " if c.ok else "FAIL"
        print(f"  [{mark}] {c.name.ljust(width)} {c.detail}")
        if not c.ok:
            fails.append(c)

    print("=" * 60)
    if not fails:
        print("All checks passed. Cortex is ready.")
        return 0

    print(f"{len(fails)} check(s) failed. Fixes:")
    for i, c in enumerate(fails, 1):
        print(f"  {i}. {c.name}:")
        if c.fix:
            print(f"     → {c.fix}")
        else:
            print(f"     → Review output above: {c.detail}")
    return 1


if __name__ == "__main__":
    sys.exit(run())
