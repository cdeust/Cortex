"""Invariant: the test suite never reads or writes the operator's real data.

Incident 2026-07-28 (issue #219). Isolation in `tests_py/conftest.py` used to
be conditional on PostgreSQL being *unavailable*:

    if not _USE_PG:
        os.environ["CORTEX_MEMORY_SQLITE_FALLBACK_PATH"] = <temp>

On a developer machine where PG is reachable AND the SQLite backend is
selected, that branch never ran. Two things followed:

  * `settings.DB_PATH` resolved to the real `~/.claude/methodology/memory.db`.
    The autouse `_test_isolation` fixture DELETEs every table between tests,
    so running the suite locally wiped that store to 0 rows.
  * `consolidate.handler()` calls `write_dashboards(WIKI_ROOT)`, which walked
    the developer's real wiki (16,234 files — the "suite hangs at 58%"
    symptom) and WROTE generated pages into
    `~/.claude/methodology/wiki/_dashboards/`.

Both roots derive from `config.CLAUDE_DIR`, which had no override seam at
all. The fix adds `CORTEX_CLAUDE_DIR` and redirects it unconditionally.

These tests pin that fix from two angles: the RESOLVED roots are isolated
(not merely the env vars), and a live write-path handler leaves the real
tree untouched. The guard itself — `guard_against_real_data_roots`,
whether it can be silently removed or its module-level call site
weakened — has its own file, `test_real_data_root_guard.py` (issue
#276/#287 boy-scout follow-up, splitting this file under
coding-standards.md §4.1's 300-line cap).
"""

from __future__ import annotations

import os
import unittest.mock as mock
from pathlib import Path

import pytest

_REAL_CLAUDE_DIR = Path(os.path.expanduser("~/.claude")).resolve()


def _real(path: str | Path) -> str:
    return os.path.realpath(os.path.expanduser(str(path)))


def _is_under(path: str | Path, root: Path) -> bool:
    return _real(path).startswith(_real(root))


# ── The resolved roots, not the env vars ─────────────────────────────────────


class TestResolvedRootsAreIsolated:
    """Every path constant Cortex derives must land in the throwaway tree.

    Asserting the RESOLVED constants (rather than `os.environ`) is the point:
    the constants are bound at import time by 40 modules doing
    `from ...config import METHODOLOGY_DIR`. An environment set correctly but
    too late produces correct-looking env vars and real-data constants.
    """

    def test_claude_dir_is_not_the_real_root(self):
        from mcp_server.infrastructure.config import CLAUDE_DIR

        assert not _is_under(CLAUDE_DIR, _REAL_CLAUDE_DIR), (
            f"CLAUDE_DIR resolved to {CLAUDE_DIR}, inside the operator's real "
            f"{_REAL_CLAUDE_DIR}. The suite deletes tables and rewrites wiki "
            "pages — it must never bind here (issue #219)."
        )

    def test_wiki_root_is_not_the_real_wiki(self):
        """The wiki is the root that `consolidate` WRITES to.

        `write_dashboards` does `mkdir(parents=True, exist_ok=True)` and
        `path.write_text(...)` per domain — an unisolated WIKI_ROOT means the
        suite generates pages into the operator's real wiki.
        """
        from mcp_server.infrastructure.config import WIKI_ROOT

        assert not _is_under(WIKI_ROOT, _REAL_CLAUDE_DIR), (
            f"WIKI_ROOT resolved to {WIKI_ROOT}, inside the real "
            f"{_REAL_CLAUDE_DIR} — consolidate would write dashboards there."
        )

    @pytest.mark.parametrize("field", ["DB_PATH", "SQLITE_FALLBACK_PATH"])
    def test_sqlite_paths_are_not_the_real_store(self, field: str):
        """Both SQLite settings must be isolated, not just one.

        Handlers pass the deprecated `DB_PATH` to the store while the store
        itself falls back to `SQLITE_FALLBACK_PATH` (memory_config.py:48-49).
        Isolating only one leaves the other resolving to the real file.
        """
        from mcp_server.infrastructure.memory_config import get_memory_settings

        value = getattr(get_memory_settings(), field)
        assert not _is_under(value, _REAL_CLAUDE_DIR), (
            f"MemorySettings.{field} resolved to {value}, inside the real "
            f"{_REAL_CLAUDE_DIR}. The between-test purge would wipe it."
        )

    def test_isolation_survives_an_exported_db_path(self):
        """An operator's exported path must be OVERWRITTEN, not respected.

        The #220 reproduction command exports CORTEX_MEMORY_DB_PATH. Honoring
        it would let any environment re-point the suite at a real file, which
        is exactly the failure mode this invariant exists to prevent. The
        backend a developer selects is their choice; the physical location
        the suite writes to is not.
        """
        from mcp_server.infrastructure.memory_config import get_memory_settings

        resolved = _real(get_memory_settings().DB_PATH)
        assert _real(os.environ["CORTEX_MEMORY_DB_PATH"]) == resolved, (
            "CORTEX_MEMORY_DB_PATH and the resolved DB_PATH disagree — "
            "conftest's unconditional override is no longer in effect."
        )
        assert not _is_under(resolved, _REAL_CLAUDE_DIR)


