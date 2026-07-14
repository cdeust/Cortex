"""Tests for mcp_server.handlers.check_setup — MCP facade over doctor.py.

Contract under test (from check_setup.py docstrings and schema):
  POST-1: `checks` has exactly len(CHECKS) entries, in CHECKS' own order
          (no reordering/filtering — mirrors doctor's dependency order:
          Python -> driver -> DATABASE_URL -> connection -> extensions -> FS).
  POST-2: `ready` is True iff no non-optional check failed.
  POST-3: `fixes_needed` counts failing non-optional checks only; an
          optional-check failure (e.g. codebase-pipeline probe) never
          blocks readiness or is counted.
  POST-4: no check logic is duplicated — the handler calls the exact
          `Check` callables from `mcp_server.doctor.CHECKS`.
  POST-5: schema takes no arguments (composition-root/facade, not a
          re-implementation).
"""

import asyncio

from mcp_server.doctor import Check
from mcp_server.handlers.check_setup import handler, schema


def _fake_check(name: str, ok: bool, optional: bool = False, fix: str = "") -> Check:
    return Check(name, ok, detail=f"{name} detail", fix=fix, optional=optional)


class TestCheckSetupHandlerAllGreen:
    """DB up, everything green — POST-2, POST-3."""

    def test_ready_true_when_all_pass(self, monkeypatch):
        checks = [
            lambda: _fake_check("Python >= 3.10", True),
            lambda: _fake_check("PG Python drivers", True),
            lambda: _fake_check("DATABASE_URL", True),
            lambda: _fake_check("PG connection", True),
            lambda: _fake_check("pgvector + pg_trgm extensions", True),
            lambda: _fake_check("~/.claude/methodology writable", True),
        ]
        monkeypatch.setattr("mcp_server.handlers.check_setup.CHECKS", checks)

        result = asyncio.run(handler())

        assert result["ready"] is True
        assert result["summary"] == "ready"
        assert result["fixes_needed"] == 0
        assert len(result["checks"]) == len(checks)
        assert all(c["ok"] for c in result["checks"])


class TestCheckSetupHandlerDbDown:
    """DB down — a required check fails partway through the dependency
    chain (mirrors: DATABASE_URL set but PG connection refused)."""

    def test_ready_false_and_fixes_needed_counts_required_only(self, monkeypatch):
        checks = [
            lambda: _fake_check("Python >= 3.10", True),
            lambda: _fake_check("PG Python drivers", True),
            lambda: _fake_check("DATABASE_URL", True),
            lambda: _fake_check(
                "PG connection",
                False,
                fix="Start PostgreSQL and createdb: `brew services start "
                "postgresql@17 && createdb cortex`",
            ),
            lambda: _fake_check("pgvector + pg_trgm extensions", False),
            lambda: _fake_check("~/.claude/methodology writable", True),
            # Optional probe also fails but must not count toward fixes_needed.
            lambda: _fake_check("codebase-pipeline (optional)", False, optional=True),
        ]
        monkeypatch.setattr("mcp_server.handlers.check_setup.CHECKS", checks)

        result = asyncio.run(handler())

        assert result["ready"] is False
        assert result["fixes_needed"] == 2  # PG connection + extensions, not optional
        assert result["summary"] == "2 fixes needed"

    def test_optional_only_failure_still_ready(self, monkeypatch):
        checks = [
            lambda: _fake_check("Python >= 3.10", True),
            lambda: _fake_check("codebase-pipeline (optional)", False, optional=True),
        ]
        monkeypatch.setattr("mcp_server.handlers.check_setup.CHECKS", checks)

        result = asyncio.run(handler())

        assert result["ready"] is True
        assert result["fixes_needed"] == 0
        assert result["summary"] == "ready"

    def test_single_fix_singular_wording(self, monkeypatch):
        checks = [
            lambda: _fake_check("DATABASE_URL", False, fix="export DATABASE_URL=..."),
        ]
        monkeypatch.setattr("mcp_server.handlers.check_setup.CHECKS", checks)

        result = asyncio.run(handler())

        assert result["fixes_needed"] == 1
        assert result["summary"] == "1 fix needed"


class TestCheckSetupHandlerOrder:
    """POST-1: dependency order is preserved exactly, not re-sorted."""

    def test_order_matches_checks_list(self, monkeypatch):
        names = ["Zebra check", "Alpha check", "Middle check"]
        checks = [lambda n=n: _fake_check(n, True) for n in names]
        monkeypatch.setattr("mcp_server.handlers.check_setup.CHECKS", checks)

        result = asyncio.run(handler())

        assert [c["name"] for c in result["checks"]] == names


class TestCheckSetupHandlerNoDuplication:
    """POST-4: real doctor.CHECKS (unmocked) drives the handler — no
    reimplemented check logic, exercises the real Python-version check."""

    def test_uses_real_doctor_checks_python_version_passes(self):
        result = asyncio.run(handler())
        py_check = next(c for c in result["checks"] if c["name"] == "Python >= 3.10")
        assert py_check["ok"] is True

    def test_check_shape(self):
        result = asyncio.run(handler())
        for c in result["checks"]:
            assert set(c.keys()) == {"name", "ok", "optional", "detail", "fix_command"}
            assert isinstance(c["ok"], bool)
            assert isinstance(c["optional"], bool)


class TestCheckSetupSchema:
    """POST-5: facade takes no arguments; schema artifact well-formed."""

    def test_schema_exists(self):
        assert "description" in schema
        assert "inputSchema" in schema

    def test_schema_takes_no_arguments(self):
        assert schema["inputSchema"]["properties"] == {}
        assert schema["inputSchema"]["required"] == []

    def test_schema_additional_properties_false(self):
        assert schema["inputSchema"]["additionalProperties"] is False
