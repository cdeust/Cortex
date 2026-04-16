"""Tests for mcp_server.hooks.session_lifecycle — ported from session-lifecycle.test.js."""

from __future__ import annotations

import json
from unittest.mock import patch

from mcp_server.hooks.session_lifecycle import (
    process_event,
    _resolve_domain,
    main,
    MAX_SESSION_LOG_ENTRIES,
)


def _empty_profiles():
    return {"domains": {}, "version": 2, "updatedAt": None}


def _profiles_with_domain():
    return {
        "domains": {
            "my-project": {
                "projects": ["-Users-dev-my-project"],
                "sessionCount": 5,
                "sessionShape": {
                    "avgDuration": 1000,
                    "avgTurns": 10,
                    "burstRatio": 0.5,
                    "explorationRatio": 0.3,
                },
                "toolPreferences": {},
            }
        },
        "version": 2,
        "updatedAt": None,
    }


def _session_log():
    return {"sessions": []}


class TestResolveDomain:
    def test_matches_existing_domain(self):
        profiles = _profiles_with_domain()
        event = {"cwd": "/Users/dev/my-project", "session_id": "s1"}
        assert _resolve_domain(event, profiles) == "my-project"

    def test_derives_from_label(self):
        profiles = _empty_profiles()
        event = {
            "cwd": "/Users/dev/Documents/Developments/cool-app",
            "session_id": "s1",
        }
        result = _resolve_domain(event, profiles)
        assert result == "cool-app"

    def test_uses_project_field(self):
        profiles = _profiles_with_domain()
        event = {"project": "-Users-dev-my-project", "session_id": "s1"}
        assert _resolve_domain(event, profiles) == "my-project"

    def test_defaults_to_unknown(self):
        profiles = _empty_profiles()
        event = {"session_id": "s1"}
        assert _resolve_domain(event, profiles) == "unknown"

    def test_unknown_when_no_cwd(self):
        profiles = _empty_profiles()
        event = {"session_id": "s1", "cwd": None}
        assert _resolve_domain(event, profiles) == "unknown"


