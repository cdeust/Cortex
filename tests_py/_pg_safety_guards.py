"""Fail-closed guards against running the destructive test suite against a
real database or a real `~/.claude` tree.

Extracted from `tests_py/conftest.py` (issue #276/#287 boy-scout follow-up)
as part of bringing that file under the repo's 300-line cap
(coding-standards.md §4.1) — see `tests_py/_pg_throwaway_db.py`'s docstring
for the full rationale. Behavior is unchanged: both guards below still
call `pytest.exit(..., returncode=2)` themselves (that call does not need
to happen inside a named pytest hook — conftest.py invokes these as plain
functions at module-import time, exactly as it invoked the code before the
extraction), with the same messages and the same conditions. The only
change is that they take their inputs as explicit parameters instead of
reading `tests_py/conftest.py`'s module globals directly — an incidental
DI improvement (these are independently testable now), not the goal.
"""

from __future__ import annotations

import os

import pytest
import pathlib


def looks_like_test_db(url: str) -> bool:
    """True when the database NAME declares itself a test/bench database.

    `.rsplit("/", 1)[-1]` and `.split("?", 1)[0]` are both selected for
    their FIRST/LAST-element indexing, not their maxsplit count: `[-1]`
    from `rsplit(sep, N)` is the same for every N>=1 or unlimited (it is
    always "everything after the rightmost separator"), and `[0]` from
    `split(sep, N)` is likewise invariant to N (always "everything before
    the leftmost separator"). Only swapping `rsplit` for `split` (or vice
    versa) on the SAME call changes the result, and only when 2+
    occurrences of that separator are present.
    """
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    return name.endswith("_test") or name.endswith("_bench") or "_test_" in name


def guard_against_populated_db(test_db_url: str) -> None:
    """Refuse to run destructive test isolation against a populated DB.

    INCIDENT 2026-06-10: an agent ran ``DATABASE_URL=<production> CI=true
    pytest`` — the CI branch trusted the URL verbatim and
    ``_clean_all_tables`` deleted 537,396 production memories (plus all
    entities, relationships, and prospective triggers) between tests.

    Two-tier guard, fail-closed:
      * a database whose NAME marks it as a test DB (``*_test`` /
        ``*_bench``) is trusted — local cortex_test and bench DBs;
      * any OTHER name (e.g. the fresh runner-local ``cortex`` that real
        CI creates) must hold ZERO memories at session start. A genuine
        test database is created empty; pre-existing rows mean this is
        somebody's real store. No threshold constant — empty is empty.

    Override (explicit, never default): CORTEX_TEST_ALLOW_POPULATED=1.
    """
    if os.environ.get("CORTEX_TEST_ALLOW_POPULATED") == "1":
        return
    if looks_like_test_db(test_db_url):
        return
    try:
        import psycopg

        with psycopg.connect(test_db_url, autocommit=True, connect_timeout=3) as conn:
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            count = row[0] if row else 0
    except Exception:
        return  # unreachable/uninitialized DB — the SQLite fallback handles it
    if count > 0:
        pytest.exit(
            f"REFUSING to run: test DB '{test_db_url}' is not named like a "
            f"test database and already holds {count} memories. The test "
            "suite DELETEs every table between tests — pointing it at a real "
            "store destroys it (incident 2026-06-10: 537k rows lost). Use a "
            "*_test database, or set CORTEX_TEST_ALLOW_POPULATED=1 if you "
            "really mean it.",
            returncode=2,
        )


def _resolved_real_data_roots() -> list[tuple[str, str]]:
    """`(name, resolved value)` for every root that must stay inside the
    isolated tree — read fresh from `mcp_server`, never from the env vars
    `conftest.py`'s `_redirect_real_data_roots` set: an import that happened
    too early, or a future edit that moves the redirection below the first
    import, would leave these constants bound to the real `~/.claude`
    while the env vars still look correct."""
    from mcp_server.infrastructure.config import CLAUDE_DIR, WIKI_ROOT
    from mcp_server.infrastructure.memory_config import get_memory_settings

    settings = get_memory_settings()
    return [
        ("CLAUDE_DIR", str(CLAUDE_DIR)),
        ("WIKI_ROOT", str(WIKI_ROOT)),
        ("MemorySettings.DB_PATH", settings.DB_PATH),
        ("MemorySettings.SQLITE_FALLBACK_PATH", settings.SQLITE_FALLBACK_PATH),
    ]


# Fail-closed and unconditional: there is no override. A suite that DELETEs
# every table between tests and rewrites the wiki has no safe way to run
# against a real tree (issue #219 — the previous isolation was conditional
# and its failure was silent for as long as it took to notice a 0-row store).
def guard_against_real_data_roots(isolated_claude_dir: str) -> None:
    """Refuse to run if any resolved root still points at real user data."""
    isolated = os.path.realpath(isolated_claude_dir)
    offenders = [
        (name, value)
        for name, value in _resolved_real_data_roots()
        if not os.path.realpath(pathlib.Path(value).expanduser()).startswith(isolated)
    ]
    if not offenders:
        return
    detail = "\n".join(f"    {name} -> {value}" for name, value in offenders)
    real_root = os.path.realpath(pathlib.Path("~/.claude").expanduser())
    pytest.exit(
        "REFUSING to run: test isolation is not in effect. These roots "
        f"still resolve outside the throwaway tree {isolated}:\n{detail}\n"
        f"(real user root: {real_root}). The suite DELETEs every table "
        "between tests and regenerates wiki dashboards — running it "
        "against a real tree destroys data (issue #219). Ensure "
        "_redirect_real_data_roots() runs before any mcp_server import.",
        returncode=2,
    )
