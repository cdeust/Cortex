"""Tests for mcp_server.hooks.session_lifecycle — ported from
session-lifecycle.test.js."""

from __future__ import annotations

import json
from unittest.mock import patch

from mcp_server.hooks.session_lifecycle import (
    process_event,
    _resolve_domain,
    _consolidation_mode,
    _run_consolidation_cycle,
    _spawn_consolidation,
    _tombstone_session_registry,
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
    def test_sessionid_prefers_transcript_stem(
        self, mock_lp, mock_lsl, mock_ssl, mock_sp
    ):
        """Q2 alignment: transcript_path present -> canonical stem wins
        over the raw (potentially resume/clear-diverged) event session_id."""
        process_event(
            {
                "session_id": "raw-diverged-id",
                "transcript_path": "/tmp/projects/x/7374abf5-stem.jsonl",
                "cwd": "/tmp",
            }
        )
        entry = mock_ssl.call_args[0][0]["sessions"][0]
        assert entry["sessionId"] == "7374abf5-stem"

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
    def test_sessionid_falls_back_without_transcript_path(
        self, mock_lp, mock_lsl, mock_ssl, mock_sp
    ):
        """No transcript_path -> documented degradation to raw event
        session_id (same as pre-alignment behavior, e.g. every existing
        fixture in this file that omits transcript_path)."""
        process_event({"session_id": "raw-only-id", "cwd": "/tmp"})
        entry = mock_ssl.call_args[0][0]["sessions"][0]
        assert entry["sessionId"] == "raw-only-id"


class TestConsolidationMode:
    """The turn-gated depth ADR-0497 chose stays the same after the spawn
    moved consolidation into a subprocess (ADR-1082)."""

    def test_a_short_session_is_light(self):
        assert _consolidation_mode(0) == "light"
        assert _consolidation_mode(4) == "light"

    def test_a_medium_session_is_standard(self):
        assert _consolidation_mode(5) == "standard"
        assert _consolidation_mode(19) == "standard"

    def test_a_long_session_is_full(self):
        assert _consolidation_mode(20) == "full"
        assert _consolidation_mode(200) == "full"


class TestSpawnConsolidation:
    """Consolidation moved from an in-process ``asyncio.run`` to a detached
    subprocess so a Codex SessionEnd (1 s soft / 3 s hard timeout) is not
    blocked by a consolidation cycle (ADR-1082)."""

    @patch("mcp_server.hooks.session_lifecycle.subprocess.Popen")
    def test_the_launcher_gets_the_same_mode_the_turn_count_earns(
        self, mock_popen, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path))

        _spawn_consolidation(turn_count=12)

        cmd = mock_popen.call_args[0][0]
        assert cmd[-3:] == [
            "mcp_server.hooks.session_lifecycle",
            "--consolidate",
            "standard",
        ]
        assert mock_popen.call_args.kwargs["start_new_session"] is True
        # Never waited on: a session end that blocked on a "dream" cycle is
        # exactly the bug this spawn replaces.
        mock_popen.return_value.wait.assert_not_called()

    @patch("mcp_server.hooks.session_lifecycle.subprocess.Popen")
    def test_a_spawn_failure_does_not_raise(self, mock_popen, tmp_path, monkeypatch):
        monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path))
        mock_popen.side_effect = OSError("no such file or directory")

        _spawn_consolidation(turn_count=1)  # must not raise

    @patch(
        "mcp_server.hooks.session_lifecycle.subprocess.Popen",
        side_effect=OSError("simulated launcher failure"),
    )
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
    def test_the_session_log_row_exists_even_when_the_launcher_fails(
        self, mock_lp, mock_lsl, mock_ssl, mock_sp, mock_popen, tmp_path, monkeypatch
    ):
        """Pins the order: the log write (``save_session_log``) happens
        before the detached consolidation spawn, so a launcher that raises
        (standing in for one that hangs past Codex's SessionEnd timeout,
        since ``Popen`` itself never blocks on the child) never costs the
        session its log entry."""
        monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path))

        process_event({"session_id": "s-spawn-fails", "cwd": "/tmp"})

        mock_ssl.assert_called_once()
        entry = mock_ssl.call_args[0][0]["sessions"][0]
        assert entry["sessionId"] == "s-spawn-fails"
        mock_popen.assert_called_once()


