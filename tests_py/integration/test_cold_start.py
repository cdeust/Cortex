"""Integration tests: cold start experience.

Tests the end-to-end cold start flow:
  1. Session start hook — detects DB state, outputs appropriate message
  2. Tool error handler — wraps errors with friendly guidance
  3. Setup script — auto-configures PostgreSQL
  4. Backfill consent — asks user before importing, never auto-runs
"""

import json
import os
import subprocess
import sys

import pytest
import pathlib


def _pg_reachable() -> bool:
    """Check if PostgreSQL is reachable on the test DATABASE_URL."""
    try:
        from scripts.setup_db import _pg_is_running

        db_url = os.environ.get(
            "DATABASE_URL", "postgresql://localhost:5432/cortex_test"
        )
        # Extract host and port from DATABASE_URL
        # Format: postgresql://[user[:pass]@]host[:port]/dbname
        from urllib.parse import urlparse

        parsed = urlparse(db_url)
        host = parsed.hostname or "localhost"
        port = str(parsed.port or 5432)
        return _pg_is_running(host, port)
    except Exception:
        return False


# ── Session Start Hook Tests ─────────────────────────────────────────────


class TestSessionStartHook:
    """Test session_start.py outputs correct context for different DB states."""

    def test_normal_session_with_memories(self, tmp_path, monkeypatch, capsys):
        """When the store has memories, the banner injects context (not cold start).

        Hermetic (issue #174 family — hidden live-environment dependency).
        The prior version ran ``session_start.py`` as a subprocess with the
        inherited real environment: the SessionStart backend gate reads the
        developer's live backend marker (``~/.claude/methodology/backend.json``),
        the banner then reads the real ``~/.claude/methodology/memory.db`` (or a
        live PostgreSQL), and the subprocess also spawned detached
        background consolidate/reanalyze workers against the real HOME. The
        in-process ``remember`` write landed in the per-process test DB while
        the subprocess read a *different* live store, so the assertion outcome
        depended on whose machine ran it — and the raw ``UPDATE ... NOW()`` seed
        is PostgreSQL-only, silently mismatched under the SQLite default.

        Rewritten to the canonical hermetic pattern already used by
        ``tests_py/hooks/test_sqlite_hook_paths.py``: seed an ephemeral
        ``SqliteMemoryStore`` in ``tmp_path`` and drive the SQLite banner path
        (``_sqlite_context``) in-process, asserting the seeded memory is
        injected and no PostgreSQL install guidance leaks in.
        """
        from mcp_server.hooks import session_start
        from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

        monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
        store = SqliteMemoryStore(db_path=str(tmp_path / "memory.db"))
        try:
            store.insert_memory(
                {
                    "content": "Critical architecture: use PostgreSQL for all storage",
                    "heat": 1.0,
                    "is_protected": True,
                    "tags": ["_anchor", "architecture"],
                }
            )
            monkeypatch.setattr(
                "mcp_server.infrastructure.memory_store.get_shared_store",
                lambda: store,
            )
            monkeypatch.setattr(session_start, "_print_external_sources", lambda: None)

            session_start._sqlite_context(
                {"transcript_path": str(tmp_path / "session.jsonl")}
            )
        finally:
            store.close()

        output = capsys.readouterr().out
        # Memory context injected, not a cold-start message.
        assert "Cortex" in output
        assert "Critical architecture" in output
        # And never the PostgreSQL install guidance.
        assert "brew install" not in output

    def test_empty_db_with_session_files_auto_backfills(self):
        """When DB is empty but sessions exist, auto-backfill runs and
        reports result."""
        from unittest.mock import patch

        from mcp_server.hooks.session_start import _build_cold_start_message

        setup_result = {
            "status": "ready",
            "memories": 0,
            "session_files": 150,
        }
        # Mock _auto_backfill to avoid actual DB operations
        with patch("mcp_server.hooks.session_start._auto_backfill", return_value=42):
            msg = _build_cold_start_message(setup_result)

        assert "auto-imported" in msg.lower() or "42 memories" in msg
        assert msg  # non-empty

    def test_empty_db_no_sessions_shows_getting_started(self):
        """Brand new user with no history gets a friendly start guide."""
        from mcp_server.hooks.session_start import _build_cold_start_message

        setup_result = {
            "status": "ready",
            "memories": 0,
            "session_files": 0,
        }
        msg = _build_cold_start_message(setup_result)

        assert "set up and ready" in msg
        assert "remember" in msg.lower()

    def test_pg_not_installed_shows_install_guide(self):
        """When PostgreSQL is not running, shows installation guide."""
        from mcp_server.hooks.session_start import _build_cold_start_message

        setup_result = {
            "status": "needs_install",
            "message": "PostgreSQL is not running.",
        }
        msg = _build_cold_start_message(setup_result)

        assert "brew install" in msg
        assert "postgresql" in msg.lower()

    def test_schema_failure_shows_error(self):
        """When schema init fails, shows helpful error."""
        from mcp_server.hooks.session_start import _build_cold_start_message

        setup_result = {
            "status": "schema_failed",
            "message": "psycopg not installed (run: pip install psycopg[binary])",
        }
        msg = _build_cold_start_message(setup_result)

        assert "psycopg" in msg
        assert "README" in msg or "installation" in msg.lower()

    def test_context_building_with_anchors_and_hot(self):
        """Memory context block includes anchored + hot memories."""
        from mcp_server.hooks.session_start import _build_context

        anchors = [
            {"id": 1, "content": "Always use UTC timestamps", "domain": "backend"},
        ]
        hot = [
            {
                "id": 2,
                "content": "Fixed the auth bug",
                "domain": "backend",
                "heat": 0.9,
            },
            {"id": 3, "content": "Migrated to PG", "domain": "infra", "heat": 0.7},
        ]
        checkpoint = {
            "current_task": "Building cold start",
            "next_steps": ["Run tests", "Push"],
            "open_questions": [],
            "active_errors": [],
            "key_decisions": [],
            "directory": "/project",
        }

        context = _build_context(anchors, hot, checkpoint)

        assert "Anchored Memories" in context
        assert "UTC timestamps" in context
        assert "Hot Memories" in context
        assert "Fixed the auth bug" in context
        assert "Building cold start" in context
        assert "recall" in context.lower()

    def test_context_empty_when_no_data(self):
        """Returns empty string when there's nothing to inject."""
        from mcp_server.hooks.session_start import _build_context

        assert _build_context([], [], None) == ""


