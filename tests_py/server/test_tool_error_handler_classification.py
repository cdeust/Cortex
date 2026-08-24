"""Unit tests for mcp_server.tool_error_handler._classify_error and
safe_handler's error path.

Focus: the anti-silent-fallback boundary (fix/bare-container-contract review
finding #2). RuntimeError raised by memory_store._construct_store when an
explicit DATABASE_URL is unreachable must NOT be reclassified into the
generic "database_not_connected" PostgreSQL-setup guide — that guide tells
the user to install/configure Postgres, discarding the actually load-bearing
information (the fallback was refused on purpose; unset DATABASE_URL or opt
in via CORTEX_ALLOW_SQLITE_FALLBACK=1).

``TestSafeHandlerErrorPath`` covers the 2026-07-14 fix: safe_handler must
RAISE mcp.server.mcpserver.exceptions.ToolError carrying the classified
message (was fastmcp.exceptions.ToolError before the mcp 2.0.0 migration,
PR #331 — same name, same family) (not return an {"error", "message",
"hint"} dict, which fails every tool's outputSchema validation and is
replaced client-side by a generic "'<field>' is a required property"
message), and must log the exception with its traceback before
classifying it away.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.tool_error_handler import _classify_error, safe_handler


class TestExplicitDatabaseUrlUnreachableClassification:
    def test_explicit_refusal_message_is_not_masked(self):
        exc = RuntimeError(
            "explicit DATABASE_URL unreachable "
            "(url=postgresql://127.0.0.1:1/x): "
            "OperationalError: connection failed: connection to server at "
            '"127.0.0.1", port 1 failed: Connection refused; refusing '
            "silent SQLite fallback; unset DATABASE_URL for sandbox mode "
            "or set CORTEX_ALLOW_SQLITE_FALLBACK=1 to opt in"
        )
        error_type, message = _classify_error(exc)
        assert error_type == "explicit_database_url_unreachable"
        assert "refusing silent SQLite fallback" in message

    def test_generic_connection_refused_still_classified_as_db_not_connected(self):
        """Regression guard: unrelated connection errors (the CLI/postgresql
        required path, or any other psycopg failure) must keep getting the
        friendly setup guide — only OUR marker string bypasses it."""
        exc = RuntimeError(
            "PostgreSQL connection failed (url=postgresql://127.0.0.1:1/x): "
            "OperationalError: connection refused"
        )
        error_type, message = _classify_error(exc)
        assert error_type == "database_not_connected"


class TestGenericClassification:
    def test_missing_extension_classified(self):
        exc = Exception('type "vector" does not exist')
        error_type, _ = _classify_error(exc)
        assert error_type == "missing_extension"

    def test_unrecognized_error_falls_through_unclassified(self):
        exc = ValueError("some unrelated application error")
        error_type, message = _classify_error(exc)
        assert error_type == "ValueError"
        assert message == "some unrelated application error"


class TestQueryErrorsAreNotMaskedAsDbNotConnected:
    """Regression: SQLite query-level OperationalErrors were classified as
    'database_not_connected' (PostgreSQL setup guide) because the exception
    CLASS name is 'OperationalError' and the old keyword list matched
    'operationalerror'. A FTS5 syntax error in get_causal_chain surfaced this
    way — the real error was buried under a 'brew install postgresql' guide,
    doubly wrong on the SQLite backend. Query errors must fall through to
    their honest '<Type>: <message>'."""

    def test_fts5_syntax_error_not_masked(self):
        import sqlite3

        exc = sqlite3.OperationalError('fts5: syntax error near ""__main__""')
        error_type, message = _classify_error(exc)
        assert error_type == "OperationalError"
        assert "fts5: syntax error" in message

    def test_no_such_table_not_masked(self):
        import sqlite3

        exc = sqlite3.OperationalError("no such table: memories")
        error_type, message = _classify_error(exc)
        assert error_type == "OperationalError"
        assert "no such table" in message

    def test_column_does_not_exist_not_masked(self):
        # bare "does not exist" used to route a query bug to the DB guide.
        exc = Exception('column "heat" does not exist')
        error_type, _ = _classify_error(exc)
        assert error_type == "Exception"

    def test_word_containing_role_not_masked(self):
        # bare "role" matched substrings like "control"/"payroll" — gone.
        exc = ValueError("invalid role assignment in access control policy")
        error_type, _ = _classify_error(exc)
        assert error_type == "ValueError"

    def test_statement_timeout_not_masked(self):
        # a lock/statement timeout is not a connection failure.
        import sqlite3

        exc = sqlite3.OperationalError("database is locked")
        error_type, _ = _classify_error(exc)
        assert error_type == "OperationalError"

    def test_genuine_connection_failures_still_classified(self):
        for msg in [
            "connection refused",
            "could not connect to server",
            "could not translate host name",
            "server closed the connection unexpectedly",
            "the database system is starting up",
            "password authentication failed for user",
            "connection timed out",
        ]:
            error_type, message = _classify_error(RuntimeError(msg))
            assert error_type == "database_not_connected", msg
            assert "PostgreSQL" in message


class TestSafeHandlerErrorPath:
    """safe_handler must raise ToolError, not return an error dict, and
    must log the underlying exception (with traceback) before
    classification discards it."""

    def test_raises_tool_error_with_classified_message(self):
        async def failing_handler(_args):
            raise ValueError("boom")

        with pytest.raises(ToolError) as exc_info:
            asyncio.run(safe_handler(failing_handler, {}))

        assert "ValueError" in str(exc_info.value)
        assert "boom" in str(exc_info.value)

    def test_logs_exception_with_traceback_before_raising(self, caplog):
        async def failing_handler(_args):
            raise RuntimeError("root cause detail")

        with caplog.at_level(logging.ERROR, logger="mcp_server.tool_error_handler"):
            with pytest.raises(ToolError):
                asyncio.run(safe_handler(failing_handler, {}, tool_name="recall"))

        assert any(
            "RuntimeError" in record.getMessage() and record.exc_info
            for record in caplog.records
        )

    def test_success_path_still_returns_dict_unchanged(self):
        async def good_handler(_args):
            return {"ok": True}

        result = asyncio.run(safe_handler(good_handler, {}))
        assert result == {"ok": True}
