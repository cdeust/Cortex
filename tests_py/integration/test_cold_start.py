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

    def _run_hook(self, env_overrides: dict | None = None) -> str:
        """Run session_start.py as subprocess and capture stdout."""
        hook_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "mcp_server",
            "hooks",
            "session_start.py",
        )
        hook_path = os.path.abspath(hook_path)
        env = {**os.environ, **(env_overrides or {})}
        result = subprocess.run(
            [sys.executable, hook_path],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        return result.stdout.strip()

    def test_normal_session_with_memories(self):
        """When DB has memories, hook should inject memory context."""
        from mcp_server.handlers.remember import handler as remember
        import asyncio

        # Store a test memory
        asyncio.run(
            remember(
                {
                    "content": "Critical architecture: use PostgreSQL for all storage",
                    "force": True,
                    "tags": ["_anchor", "architecture"],
                }
            )
        )
        # Mark it as protected/anchored
        from mcp_server.infrastructure.memory_store import MemoryStore

        store = MemoryStore()
        store._conn.execute(
            "UPDATE memories SET is_protected = TRUE, heat = 1.0 "
            "WHERE content LIKE '%Critical architecture%'"
        )
        store.close()

        output = self._run_hook()
        # Should contain memory context, not cold start message
        assert "Cortex" in output
        # Should NOT contain setup instructions
        assert "brew install" not in output

    def test_empty_db_with_session_files_auto_backfills(self):
        """When DB is empty but sessions exist, auto-backfill runs and reports result."""
        from unittest.mock import patch

        from mcp_server.hooks.session_start import _build_cold_start_message

        setup_result = {
            "status": "ready",
            "memories": 0,
            "session_files": 150,
        }
        # Mock _auto_backfill to avoid actual DB operations
        with patch(
            "mcp_server.hooks.session_start._auto_backfill", return_value=42
        ):
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
    """Test that tool errors produce friendly, actionable messages."""

    @pytest.mark.asyncio
    async def test_db_connection_error_returns_setup_guide(self):
        """Database connection errors should return setup instructions."""
        from mcp_server.tool_error_handler import safe_handler

        async def failing_handler(args):
            raise ConnectionError("could not connect to server: Connection refused")

        result = await safe_handler(failing_handler, {})
        parsed = json.loads(result)

        assert parsed["error"] == "database_not_connected"
        assert "PostgreSQL" in parsed["message"]
        assert "brew install" in parsed["message"]

    @pytest.mark.asyncio
    async def test_missing_extension_error(self):
        """Missing pgvector/pg_trgm should show extension install guide."""
        from mcp_server.tool_error_handler import safe_handler

        async def failing_handler(args):
            raise Exception('type "vector" does not exist')

        result = await safe_handler(failing_handler, {})
        parsed = json.loads(result)

        assert parsed["error"] == "missing_extension"
        assert "pgvector" in parsed["message"]

    @pytest.mark.asyncio
    async def test_generic_error_no_traceback(self):
        """Generic errors should not leak Python tracebacks."""
        from mcp_server.tool_error_handler import safe_handler

        async def failing_handler(args):
            raise ValueError("something went wrong")

        result = await safe_handler(failing_handler, {})
        parsed = json.loads(result)

        assert parsed["error"] == "ValueError"
        assert "something went wrong" in parsed["message"]
        # Should NOT contain traceback markers
        assert "Traceback" not in result
        assert "File " not in result

    @pytest.mark.asyncio
    async def test_successful_handler_returns_json(self):
        """Successful handler calls return properly formatted JSON."""
        from mcp_server.tool_error_handler import safe_handler

        async def good_handler(args):
            return {"status": "ok", "count": 42}

        result = await safe_handler(good_handler, {"query": "test"})
        parsed = json.loads(result)

        assert parsed["status"] == "ok"
        assert parsed["count"] == 42

    @pytest.mark.asyncio
    async def test_handler_with_empty_args(self):
        """Handlers that accept no args should work with empty dict."""
        from mcp_server.tool_error_handler import safe_handler

        async def no_arg_handler(args):
            return {"total": 0}

        result = await safe_handler(no_arg_handler, {})
        parsed = json.loads(result)
        assert parsed["total"] == 0


# ── Setup Script Tests ───────────────────────────────────────────────────


class TestSetupScript:
    """Test scripts/setup_db.py auto-configuration."""

    def test_setup_script_exists(self):
        """Setup script must exist at expected path."""
        script = os.path.join(
            os.path.dirname(__file__), "..", "..", "scripts", "setup_db.py"
        )
        assert os.path.exists(os.path.abspath(script))

    def test_setup_reports_ready_or_needs_install(self):
        """Setup script reports 'ready' when PG is available, 'needs_install' when not."""
        script = os.path.join(
            os.path.dirname(__file__), "..", "..", "scripts", "setup_db.py"
        )
        script = os.path.abspath(script)
        plugin_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )

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