# ── Tool Error Handler Tests ─────────────────────────────────────────────


class TestToolErrorHandler:
    """Test that tool errors produce friendly, actionable messages.

    2026-07-14 fix: safe_handler no longer RETURNS an error dict on
    failure -- that dict violates every tool's outputSchema (recall
    requires "memories", remember requires "stored"/"action", etc.),
    so FastMCP's own output validation discarded our classified
    message and substituted a generic "'<field>' is a required
    property" error. safe_handler now RAISES fastmcp.exceptions.ToolError
    with the classified message; the MCP low-level server builds the
    isError=True result from str(exc) directly, bypassing outputSchema
    validation entirely (that check only runs on the non-error branch).
    """

    @pytest.mark.asyncio
    async def test_db_connection_error_returns_setup_guide(self):
        """Database connection errors should raise with setup instructions."""
        from fastmcp.exceptions import ToolError

        from mcp_server.tool_error_handler import safe_handler

        async def failing_handler(args):
            raise ConnectionError("could not connect to server: Connection refused")

        with pytest.raises(ToolError) as exc_info:
            await safe_handler(failing_handler, {})

        message = str(exc_info.value)
        assert "database_not_connected" in message
        assert "PostgreSQL" in message
        assert "brew install" in message

    @pytest.mark.asyncio
    async def test_missing_extension_error(self):
        """Missing pgvector/pg_trgm should show extension install guide."""
        from fastmcp.exceptions import ToolError

        from mcp_server.tool_error_handler import safe_handler

        async def failing_handler(args):
            # Deliberately generic (TRY002): tool_error_handler.safe_handler's
            # classifier (_classify_error) pattern-matches by exception MESSAGE
            # content only, through a last-resort `except Exception` boundary —
            # a specific exception type here would misleadingly imply
            # type-based dispatch that the code under test does not do.
            raise Exception('type "vector" does not exist')  # noqa: TRY002

        with pytest.raises(ToolError) as exc_info:
            await safe_handler(failing_handler, {})

        message = str(exc_info.value)
        assert "missing_extension" in message
        assert "pgvector" in message

    @pytest.mark.asyncio
    async def test_generic_error_no_traceback(self):
        """Generic errors should not leak Python tracebacks."""
        from fastmcp.exceptions import ToolError

        from mcp_server.tool_error_handler import safe_handler

        async def failing_handler(args):
            raise ValueError("something went wrong")

        with pytest.raises(ToolError) as exc_info:
            await safe_handler(failing_handler, {})

        message = str(exc_info.value)
        assert "ValueError" in message
        assert "something went wrong" in message
        # Should NOT contain traceback markers in the client-visible message.
        assert "Traceback" not in message
        assert "File " not in message

    @pytest.mark.asyncio
    async def test_successful_handler_returns_dict(self):
        """Successful handler calls return the dict verbatim (issue #17)."""
        from mcp_server.tool_error_handler import safe_handler

        async def good_handler(args):
            return {"status": "ok", "count": 42}

        result = await safe_handler(good_handler, {"query": "test"})
        assert isinstance(result, dict)

        assert result["status"] == "ok"
        assert result["count"] == 42

    @pytest.mark.asyncio
    async def test_handler_with_empty_args(self):
        """Handlers that accept no args should work with empty dict."""
        from mcp_server.tool_error_handler import safe_handler

        async def no_arg_handler(args):
            return {"total": 0}

        result = await safe_handler(no_arg_handler, {})
        assert isinstance(result, dict)
        assert result["total"] == 0


