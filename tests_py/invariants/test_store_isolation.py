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

These tests pin that fix from three angles, so a regression cannot be
silent: the RESOLVED roots are isolated (not merely the env vars), a live
write-path handler leaves the real tree untouched, and the conftest guard
that enforces this cannot be deleted or made conditional.
"""

from __future__ import annotations

import os
import unittest.mock as mock
from pathlib import Path

import pytest

_REAL_CLAUDE_DIR = Path(os.path.expanduser("~/.claude")).resolve()

_CONFTEST_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "conftest.py")
)


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


# ── The guard itself cannot be removed or weakened ───────────────────────────


class TestIsolationGuard:
    """`_guard_against_real_data_roots` must fire on a real root.

    The guard checks resolved values so it cannot be fooled by a
    correct-looking environment. These tests drive it against a deliberately
    un-isolated root and assert it aborts the session.
    """

    def test_guard_exits_when_a_root_escapes_isolation(self):
        """A WIKI_ROOT pointing at the real tree must abort with returncode=2.

        Postcondition: pytest.exit called once, returncode=2, message names
        the offending root so an operator can see which one escaped.
        """
        import tests_py.conftest as conftest
        from mcp_server.infrastructure import config

        real_wiki = _REAL_CLAUDE_DIR / "methodology" / "wiki"
        with (
            mock.patch.object(config, "WIKI_ROOT", real_wiki),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            conftest._guard_against_real_data_roots()

        mock_exit.assert_called_once()
        assert mock_exit.call_args[1].get("returncode") == 2
        assert "WIKI_ROOT" in mock_exit.call_args[0][0], (
            "Guard message does not name the offending root — an operator "
            f"cannot tell what escaped: {mock_exit.call_args[0][0]!r}"
        )

    def test_guard_is_silent_when_isolation_holds(self):
        """The live session is isolated, so the guard must NOT fire.

        Without this, a guard that always exits would pass the test above
        while making the suite unrunnable.
        """
        import tests_py.conftest as conftest

        with mock.patch.object(pytest, "exit") as mock_exit:
            conftest._guard_against_real_data_roots()
        mock_exit.assert_not_called()

    def test_guard_has_no_bypass_env_var(self):
        """Unlike the PG guard, this one must offer no override.

        A suite that DELETEs every table and regenerates wiki pages has no
        safe way to run against a real tree, so an escape hatch would only
        ever be used to re-enable the incident.
        """
        with open(_CONFTEST_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()

        start = next(
            i
            for i, line in enumerate(lines)
            if line.startswith("def _guard_against_real_data_roots(")
        )
        end = next(
            (
                i
                for i in range(start + 1, len(lines))
                if lines[i] and lines[i][0] not in (" ", "\t", "\n")
            ),
            len(lines),
        )
        body = "".join(lines[start:end])
        assert "CORTEX_TEST_ALLOW" not in body, (
            "An override env-var was added to the isolation guard. There is "
            "no safe way to run this suite against a real data tree."
        )


class TestGuardStructuralIntegrity:
    """The redirection and the guard must both stay unconditional."""

    def test_redirect_runs_at_module_level(self):
        """`_redirect_real_data_roots()` must be called at zero indentation.

        Inside an `if`, it reintroduces exactly the conditional-isolation bug
        of issue #219.
        """
        with open(_CONFTEST_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()

        calls = [
            line
            for line in lines
            if line.strip().endswith("_redirect_real_data_roots()")
            and not line.startswith((" ", "\t"))
        ]
        assert calls, (
            "conftest.py no longer calls _redirect_real_data_roots() at "
            "module level — real-data roots are unisolated again (#219)."
        )

    def test_guard_call_present_at_module_level(self):
        with open(_CONFTEST_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()

        calls = [
            line
            for line in lines
            if line.strip() == "_guard_against_real_data_roots()"
            and not line.startswith((" ", "\t"))
        ]
        assert calls, (
            "conftest.py no longer calls _guard_against_real_data_roots() at "
            "module level — isolation failures become silent again (#219)."
        )

    def test_redirect_precedes_first_mcp_server_import(self):
        """Ordering is load-bearing: constants bind at import time.

        `from mcp_server.infrastructure.config import METHODOLOGY_DIR` copies
        a value. If any mcp_server import runs before the env var is set, the
        copied value is the real path and no later env change can fix it.
        """
        with open(_CONFTEST_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()

        redirect_lines = [
            i
            for i, line in enumerate(lines)
            if line.strip().endswith("_redirect_real_data_roots()")
            and not line.startswith((" ", "\t"))
        ]
        assert redirect_lines, (
            "conftest.py has no module-level _redirect_real_data_roots() "
            "call, so nothing redirects the real-data roots at all (#219)."
        )
        redirect_line = redirect_lines[0]
        early_imports = [
            (i + 1, line.strip())
            for i, line in enumerate(lines[:redirect_line])
            if line.startswith(("import mcp_server", "from mcp_server"))
        ]
        assert not early_imports, (
            "mcp_server is imported before the roots are redirected, so path "
            f"constants bind to the real tree: {early_imports}"
        )