class TestConsolidateSubprocessDispatch:
    """The process ``_spawn_consolidation`` starts is this module again,
    with ``--consolidate <mode>`` — ``main`` must route to the cycle
    runner instead of trying to read a SessionEnd event from stdin."""

    @patch("mcp_server.hooks.session_lifecycle._run_consolidation_cycle")
    @patch("mcp_server.hooks.session_lifecycle.process_event")
    def test_the_consolidate_flag_skips_stdin_entirely(
        self, mock_pe, mock_cycle, monkeypatch
    ):
        monkeypatch.setattr("sys.argv", ["session_lifecycle", "--consolidate", "full"])

        main()

        mock_cycle.assert_called_once_with("full")
        mock_pe.assert_not_called()

    @staticmethod
    def _closing_run(coro, *, result=None, error=None):
        """Stand in for ``asyncio.run`` without actually scheduling the
        real handler coroutine — closing it avoids the unrelated
        "coroutine was never awaited" warning a bare Mock would leave."""
        coro.close()
        if error is not None:
            raise error
        return result if result is not None else {}

    def test_a_handler_failure_does_not_raise(self):
        with patch(
            "mcp_server.hooks.session_lifecycle.asyncio.run",
            side_effect=lambda coro: self._closing_run(
                coro, error=RuntimeError("simulated handler failure")
            ),
        ):
            _run_consolidation_cycle("light")  # must not raise

    def test_an_unrecognized_mode_degrades_to_light(self):
        with patch(
            "mcp_server.hooks.session_lifecycle.asyncio.run",
            side_effect=self._closing_run,
        ) as mock_run:
            _run_consolidation_cycle("not-a-real-mode")

        mock_run.assert_called_once()


class TestTombstoneSessionRegistry:
    """T2-H2 — SessionEnd write path (user arbitrage Q1)."""

    def test_tombstones_resolved_ancestor(self):
        with (
            patch(
                "mcp_server.infrastructure.session_registry.find_claude_ancestor",
                return_value=4242,
            ),
            patch(
                "mcp_server.infrastructure.session_registry.tombstone"
            ) as mock_tombstone,
        ):
            _tombstone_session_registry()
        mock_tombstone.assert_called_once_with(4242)

    def test_no_ancestor_skips_write(self):
        """No resolvable claude ancestor -> no tombstone call, no crash
        (degrade, never invent — design §1)."""
        with (
            patch(
                "mcp_server.infrastructure.session_registry.find_claude_ancestor",
                return_value=None,
            ),
            patch(
                "mcp_server.infrastructure.session_registry.tombstone"
            ) as mock_tombstone,
        ):
            _tombstone_session_registry()
        mock_tombstone.assert_not_called()

    def test_registry_failure_never_raises(self):
        """Etancheite: must not block the profile update / consolidation
        work that follows it in main()."""
        with patch(
            "mcp_server.infrastructure.session_registry.find_claude_ancestor",
            side_effect=RuntimeError("boom"),
        ):
            _tombstone_session_registry()  # must not raise


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

    @patch("mcp_server.hooks.session_lifecycle.process_event")
    @patch("mcp_server.hooks.session_lifecycle._tombstone_session_registry")
    @patch("sys.stdin")
    def test_tombstone_runs_even_on_tty_with_no_event(
        self, mock_stdin, mock_tomb, mock_pe
    ):
        """The registry tombstone must fire even when there is no usable
        SessionEnd event — the window ending is what matters, not the
        event payload (T2-D6 extension, Q1 arbitrage)."""
        mock_stdin.isatty.return_value = True
        main()
        mock_tomb.assert_called_once_with()
        mock_pe.assert_not_called()


class TestSessionEntryActivity:
    """Issue #591: the payload carries no tools; its transcript does."""

    def _transcript(self, tmp_path):
        records = [
            {"type": "user", "message": {"content": "fix the bug"}},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Read", "input": {}},
                        {"type": "tool_use", "name": "Edit", "input": {}},
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "Bash", "input": {}}]
                },
            },
        ]
        path = tmp_path / "abc123.jsonl"
        path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )
        return str(path)

    def test_entry_is_filled_from_the_transcript(self, tmp_path):
        from mcp_server.hooks.session_lifecycle import _build_session_entry

        entry = _build_session_entry(
            {
                "session_id": "abc123",
                "transcript_path": self._transcript(tmp_path),
                "cwd": "/tmp/project",
            },
            "my-project",
        )

        assert entry["toolsUsed"] == ["Read", "Edit", "Bash"]
        assert entry["turnCount"] == 2

    def test_the_event_wins_when_it_carries_the_fields(self, tmp_path):
        from mcp_server.hooks.session_lifecycle import _build_session_entry

        entry = _build_session_entry(
            {
                "session_id": "abc123",
                "transcript_path": self._transcript(tmp_path),
                "cwd": "/tmp/project",
                "tools_used": ["Write"],
                "turn_count": 9,
            },
            "my-project",
        )

        assert entry["toolsUsed"] == ["Write"]
        assert entry["turnCount"] == 9

    def test_no_transcript_leaves_the_entry_empty(self):
        from mcp_server.hooks.session_lifecycle import _build_session_entry

        entry = _build_session_entry(
            {"session_id": "abc123", "cwd": "/tmp/project"}, "my-project"
        )

        assert entry["toolsUsed"] == []
        assert entry["turnCount"] == 0