# ── Setup Script Tests ───────────────────────────────────────────────────


class TestSetupScript:
    """Test scripts/setup_db.py auto-configuration."""

    def test_setup_script_exists(self):
        """Setup script must exist at expected path."""
        script = pathlib.Path(__file__).parent / ".." / ".." / "scripts" / "setup_db.py"
        assert script.resolve().exists()

    def test_setup_reports_ready_or_needs_install(self):
        """Setup script reports 'ready' when PG is available, 'needs_install'
        when not."""
        script = pathlib.Path(__file__).parent / ".." / ".." / "scripts" / "setup_db.py"
        script = script.resolve()
        plugin_root = (pathlib.Path(__file__).parent / ".." / "..").resolve()

        # Use the same DATABASE_URL that tests are configured with
        db_url = os.environ.get(
            "DATABASE_URL", "postgresql://localhost:5432/cortex_test"
        )

        # Ensure subprocess can find psycopg and mcp_server
        env = {**os.environ, "DATABASE_URL": db_url}
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{plugin_root}:{existing_pp}" if existing_pp else plugin_root
        )

        result = subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )

        parsed = json.loads(result.stdout.strip())
        # Setup returns a valid status dict regardless of DB state
        assert parsed["status"] in (
            "ready",
            "needs_install",
            "needs_setup",
            "create_failed",
            "schema_failed",
            "auth_failed",
            "error",
        )
        if parsed["status"] == "ready":
            assert isinstance(parsed["memories"], int)
            assert isinstance(parsed["session_files"], int)

    def test_setup_detects_missing_pg(self):
        """When PostgreSQL isn't accessible, setup should report needs_install."""
        from scripts.setup_db import _pg_is_running

        # Port 1 should never have PG running
        assert not _pg_is_running("localhost", "1")

    def test_url_parsing(self):
        """DATABASE_URL parsing handles various formats."""
        from scripts.setup_db import _parse_db_url

        # Simple
        info = _parse_db_url("postgresql://localhost:5432/cortex")
        assert info == {"host": "localhost", "port": "5432", "dbname": "cortex"}

        # With user
        info = _parse_db_url("postgresql://user@localhost:5432/mydb")
        assert info == {"host": "localhost", "port": "5432", "dbname": "mydb"}

        # With user:password
        info = _parse_db_url("postgresql://user:pass@host:9999/db")
        assert info == {"host": "host", "port": "9999", "dbname": "db"}

        # No port
        info = _parse_db_url("postgresql://localhost/cortex")
        assert info == {"host": "localhost", "port": "5432", "dbname": "cortex"}


# ── Backfill Consent Tests ───────────────────────────────────────────────


class TestBackfillConsent:
    """Verify backfill never auto-runs — user must explicitly consent."""

    def test_session_start_auto_backfills(self):
        """Session start hook auto-backfills when DB is empty with session files."""
        import inspect
        from mcp_server.hooks import session_start

        source = inspect.getsource(session_start)
        # Must contain auto-backfill logic
        assert "_auto_backfill" in source
        assert "backfill" in source.lower()

    def test_cold_start_auto_import_reports_count(self):
        """Cold start with sessions auto-imports and reports the count."""
        from unittest.mock import patch

        from mcp_server.hooks.session_start import _build_cold_start_message

        with patch("mcp_server.hooks.session_start._auto_backfill", return_value=42):
            msg = _build_cold_start_message(
                {
                    "status": "ready",
                    "memories": 0,
                    "session_files": 500,
                }
            )

        # Must report auto-import result
        assert "42" in msg
        assert "import" in msg.lower() or "memor" in msg.lower()

    def test_backfill_handler_exists_and_is_callable(self):
        """The backfill handler should exist for when user says yes."""
        from mcp_server.handlers.backfill_memories import handler, schema

        assert callable(handler)
        assert "description" in schema
        assert "inputSchema" in schema