# ── Behavioral: a live write path leaves the real tree byte-identical ────────


class TestRealTreeIsNeverWritten:
    """Run the handler that caused the incident; the real tree must not move.

    This is the negative assertion the settings checks above cannot make:
    absence of a write IS the behavior under test (§13.1 G4). `consolidate`
    is the specific handler that regenerated dashboards into the operator's
    wiki, so it is the right probe rather than an arbitrary one.
    """

    @staticmethod
    def _fingerprint(root: Path) -> dict[str, tuple[float, int]]:
        """(mtime, size) per file under `root`; empty dict when absent.

        Absence is a valid state, not a skip condition: on CI there is no
        real `~/.claude` tree, so before and after are both empty and the
        equality assertion still holds meaningfully.
        """
        if not root.is_dir():
            return {}
        out: dict[str, tuple[float, int]] = {}
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    st = path.stat()
                    out[str(path)] = (st.st_mtime, st.st_size)
            except OSError:
                continue
        return out

    @pytest.mark.asyncio
    async def test_consolidate_does_not_touch_the_real_wiki(self):
        """The exact call chain from the incident must not write real files.

        consolidate.handler() -> run_wiki_maintenance -> write_dashboards(
        WIKI_ROOT) -> render_dashboard/audit_files. Before the fix this
        walked 16,234 real files and wrote `_dashboards/*.md`.
        """
        from mcp_server.handlers.consolidate import handler

        real_wiki = _REAL_CLAUDE_DIR / "methodology" / "wiki"
        before = self._fingerprint(real_wiki)

        await handler()

        after = self._fingerprint(real_wiki)
        changed = sorted(
            name
            for name in set(before) | set(after)
            if before.get(name) != after.get(name)
        )
        assert not changed, (
            "consolidate() modified files inside the operator's real wiki: "
            f"{changed[:10]} ({len(changed)} total). WIKI_ROOT is not "
            "isolated (issue #219)."
        )

    @pytest.mark.asyncio
    async def test_consolidate_does_not_touch_the_real_sqlite_store(self):
        """The real memory.db must be byte-identical across a full cycle.

        consolidate decays heat, compresses memories to gist/tag, and
        advances consolidation stages — every one of those is a write.
        """
        from mcp_server.handlers.consolidate import handler

        real_db = _REAL_CLAUDE_DIR / "methodology" / "memory.db"
        before = real_db.stat() if real_db.exists() else None

        await handler()

        after = real_db.stat() if real_db.exists() else None
        if before is None and after is None:
            return  # no real store on this machine — nothing to corrupt
        assert before is not None and after is not None, (
            f"consolidate() created or deleted {real_db} — the suite is "
            "bound to the operator's real store."
        )
        assert (before.st_mtime, before.st_size) == (after.st_mtime, after.st_size), (
            f"consolidate() wrote to the operator's real store {real_db} (issue #219)."
        )


# ── The exact set of roots the guard checks ──────────────────────────────────


class TestResolvedRealDataRoots:
    """`_pg_safety_guards._resolved_real_data_roots` names the exact four
    roots `guard_against_real_data_roots` checks. A wrong label here would
    still let the guard fire correctly but tell an operator the wrong name
    for which root escaped."""

    def test_returns_the_four_named_roots_in_order(self):
        from mcp_server.infrastructure import config, memory_config
        from tests_py import _pg_safety_guards

        fake_settings = mock.Mock(
            DB_PATH="/fake/db.sqlite",
            SQLITE_FALLBACK_PATH="/fake/fallback.sqlite",
        )
        with (
            mock.patch.object(config, "CLAUDE_DIR", "/fake/claude"),
            mock.patch.object(config, "WIKI_ROOT", "/fake/claude/wiki"),
            mock.patch.object(
                memory_config, "get_memory_settings", return_value=fake_settings
            ),
        ):
            assert _pg_safety_guards._resolved_real_data_roots() == [
                ("CLAUDE_DIR", "/fake/claude"),
                ("WIKI_ROOT", "/fake/claude/wiki"),
                ("MemorySettings.DB_PATH", "/fake/db.sqlite"),
                ("MemorySettings.SQLITE_FALLBACK_PATH", "/fake/fallback.sqlite"),
            ]


# The guard itself (TestIsolationGuard, TestGuardStructuralIntegrity) moved
# to test_real_data_root_guard.py — issue #276/#287 boy-scout follow-up,
# splitting this file under coding-standards.md §4.1's 300-line cap (see
# that file's docstring for the size-cap rationale).
