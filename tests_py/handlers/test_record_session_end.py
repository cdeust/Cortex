"""Tests for mcp_server.handlers.record_session_end — ported from
record-session-end.test.js."""

import asyncio
import time
from unittest.mock import patch

from mcp_server.handlers.record_session_end import handler


def _mock_io():
    """Mock all filesystem I/O in the handler (profiles + session log)."""
    return (
        patch(
            "mcp_server.handlers.record_session_end.load_profiles",
            return_value={"domains": {}},
        ),
        patch(
            "mcp_server.handlers.record_session_end.load_session_log",
            return_value={"sessions": []},
        ),
        patch("mcp_server.handlers.record_session_end.save_session_log"),
        patch("mcp_server.handlers.record_session_end.save_profile"),
    )


class TestRecordSessionEndHandler:
    def test_returns_domain_and_profile_updated(self):
        p1, p2, p3, p4 = _mock_io()
        with p1, p2, p3, p4:
            result = asyncio.run(
                handler(
                    {
                        "session_id": f"test-session-{int(time.time() * 1000)}",
                    }
                )
            )
            assert result is not None
            assert "domain" in result
            assert isinstance(result["domain"], str)
            assert "profileUpdated" in result
            assert isinstance(result["profileUpdated"], bool)

    def test_returns_confidence(self):
        p1, p2, p3, p4 = _mock_io()
        with p1, p2, p3, p4:
            result = asyncio.run(
                handler(
                    {
                        "session_id": f"test-session-conf-{int(time.time() * 1000)}",
                    }
                )
            )
            assert "confidence" in result
            assert isinstance(result["confidence"], (int, float))

    def test_accepts_optional_fields(self):
        p1, p2, p3, p4 = _mock_io()
        with p1, p2, p3, p4:
            result = asyncio.run(
                handler(
                    {
                        "session_id": f"test-session-full-{int(time.time() * 1000)}",
                        "tools_used": ["Read", "Edit"],
                        "duration": 60000,
                        "turn_count": 10,
                        "keywords": ["refactor", "testing"],
                        "cwd": "/tmp/test",
                    }
                )
            )
            assert result is not None
            assert "domain" in result

    def test_returns_new_patterns_array(self):
        p1, p2, p3, p4 = _mock_io()
        with p1, p2, p3, p4:
            result = asyncio.run(
                handler(
                    {
                        "session_id": "test-session-patterns-"
                        f"{int(time.time() * 1000)}",
                    }
                )
            )
            assert "newPatterns" in result
            assert isinstance(result["newPatterns"], list)

    def test_defaults_to_unknown_domain(self):
        """When no domain, cwd, or project provided, defaults to 'unknown'."""
        with (
            patch(
                "mcp_server.handlers.record_session_end.load_profiles",
                return_value={"domains": {}},
            ),
            patch(
                "mcp_server.handlers.record_session_end.load_session_log",
                return_value={"sessions": []},
            ),
            patch("mcp_server.handlers.record_session_end.save_session_log"),
        ):
            result = asyncio.run(
                handler(
                    {
                        "session_id": "test-unknown-domain",
                    }
                )
            )
        assert result["domain"] == "unknown"

    def test_detects_domain_from_project_in_profiles(self):
        profiles = {
            "domains": {
                "my-domain": {
                    "projects": ["proj-123"],
                    "confidence": 0.5,
                }
            }
        }
        with (
            patch(
                "mcp_server.handlers.record_session_end.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.record_session_end.load_session_log",
                return_value={"sessions": []},
            ),
            patch("mcp_server.handlers.record_session_end.save_session_log"),
            patch("mcp_server.handlers.record_session_end.apply_session_update"),
            patch("mcp_server.handlers.record_session_end.save_profile"),
        ):
            result = asyncio.run(
                handler(
                    {
                        "session_id": "test-detect-domain",
                        "project": "proj-123",
                    }
                )
            )
        assert result["domain"] == "my-domain"
        assert result["profileUpdated"] is True

    def test_detects_domain_despite_windows_casing_mismatch(self):
        # issue #95: profile keeps original filesystem casing
        # ('C--Work-MyRepo') while cwd_to_project_id derives a lowercase
        # slug for Windows-style paths ('c--work-myrepo'). Before the fix,
        # remember(directory=...) -> detect_domain -> this resolver stored
        # domain "" (fell through to the label-derived fallback, which for
        # an unrelated cwd is not "unknown" but also not "my-domain").
        profiles = {
            "domains": {
                "my-domain": {
                    "projects": ["C--Work-MyRepo"],
                    "confidence": 0.5,
                }
            }
        }
        with (
            patch(
                "mcp_server.handlers.record_session_end.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.record_session_end.load_session_log",
                return_value={"sessions": []},
            ),
            patch("mcp_server.handlers.record_session_end.save_session_log"),
            patch("mcp_server.handlers.record_session_end.apply_session_update"),
            patch("mcp_server.handlers.record_session_end.save_profile"),
        ):
            result = asyncio.run(
                handler(
                    {
                        "session_id": "test-windows-casing",
                        "cwd": "C:\\Work\\MyRepo",
                    }
                )
            )
        assert result["domain"] == "my-domain"
        assert result["profileUpdated"] is True

    def test_categorizes_keywords(self):
        with (
            patch(
                "mcp_server.handlers.record_session_end.load_profiles",
                return_value={"domains": {}},
            ),
            patch(
                "mcp_server.handlers.record_session_end.load_session_log",
                return_value={"sessions": []},
            ),
            patch(
                "mcp_server.handlers.record_session_end.save_session_log"
            ) as mock_save,
        ):
            asyncio.run(
                handler(
                    {
                        "session_id": "test-categorize",
                        "keywords": ["fix", "bug", "error"],
                    }
                )
            )
        # Session log was saved — check that session entry was appended
        mock_save.assert_called_once()
        saved_log = mock_save.call_args[0][0]
        session_entry = saved_log["sessions"][-1]
        assert session_entry["category"] == "bug-fix"

    def test_session_log_rolling_limit(self):
        """Log should be capped at 1000 entries."""
        existing_sessions = [{"sessionId": f"old-{i}"} for i in range(1000)]
        with (
            patch(
                "mcp_server.handlers.record_session_end.load_profiles",
                return_value={"domains": {}},
            ),
            patch(
                "mcp_server.handlers.record_session_end.load_session_log",
                return_value={"sessions": existing_sessions},
            ),
            patch(
                "mcp_server.handlers.record_session_end.save_session_log"
            ) as mock_save,
        ):
            asyncio.run(
                handler(
                    {
                        "session_id": "test-rolling",
                    }
                )
            )
        saved_log = mock_save.call_args[0][0]
        assert len(saved_log["sessions"]) == 1000

    def test_lesson_candidates_stored_key_present(self):
        """M-D6 (7.6): the response always carries lessonCandidatesStored."""
        p1, p2, p3, p4 = _mock_io()
        with p1, p2, p3, p4:
            result = asyncio.run(
                handler(
                    {
                        "session_id": f"test-lesson-key-{int(time.time() * 1000)}",
                    }
                )
            )
        assert "lessonCandidatesStored" in result
        assert isinstance(result["lessonCandidatesStored"], int)

    def test_persists_top_suggestion_as_lesson_candidate_memory(self):
        """M-D6 (7.6): a non-empty top_suggestion becomes its own durable
        memory (source='self-critique', tags include 'lesson-candidate') —
        previously it was computed and returned, never stored (design
        §M-D6: 'top_suggestions calculées puis perdues')."""
        p1, p2, p3, p4 = _mock_io()
        session_id = f"test-lesson-persist-{int(time.time() * 1000)}"
        with p1, p2, p3, p4:
            result = asyncio.run(
                handler(
                    {
                        "session_id": session_id,
                        # No tools_used -> analyze_tool_usage guarantees a
                        # non-empty suggestion ("No tools were used...").
                    }
                )
            )

        assert result["critique"]["top_suggestions"], (
            "fixture assumption: empty tools_used always yields >=1 suggestion"
        )
        assert result["lessonCandidatesStored"] >= 1

        from mcp_server.infrastructure.memory_store import get_shared_store

        store = get_shared_store()
        recent = store.get_recent_memories(limit=50)
        matches = [
            m
            for m in recent
            if session_id in m.get("content", "")
            and "lesson-candidate" in (m.get("tags") or [])
        ]
        assert matches, "expected a lesson-candidate memory tagged with the session id"
        assert matches[0].get("source") == "self-critique"

    def test_profile_not_updated_when_domain_not_in_profiles(self):
        with (
            patch(
                "mcp_server.handlers.record_session_end.load_profiles",
                return_value={"domains": {}},
            ),
            patch(
                "mcp_server.handlers.record_session_end.load_session_log",
                return_value={"sessions": []},
            ),
            patch("mcp_server.handlers.record_session_end.save_session_log"),
        ):
            result = asyncio.run(
                handler(
                    {
                        "session_id": "test-no-update",
                        "domain": "nonexistent",
                    }
                )
            )
        assert result["profileUpdated"] is False
        assert result["confidence"] == 0
