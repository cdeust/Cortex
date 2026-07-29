"""Tests for scripts/groomer.py — the G-3 scheduled groomer entry point.

Covers: dry-run writes nothing (real PG — wiki.pages row count and
memories row count are identical before/after), the --apply env-var
gate, the no-promotion invariant (grep, mirroring
test_distill_drain.py::TestNeverCallsLessonPromotion), and journal
artifact shape. Loaded via importlib.util (scripts/ is not a package),
matching tests_py/scripts/test_launcher_resolution.py's convention.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GROOMER_PATH = REPO_ROOT / "scripts" / "groomer.py"


@pytest.fixture
def groomer_module():
    # Dotted to match the path-derived name mutmut keys mutant trampolines
    # on ("scripts.groomer.*") — a synthetic name makes every mutant look
    # unreached to a scoped mutation run (issue #262).
    spec = importlib.util.spec_from_file_location("scripts.groomer", GROOMER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _store():
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import get_shared_store

    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)


def _pg_only():
    store = _store()
    if not hasattr(store, "batch_pool"):
        pytest.skip("groomer dry-run test requires a PostgreSQL store")
    return store


def _row_counts(conn):
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT count(*) AS n FROM memories")
        mem_n = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM wiki.pages")
        page_n = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM wiki.citations")
        cit_n = cur.fetchone()["n"]
    return (mem_n, page_n, cit_n)


class TestNoPromotionInvariant:
    def test_source_never_imports_lesson_promotion_handler(self, groomer_module):
        source = inspect.getsource(groomer_module)
        assert "import lesson_promotion" not in source
        assert "lesson_promotion.handler(" not in source
        # `curate_distill`/`get_grooming_health` are the only judgment-level
        # modules this script may import.
        assert "from mcp_server.handlers.lesson_promotion" not in source

    def test_source_never_calls_add_rule_or_create_trigger(self, groomer_module):
        source = inspect.getsource(groomer_module)
        assert "add_rule.handler" not in source
        assert "create_trigger.handler" not in source
        assert "import add_rule" not in source
        assert "import create_trigger" not in source


class TestDryRunWritesNothing:
    @pytest.mark.asyncio
    async def test_dry_run_leaves_row_counts_unchanged(
        self, groomer_module, monkeypatch
    ):
        store = _pg_only()
        before = _row_counts(store._conn)

        monkeypatch.delenv("CORTEX_HEADLESS_AUTHORING", raising=False)
        result = await groomer_module._run(
            apply=False,
            wiki_max_drains=1,
            wiki_max_anchor_drains=1,
            distill_limit=1,
            force=False,
        )

        after = _row_counts(store._conn)
        assert before == after
        assert result["mode"] == "dry-run"
        assert result["wiki"] is not None
        assert result["distill"] is not None
        assert result["active_session_guard"] is None

    @pytest.mark.asyncio
    async def test_dry_run_forced_previews_without_writing(
        self, groomer_module, monkeypatch
    ):
        """--force with dry-run still writes nothing -- force only
        changes what's REPORTED as due, apply=False still short-circuits
        before any leg executes."""
        store = _pg_only()
        before = _row_counts(store._conn)

        result = await groomer_module._run(
            apply=False,
            wiki_max_drains=1,
            wiki_max_anchor_drains=1,
            distill_limit=1,
            force=True,
        )

        after = _row_counts(store._conn)
        assert before == after
        assert result["due"] == {"wiki": True, "distillation": True}
        assert result["wiki"]["would_run"] is True
        assert result["distill"]["would_run"] is True


class TestApplyRequiresEnvVar:
    @pytest.mark.asyncio
    async def test_apply_without_env_var_refuses(self, groomer_module, monkeypatch):
        _pg_only()
        monkeypatch.delenv("CORTEX_HEADLESS_AUTHORING", raising=False)
        with pytest.raises(SystemExit):
            await groomer_module._run(
                apply=True,
                wiki_max_drains=1,
                wiki_max_anchor_drains=1,
                distill_limit=1,
                force=False,
            )

    @pytest.mark.asyncio
    async def test_apply_with_wrong_env_value_refuses(
        self, groomer_module, monkeypatch
    ):
        _pg_only()
        monkeypatch.setenv("CORTEX_HEADLESS_AUTHORING", "true")  # not "1"
        with pytest.raises(SystemExit):
            await groomer_module._run(
                apply=True,
                wiki_max_drains=1,
                wiki_max_anchor_drains=1,
                distill_limit=1,
                force=False,
            )


class TestActiveSessionGuard:
    @pytest.mark.asyncio
    async def test_apply_skipped_when_session_active(self, groomer_module, monkeypatch):
        _pg_only()
        monkeypatch.setenv("CORTEX_HEADLESS_AUTHORING", "1")
        # Patch the consumer binding: groomer.py imports the guard at module
        # top (PLC0415 hoist), so patching the defining module cannot reach
        # the copy the fixture already bound at exec time.
        monkeypatch.setattr(groomer_module, "has_active_session_window", lambda: True)
        result = await groomer_module._run(
            apply=True,
            wiki_max_drains=1,
            wiki_max_anchor_drains=1,
            distill_limit=1,
            force=True,
        )
        assert result["active_session_guard"] is not None
        assert result["wiki"] is None
        assert result["distill"] is None


class TestJournalArtifact:
    def test_write_journal_produces_json_and_markdown(self, groomer_module, tmp_path):
        fake_result = {
            "health": {
                "kinds": {
                    "wiki": {
                        "backlog_count": 0,
                        "stale": False,
                        "days_since_last_run": 0.1,
                    },
                    "distillation": {
                        "backlog_count": 0,
                        "stale": False,
                        "days_since_last_run": None,
                    },
                    "promotion": {
                        "backlog_count": 5,
                        "stale": True,
                        "days_since_last_run": None,
                    },
                },
                "threshold_days": 6.0,
                "any_stale": True,
            },
            "due": {"wiki": False, "distillation": False},
            "mode": "dry-run",
            "active_session_guard": None,
            "wiki": {"would_run": False},
            "distill": {"would_run": False},
            "promotion_backlog_reported_only": {
                "backlog_count": 5,
                "stale": True,
                "days_since_last_run": None,
            },
        }

        json_path = groomer_module._write_journal(fake_result, tmp_path, "dry-run")
        assert json_path.exists()
        md_path = json_path.with_suffix(".md")
        assert md_path.exists()

        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded["mode"] == "dry-run"
        assert loaded["due"] == {"wiki": False, "distillation": False}

        md_text = md_path.read_text(encoding="utf-8")
        assert "promotion" in md_text
        assert "NEVER" in md_text
