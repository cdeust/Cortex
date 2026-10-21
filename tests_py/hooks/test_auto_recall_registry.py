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
    def test_writes_transcript_stem_on_every_prompt(self):
        event = {"transcript_path": "/home/u/.claude/projects/p/xyz-9.jsonl"}
        with patch(
            "mcp_server.infrastructure.session_registry.write_session"
        ) as mock_write:
            _refresh_session_registry(event)
        mock_write.assert_called_once_with("xyz-9")

    def test_missing_transcript_path_writes_none(self):
        with patch(
            "mcp_server.infrastructure.session_registry.write_session"
        ) as mock_write:
            _refresh_session_registry({})
        mock_write.assert_called_once_with(None)

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
            patch("mcp_server.hooks.auto_recall._store") as mock_connect,
        ):
            try:
                process_event(event)
            except SystemExit:
                pass
        mock_refresh.assert_called_once_with(event)
        mock_connect.assert_not_called()
