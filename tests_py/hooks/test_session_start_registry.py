"""Unit tests for session_start.py's session-registry write wiring (T2-H2).

Covers T2-D6 (write + purge, best-effort behind the headless guard) and
the étanchéité (leak-proofing) requirement: a registry failure must
never raise out of ``_refresh_session_registry`` and must never touch
the banner it's called alongside.
"""

from __future__ import annotations

from unittest.mock import patch

from mcp_server.hooks.session_start import _refresh_session_registry


class TestRefreshSessionRegistry:
    def test_writes_transcript_stem_and_purges(self):
        event = {"transcript_path": "/home/u/.claude/projects/p/abc-123.jsonl"}
        with (
            patch(
                "mcp_server.infrastructure.session_registry.write_session"
            ) as mock_write,
            patch(
                "mcp_server.infrastructure.session_registry.purge_dead_entries"
            ) as mock_purge,
        ):
            _refresh_session_registry(event)

        mock_write.assert_called_once_with("abc-123")
        mock_purge.assert_called_once_with()

    def test_missing_transcript_path_writes_none(self):
        """No transcript_path (manual/tty run) → session_id=None is a
        legitimate tombstone-shaped write, never a raised exception."""
        with (
            patch(
                "mcp_server.infrastructure.session_registry.write_session"
            ) as mock_write,
            patch("mcp_server.infrastructure.session_registry.purge_dead_entries"),
        ):
            _refresh_session_registry({})

        mock_write.assert_called_once_with(None)

    def test_registry_failure_never_raises(self):
        """Etancheite: an exception inside write_session must not escape
        _refresh_session_registry — the SessionStart banner is critical
        and must never be interrupted by a registry hiccup."""
        event = {"transcript_path": "/x/y/z.jsonl"}
        with patch(
            "mcp_server.infrastructure.session_registry.write_session",
            side_effect=RuntimeError("disk full"),
        ):
            _refresh_session_registry(event)  # must not raise

    def test_purge_failure_never_raises(self):
        event = {"transcript_path": "/x/y/z.jsonl"}
        with (
            patch("mcp_server.infrastructure.session_registry.write_session"),
            patch(
                "mcp_server.infrastructure.session_registry.purge_dead_entries",
                side_effect=OSError("permission denied"),
            ),
        ):
            _refresh_session_registry(event)  # must not raise


class TestMainCallsRegistryRefresh:
    def test_main_invokes_refresh_before_pg_work(self):
        """_refresh_session_registry must run even on the cold-start /
        no-PG early-return branches (T2-D9 case 3 rationale)."""
        with (
            patch("mcp_server.hooks.session_start._read_event", return_value={}),
            patch("mcp_server.hooks.session_start._auto_wire_pipeline"),
            patch("mcp_server.hooks.session_start._maybe_background_reanalyze"),
            patch("mcp_server.hooks.session_start._maybe_background_consolidate"),
            patch(
                "mcp_server.hooks.session_start._refresh_session_registry"
            ) as mock_refresh,
            patch("mcp_server.hooks.session_start._pg_store", return_value=None),
            patch("mcp_server.hooks.session_start._try_setup_db", return_value=None),
            patch(
                "mcp_server.hooks.session_start._build_cold_start_message",
                return_value="",
            ),
        ):
            from mcp_server.hooks.session_start import main

            main()

        mock_refresh.assert_called_once_with({})
