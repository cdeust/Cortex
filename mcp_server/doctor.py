"""`cortex doctor` — diagnostic CLI for plugin-marketplace users.

source: ADR-0322"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Callable

from mcp_server.observability import silent_failure
from mcp_server.shared.platform import home_dir
from mcp_server.core.reranker import ensure_reranker_loaded
from mcp_server.hooks.wiring import wire_composition_root
from mcp_server.handlers.admission import DEFAULT_SEMAPHORE
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.infrastructure.backend_marker import effective_backend
from mcp_server.doctor_mcp import run_mcp
from mcp_server.shared.subprocess_safe import run_with_hard_timeout

# source: validate_memory.py:29 precedent (_GIT_CHECK_TIMEOUT_S)
_WORKTREE_LIST_TIMEOUT_S = 2.0


def ensure_reranker_ready():
    """Self-wiring FlashRank preload for standalone callers (CI, `python -m
    mcp_server.doctor`) that never import mcp_server/__main__.py.

    Precondition: none.
    Postcondition: core/reranker_model.py's filesystem seam is configured
    (idempotent — safe to call more than once per process) before
    ``ensure_reranker_loaded`` runs. Calling ``core.reranker.
    ensure_reranker_loaded`` directly from a bare script raises
    RuntimeError instead of loading, because nothing configured the seam
    first (issue #560 CI regression, 2026-09-15:
    `.github/actions/test-suite`'s reranker preload step did exactly that
    and failed on every Python version). This is the composition root for
    that preload — mcp_server/doctor.py already imports both core and
    infrastructure freely, unlike core/ or infrastructure/ themselves.

    source: ADR-0244 (issue #560)"""
    wire_composition_root()
    return ensure_reranker_loaded()


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
        import psycopg  # noqa: PLC0415, F401 — source: ADR-0322
    except ImportError:
        return Check(
            "psycopg driver",
            False,
            "not installed",
            "Install the postgresql extra: `pip install hypermnesia-mcp[postgresql]`",
        )
    try:
        import psycopg_pool  # noqa: PLC0415, F401 — source: ADR-0322
    except ImportError:
        return Check(
            "psycopg_pool",
            False,
            "not installed (required for Phase 5 ConnectionPool)",
            "Upgrade to v3.13.0+: `pip install -U hypermnesia-mcp[postgresql]`",
        )
    try:
        import pgvector  # noqa: PLC0415, F401 — source: ADR-0322
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
        import psycopg  # noqa: PLC0415 — source: ADR-0322
    except ImportError:
        return Check("PG connection", False, "psycopg not installed", "")
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return Check("PG connection", False, "DATABASE_URL not set", "")
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            row = conn.execute("SELECT version()").fetchone()
            return Check("PG connection", True, row[0] if row else "ok")
    except Exception as exc:  # noqa: BLE001 — source: ADR-0322
        return Check(
            "PG connection",
            False,
            f"{type(exc).__name__}: {exc}",
            "Start PostgreSQL and createdb: "
            "`brew services start postgresql@17 && createdb cortex`",
        )


def _pg_extensions() -> Check:
    try:
        import psycopg  # noqa: PLC0415 — source: ADR-0322
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
                "SELECT extname FROM pg_extension "
                "WHERE extname IN ('vector', 'pg_trgm')"
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
    except Exception as exc:  # noqa: BLE001 — source: ADR-0322
        return Check(
            "pgvector + pg_trgm extensions",
            False,
            f"{type(exc).__name__}: {exc}",
            "",
        )


def _methodology_dir() -> Check:
    # source: ADR-0322

    path = home_dir() / ".claude" / "methodology"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok")
        probe.unlink()
        return Check("~/.claude/methodology writable", True, str(path))
    except Exception as exc:  # noqa: BLE001 — source: ADR-0322
        return Check(
            "~/.claude/methodology writable",
            False,
            f"{type(exc).__name__}: {exc}",
            f"Check directory permissions: `ls -la {path.parent}`",
        )


def _codebase_pipeline() -> Check:
    """Optional: detect the ai-architect-mcp-codebase MCP server.

    source: ADR-0322

    Detection strategy (cheapest first):
      1. ``cortex-pipeline`` or ``ai-architect-mcp-codebase`` on PATH
      2. A ``cargo`` install cache under ~/.cargo/bin
      3. A sibling git clone at ../anthropic/ai-architect-mcp-codebase
    """
    candidates = [
        "cortex-pipeline",
        "ai-architect-mcp-codebase",
        "ai-architect-mcp-codebase",
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
    sibling = Path.cwd().parent / "anthropic" / "ai-architect-mcp-codebase"
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
        "       git clone https://github.com/cdeust/ai-architect-mcp-codebase\n"
        "       cd ai-architect-mcp-codebase && cargo install --path .\n"
        "     Cortex memory / recall works fine without this component.",
        optional=True,
    )


def _worktree_list() -> list[dict[str, object]] | None:
    """Parse ``git worktree list --porcelain``, main worktree first.

    precondition: none — safe to call outside a git checkout.
    postcondition: returns one dict per worktree block, in the order git
    printed them (the main worktree is always first — git-worktree(1)
    section list). Each dict carries ``path`` (str), ``bare`` (bool),
    ``prunable`` (bool). Returns ``None`` when ``git`` is missing, the cwd
    isn't a git checkout, or the command times out — every failure mode
    of ``run_with_hard_timeout`` collapses to the same "not applicable"
    signal, never a raised exception.

    source: ADR-1079"""
    out = run_with_hard_timeout(
        ["git", "worktree", "list", "--porcelain"],
        cwd=Path.cwd(),
        timeout=_WORKTREE_LIST_TIMEOUT_S,
    )
    if out is None:
        return None
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            if current is not None:
                entries.append(current)
            current = {
                "path": line[len("worktree ") :].strip(),
                "bare": False,
                "prunable": False,
            }
        elif line == "bare" and current is not None:
            current["bare"] = True
        elif line.startswith("prunable") and current is not None:
            current["prunable"] = True
    if current is not None:
        entries.append(current)
    return entries or None


def _worktree_classification(entries: list[dict[str, object]]) -> tuple[bool, str]:
    """Classify worktree ``entries`` (``_worktree_list()`` output, main
    first) against the allowed-location rule.

    postcondition: ``ok`` is True for "not a git checkout" (empty
    ``entries``), a bare main repo, and full compliance; False carries
    every offending resolved path in ``detail``. The allowed root is
    derived from ``entries[0]`` (the main worktree — always first, per
    git-worktree(1) section list), never from ``git rev-parse
    --show-toplevel``, which resolves to a linked worktree's own path
    when run from inside one and would false-positive on every sibling.

    source: ADR-1079 (rule: docs/agent-guidance.md:160-166)"""
    if not entries:
        return True, "not a git checkout"
    main = entries[0]
    if main.get("bare"):
        return True, "bare repository — rule not applicable"
    allowed_root = (Path(str(main["path"])) / ".claude" / "worktrees").resolve()
    outside = [
        str(Path(str(e["path"])).resolve())
        for e in entries[1:]
        if not e.get("prunable")
        and not _under(Path(str(e["path"])).resolve(), allowed_root)
    ]
    if not outside:
        return True, f"all worktrees under {allowed_root}"
    return False, f"outside {allowed_root}: {', '.join(outside)}"


def _worktree_locations() -> Check:
    """Optional: WARN when a registered worktree lives outside
    ``<main-worktree>/.claude/worktrees/``. Reports only — never fixes,
    never moves the worktree, never fails doctor's exit code
    (``optional=True``).

    source: ADR-1078 (rule reported: docs/agent-guidance.md:160-166)"""
    ok, detail = _worktree_classification(_worktree_list() or [])
    fix = (
        ""
        if ok
        else "Move or remove these worktrees — the only allowed location "
        "is <repo>/.claude/worktrees/<name>/ "
        "(source: docs/agent-guidance.md:160-166)."
    )
    return Check("worktree locations (optional)", ok, detail, fix, optional=True)


def _under(path: Path, root: Path) -> bool:
    """True iff ``path`` is ``root`` or a descendant of it (both resolved)."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _i10_config() -> Check:
    """Verify pool config respects I10 invariant without opening a pool."""
    try:
        s = get_memory_settings()
        ok = (
            s.POOL_INTERACTIVE_MAX >= DEFAULT_SEMAPHORE["interactive"] + 1
            and s.POOL_BATCH_MAX >= DEFAULT_SEMAPHORE["batch"] + 1
        )
        detail = (
            f"interactive={s.POOL_INTERACTIVE_MAX} "
            f"(>= {DEFAULT_SEMAPHORE['interactive'] + 1}), "
            f"batch={s.POOL_BATCH_MAX} (>= {DEFAULT_SEMAPHORE['batch'] + 1})"
        )
        fix = (
            "Increase CORTEX_MEMORY_POOL_INTERACTIVE_MAX or "
            "CORTEX_MEMORY_POOL_BATCH_MAX until I10 is satisfied."
        )
        return Check("I10 pool capacity", ok, detail, fix if not ok else "")
    except Exception as exc:  # noqa: BLE001 — source: ADR-0322
        return Check("I10 pool capacity", False, f"{type(exc).__name__}: {exc}", "")


def _sqlite_store() -> Check:
    """SQLite backend: the store opens and its schema initializes.

    source: ADR-0322"""
    try:
        path = get_memory_settings().SQLITE_FALLBACK_PATH
        store = SqliteMemoryStore(db_path=path)
        try:
            total = int(store.count_memories().get("total") or 0)
        finally:
            store.close()
        return Check("SQLite store", True, f"{path} ({total} memories)")
    except Exception as exc:  # noqa: BLE001 — source: ADR-0322
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
    _worktree_locations,  # optional — doesn't fail doctor
]

SQLITE_CHECKS: list[Callable[[], Check]] = [
    _python_version,
    _sqlite_store,
    _methodology_dir,
    _i10_config,
    _codebase_pipeline,  # optional — doesn't fail doctor
    _worktree_locations,  # optional — doesn't fail doctor
]


def active_checks() -> list[Callable[[], Check]]:
    """Backend-appropriate check list (single point of truth).

    source: ADR-0322"""
    try:
        if effective_backend(os.environ) == "sqlite":
            return SQLITE_CHECKS
    except Exception as exc:  # noqa: BLE001 — source: ADR-0322
        silent_failure.note("doctor.backend_resolution", exc)
    return CHECKS


def run() -> int:
    """Entry point. Dispatches to subcommand if given, else full check.

    source: ADR-0322"""
    argv = sys.argv[1:]
    if argv and argv[0] == "mcp":
        flags = argv[1:]
        json_output = "--json" in flags
        copy_header = "--copy" in flags
        return run_mcp(json_output=json_output, copy_header=copy_header)
    return _run_full_check()


def _run_full_check() -> int:
    """source: ADR-0322"""
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
