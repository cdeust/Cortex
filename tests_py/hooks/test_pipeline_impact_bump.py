"""Tests for the pipeline_impact_bump PostToolUse hook.

Covers:
  * Tool name gating (only Edit/Write/MultiEdit)
  * Cooldown deduplication
  * Pipeline call + symbol extraction
  * Heat-bump SQL assembly (with/without symbols)

Source: docs/program/phase-5-pool-admission-design.md pipeline-3;
user directive "codebase analysis feeding the memory and wiki".
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp_server.hooks import pipeline_impact_bump as hook


@pytest.fixture(autouse=True)
def _clean_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "_COOLDOWN_FILE", tmp_path / "cooldown.json")
    yield


class TestToolNameGating:
    def test_non_file_tool_returns_early(self):
        with patch.object(hook, "_pipeline_detect_changes") as mock_pipe:
            hook.process_event({"tool_name": "Bash"})
        mock_pipe.assert_not_called()

    def test_missing_file_path_returns_early(self):
        with patch.object(hook, "_pipeline_detect_changes") as mock_pipe:
            hook.process_event({"tool_name": "Edit", "tool_input": {}})
        mock_pipe.assert_not_called()

    @pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
    def test_file_tools_probe_pipeline(self, tool):
        with patch.object(
            hook,
            "_pipeline_detect_changes",
            new=MagicMock(),
        ) as _:
            # Using asyncio.run internally — patch the sync entry
            with patch("asyncio.run", return_value=[]):
                hook.process_event(
                    {"tool_name": tool, "tool_input": {"file_path": "/a/b.py"}}
                )


class TestCooldown:
    def test_cooldown_skips_second_call(self):
        # First call primes the cooldown.
        with patch("asyncio.run", return_value=["sym_a"]):
            with patch.object(hook, "_bump_heat_for_symbols", return_value=3):
                hook.process_event(
                    {
                        "tool_name": "Edit",
                        "tool_input": {"file_path": "/a/b.py"},
                    }
                )

        # Second call within cooldown should NOT invoke pipeline.
        with patch("asyncio.run") as mock_run:
            hook.process_event(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/a/b.py"},
                }
            )
            mock_run.assert_not_called()


class TestHeatBump:
    def test_no_symbols_returns_zero(self):
        assert hook._bump_heat_for_symbols([]) == 0

    def test_sql_query_shape(self):
        """Assembles a SQL UPDATE with one ILIKE clause per symbol and
        heat_base_set_at refresh (A3 canonical writer path)."""
        # Grab the SQL without running a real DB — fake psycopg.connect
        # and verify the call args.
        fake_conn = MagicMock()
        fake_conn.execute.return_value = MagicMock(rowcount=5)
        with patch.object(hook, "psycopg", create=True, MagicMock=MagicMock):
            with patch("psycopg.connect", return_value=fake_conn):
                with patch.dict("os.environ", {"DATABASE_URL": "postgresql://x/y"}):
                    count = hook._bump_heat_for_symbols(["foo::bar", "baz::qux"])
        assert count == 5
        # Assert SQL includes A3 columns and uses ILIKE for each symbol
        call_args = fake_conn.execute.call_args
        sql = call_args[0][0]
        assert "heat_base = LEAST(heat_base + %s, 1.0)" in sql
        assert "heat_base_set_at = NOW()" in sql
        assert sql.count("content ILIKE %s") == 2


class TestProcessEventIntegration:
    def test_happy_path_calls_bump(self):
        with patch("asyncio.run", return_value=["my_symbol"]):
            with patch.object(
                hook, "_bump_heat_for_symbols", return_value=4
            ) as mock_bump:
                hook.process_event(
                    {
                        "tool_name": "Write",
                        "tool_input": {"file_path": "/tmp/x.rs"},
                    }
                )
        mock_bump.assert_called_once_with(["my_symbol"])

    def test_empty_symbols_skips_bump(self):
        with patch("asyncio.run", return_value=[]):
            with patch.object(hook, "_bump_heat_for_symbols") as mock_bump:
                hook.process_event(
                    {
                        "tool_name": "Edit",
                        "tool_input": {"file_path": "/tmp/y.py"},
                    }
                )
        mock_bump.assert_not_called()
