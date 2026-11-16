"""Unit tests for auto_recall.py's session-registry write wiring (T2-H2).

Deliberately separate from ``test_auto_recall.py``: that file's
module-level ``pytestmark`` skips everything when PostgreSQL is
unreachable, but the registry refresh wiring needs no database at all
— it must run in CI regardless of PG availability.
"""

from __future__ import annotations

from unittest.mock import patch

from mcp_server.hooks.auto_recall import _refresh_session_registry, process_event


class TestRefreshSessionRegistry:
    def test_writes_transcript_stem_on_every_prompt(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
        event = {"transcript_path": "/home/u/.claude/projects/p/xyz-9.jsonl"}
        with patch(
            "mcp_server.infrastructure.session_registry.write_session"
        ) as mock_write:
            _refresh_session_registry(event)
        mock_write.assert_called_once_with("xyz-9", project_root=None)

    def test_missing_transcript_path_writes_none(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
        with patch(
            "mcp_server.infrastructure.session_registry.write_session"
        ) as mock_write:
            _refresh_session_registry({})
        mock_write.assert_called_once_with(None, project_root=None)

    def test_writes_the_event_project_root(self, monkeypatch):
        """Issue #711: a prompt rewrite keeps the window's project, so the
        cache eviction still sees the graph of this window as in use."""
        monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
        event = {"transcript_path": "/x/s-1.jsonl", "cwd": "/work/proj"}
        with patch(
            "mcp_server.infrastructure.session_registry.write_session"
        ) as mock_write:
            _refresh_session_registry(event)
        mock_write.assert_called_once_with("s-1", project_root="/work/proj")

    def test_registry_failure_never_raises(self):
        """Etancheite: a registry hiccup must never block recall injection."""
        event = {"transcript_path": "/x/y.jsonl"}
        with patch(
            "mcp_server.infrastructure.session_registry.write_session",
            side_effect=RuntimeError("boom"),
        ):
            _refresh_session_registry(event)  # must not raise


class TestProcessEventCallsRegistryRefresh:
    def test_refresh_called_even_when_recall_is_skipped(self):
        """The registry must refresh every prompt, independent of whether
        THIS prompt's query is skipped (T2-D6: "a chaque prompt")."""
        event = {"prompt": "ok"}  # matches _SKIP_PATTERNS -> early sys.exit(0)
        with (
            patch(
                "mcp_server.hooks.auto_recall._refresh_session_registry"
            ) as mock_refresh,
            patch("mcp_server.hooks.auto_recall._connect") as mock_connect,
        ):
            try:
                process_event(event)
            except SystemExit:
                pass
        mock_refresh.assert_called_once_with(event)
        mock_connect.assert_not_called()
