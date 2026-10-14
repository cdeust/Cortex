"""Tests for the pipeline_impact_bump PostToolUse hook.

Covers:
  * Tool name gating (only Edit/Write/MultiEdit)
  * Cooldown deduplication
  * Pipeline call + symbol extraction
  * Heat bump through the configured store (a real SQLite store here, #750)
  * Project root from the event, never the launcher's cwd (#750)

Source: docs/program/phase-5-pool-admission-design.md pipeline-3;
user directive "codebase analysis feeding the memory and wiki".
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp_server.hooks import pipeline_impact_bump as hook
from mcp_server.infrastructure import memory_store
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


@pytest.fixture(autouse=True)
def _clean_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "_COOLDOWN_FILE", tmp_path / "cooldown.json")
    monkeypatch.setenv("CLAUDE_PROJECT_ROOT", str(tmp_path))
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
        # First call primes the cooldown. Patch the async probe to a plain
        # MagicMock so the call site builds no un-awaited coroutine (the
        # patched asyncio.run supplies the result).
        with patch.object(hook, "_pipeline_detect_changes", new=MagicMock()):
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


@pytest.fixture()
def sqlite_store(tmp_path, monkeypatch):
    """A real SQLite store served as the process-wide shared store."""
    store = SqliteMemoryStore(str(tmp_path / "memory.db"))
    monkeypatch.setattr(memory_store, "get_shared_store", lambda *a, **k: store)
    yield store
    store.close()


class TestHeatBump:
    def test_no_symbols_returns_zero(self):
        assert hook._bump_heat_for_symbols([]) == 0

    def test_bumps_mentioning_memories_on_sqlite(self, sqlite_store):
        hit = sqlite_store.insert_memory(
            {"content": "handle_tool_call parses the request", "heat": 0.5}
        )
        miss = sqlite_store.insert_memory(
            {"content": "unrelated release notes", "heat": 0.5}
        )
        hot = sqlite_store.insert_memory(
            {"content": "handle_tool_call is hot already", "heat": 1.0}
        )
        assert hook._bump_heat_for_symbols(["handle_tool_call"]) == 1
        assert sqlite_store.get_memory(hit)["heat_base"] == pytest.approx(
            0.5 + hook._IMPACT_BOOST
        )
        assert sqlite_store.get_memory(miss)["heat_base"] == pytest.approx(0.5)
        assert sqlite_store.get_memory(hot)["heat_base"] == pytest.approx(1.0)

    def test_a_memory_matching_two_symbols_is_bumped_once(self, sqlite_store):
        both = sqlite_store.insert_memory(
            {"content": "parse_args feeds handle_tool_call", "heat": 0.5}
        )
        assert hook._bump_heat_for_symbols(["parse_args", "handle_tool_call"]) == 1
        assert sqlite_store.get_memory(both)["heat_base"] == pytest.approx(
            0.5 + hook._IMPACT_BOOST
        )

    def test_saturated_memories_do_not_starve_the_bump(self, sqlite_store):
        """More saturated (heat 1.0) mentions than the query limit must not
        hide the one memory the bump can still raise: the heat filter runs
        in the store query, before its LIMIT (the pre-#750 UPDATE filtered
        ``heat_base < 1.0`` in its WHERE)."""
        for i in range(hook._MAX_BUMPS + 1):
            sqlite_store.insert_memory(
                {"content": f"handle_tool_call saturated note {i}", "heat": 1.0}
            )
        cold = sqlite_store.insert_memory(
            {"content": "handle_tool_call cold note", "heat": 0.3}
        )
        assert hook._bump_heat_for_symbols(["handle_tool_call"]) == 1
        assert sqlite_store.get_memory(cold)["heat_base"] == pytest.approx(
            0.3 + hook._IMPACT_BOOST
        )

    @pytest.mark.parametrize("flag", ["is_stale", "is_benchmark"])
    def test_excluded_memories_do_not_starve_the_bump(self, sqlite_store, flag):
        """Stale or benchmark mentions above the query limit must not hide the
        valid one: the pre-#750 UPDATE excluded both in its WHERE clause."""
        for i in range(hook._MAX_BUMPS + 1):
            mid = sqlite_store.insert_memory(
                {
                    "content": f"handle_tool_call {flag} note {i}",
                    "heat": 0.9,
                    "is_benchmark": flag == "is_benchmark",
                }
            )
            if flag == "is_stale":
                sqlite_store.mark_memory_stale(mid)
        valid = sqlite_store.insert_memory(
            {"content": "handle_tool_call valid note", "heat": 0.3}
        )
        assert hook._bump_heat_for_symbols(["handle_tool_call"]) == 1
        assert sqlite_store.get_memory(valid)["heat_base"] == pytest.approx(
            0.3 + hook._IMPACT_BOOST
        )


class TestProjectRoot:
    """#750: the project is the event's, never the launcher's plugin-root cwd."""

    def _run(self, event):
        with patch.object(hook, "_pipeline_detect_changes", new=MagicMock()) as pipe:
            with patch("asyncio.run", return_value=[]):
                hook.process_event(event)
        return pipe

    def test_event_cwd_is_the_project(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
        plugin = tmp_path / "plugin"
        plugin.mkdir()
        monkeypatch.chdir(plugin)
        pipe = self._run(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/proj/a.py"},
                "cwd": "/proj",
            }
        )
        pipe.assert_called_once_with("/proj", "/proj/a.py")

    def test_unresolved_project_calls_no_pipeline(self, monkeypatch, capsys):
        monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
        pipe = self._run({"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}})
        pipe.assert_not_called()
        assert "project root unresolved" in capsys.readouterr().err


class TestProcessEventIntegration:
    def test_happy_path_calls_bump(self):
        with patch.object(hook, "_pipeline_detect_changes", new=MagicMock()):
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
        with patch.object(hook, "_pipeline_detect_changes", new=MagicMock()):
            with patch("asyncio.run", return_value=[]):
                with patch.object(hook, "_bump_heat_for_symbols") as mock_bump:
                    hook.process_event(
                        {
                            "tool_name": "Edit",
                            "tool_input": {"file_path": "/tmp/y.py"},
                        }
                    )
        mock_bump.assert_not_called()