class TestProcessEvent:
    @patch("mcp_server.hooks.session_lifecycle.save_profile")
    @patch("mcp_server.hooks.session_lifecycle.save_session_log")
    @patch(
        "mcp_server.hooks.session_lifecycle.load_session_log",
        return_value=_session_log(),
    )
    @patch(
        "mcp_server.hooks.session_lifecycle.load_profiles",
        return_value=_profiles_with_domain(),
    )
    def test_updates_existing_domain(self, mock_lp, mock_lsl, mock_ssl, mock_sp):
        event = {
            "session_id": "test-123",
            "cwd": "/Users/dev/my-project",
            "duration": 5000,
            "turn_count": 12,
            "tools_used": ["Read", "Edit"],
            "keywords": ["refactor", "cleanup"],
        }
        process_event(event)
        mock_ssl.assert_called_once()
        mock_sp.assert_called_once()
        saved_log = mock_ssl.call_args[0][0]
        assert len(saved_log["sessions"]) == 1
        assert saved_log["sessions"][0]["sessionId"] == "test-123"
        assert saved_log["sessions"][0]["domain"] == "my-project"

    @patch("mcp_server.hooks.session_lifecycle.save_profile")
    @patch("mcp_server.hooks.session_lifecycle.save_session_log")
    @patch(
        "mcp_server.hooks.session_lifecycle.load_session_log",
        return_value=_session_log(),
    )
    @patch(
        "mcp_server.hooks.session_lifecycle.load_profiles",
        return_value=_empty_profiles(),
    )
    def test_logs_only_for_unknown_domain(self, mock_lp, mock_lsl, mock_ssl, mock_sp):
        event = {"session_id": "test-456", "cwd": "/tmp/random"}
        process_event(event)
        mock_ssl.assert_called_once()
        mock_sp.assert_not_called()

    def test_skips_when_no_event(self):
        process_event(None)

    def test_skips_when_no_session_id(self):
        process_event({"cwd": "/tmp"})

    @patch("mcp_server.hooks.session_lifecycle.save_profile")
    @patch("mcp_server.hooks.session_lifecycle.save_session_log")
    @patch("mcp_server.hooks.session_lifecycle.load_session_log")
    @patch(
        "mcp_server.hooks.session_lifecycle.load_profiles",
        return_value=_empty_profiles(),
    )
    def test_caps_session_log(self, mock_lp, mock_lsl, mock_ssl, mock_sp):
        existing = {
            "sessions": [{"sessionId": f"s{i}"} for i in range(MAX_SESSION_LOG_ENTRIES)]
        }
        mock_lsl.return_value = existing
        process_event({"session_id": "overflow", "cwd": "/tmp"})
        saved_log = mock_ssl.call_args[0][0]
        assert len(saved_log["sessions"]) == MAX_SESSION_LOG_ENTRIES
        assert saved_log["sessions"][-1]["sessionId"] == "overflow"

    @patch("mcp_server.hooks.session_lifecycle.save_profile")
    @patch("mcp_server.hooks.session_lifecycle.save_session_log")
    @patch(
        "mcp_server.hooks.session_lifecycle.load_session_log",
        return_value=_session_log(),
    )
    @patch(
        "mcp_server.hooks.session_lifecycle.load_profiles",
        return_value=_empty_profiles(),
    )
    def test_category_defaults_to_general(self, mock_lp, mock_lsl, mock_ssl, mock_sp):
        process_event({"session_id": "s1", "cwd": "/tmp"})
        saved_log = mock_ssl.call_args[0][0]
        assert saved_log["sessions"][0]["category"] == "general"

    @patch("mcp_server.hooks.session_lifecycle.save_profile")
    @patch("mcp_server.hooks.session_lifecycle.save_session_log")
    @patch(
        "mcp_server.hooks.session_lifecycle.load_session_log",
        return_value=_session_log(),
    )
    @patch(
        "mcp_server.hooks.session_lifecycle.load_profiles",
        return_value=_empty_profiles(),
    )
    def test_categorizes_from_keywords(self, mock_lp, mock_lsl, mock_ssl, mock_sp):
        process_event({"session_id": "s2", "keywords": ["fix", "bug", "crash"]})
        saved_log = mock_ssl.call_args[0][0]
        assert saved_log["sessions"][0]["category"] == "bug-fix"

    @patch("mcp_server.hooks.session_lifecycle.save_profile")
    @patch("mcp_server.hooks.session_lifecycle.save_session_log")
    @patch(
        "mcp_server.hooks.session_lifecycle.load_session_log",
        return_value=_session_log(),
    )
    @patch(
        "mcp_server.hooks.session_lifecycle.load_profiles",
        return_value=_empty_profiles(),
    )
    def test_session_entry_fields(self, mock_lp, mock_lsl, mock_ssl, mock_sp):
        process_event(
            {
                "session_id": "s3",
                "cwd": "/Users/dev/test-proj",
                "duration": 3000,
                "turn_count": 7,
                "tools_used": ["Bash"],
                "keywords": ["deploy"],
            }
        )
        entry = mock_ssl.call_args[0][0]["sessions"][0]
        assert entry["sessionId"] == "s3"
        assert entry["cwd"] == "/Users/dev/test-proj"
        assert entry["duration"] == 3000
        assert entry["turnCount"] == 7
        assert entry["toolsUsed"] == ["Bash"]
        assert entry["entryKeywords"] == ["deploy"]
        assert "timestamp" in entry


class TestMain:
    @patch("mcp_server.hooks.session_lifecycle.process_event")
    @patch("sys.stdin")
    def test_reads_from_stdin(self, mock_stdin, mock_pe):
        mock_stdin.isatty.return_value = False
        mock_stdin.read.return_value = json.dumps({"session_id": "x"})
        main()
        mock_pe.assert_called_once_with({"session_id": "x"})

    @patch("mcp_server.hooks.session_lifecycle.process_event")
    @patch("sys.stdin")
    def test_exits_on_tty(self, mock_stdin, mock_pe):
        mock_stdin.isatty.return_value = True
        main()
        mock_pe.assert_not_called()

    @patch("mcp_server.hooks.session_lifecycle.process_event")
    @patch("sys.stdin")
    def test_handles_invalid_json(self, mock_stdin, mock_pe):
        mock_stdin.isatty.return_value = False
        mock_stdin.read.return_value = "not json{"
        main()
        mock_pe.assert_not_called()

    @patch("mcp_server.hooks.session_lifecycle.process_event")
    @patch("sys.stdin")
    def test_handles_empty_stdin(self, mock_stdin, mock_pe):
        mock_stdin.isatty.return_value = False
        mock_stdin.read.return_value = ""
        main()
        mock_pe.assert_not_called()
