"""Tests for mcp_server.handlers.record_session_end — ported from record-session-end.test.js."""

import asyncio
import os
import tempfile
import time
from unittest.mock import patch

from mcp_server.handlers.record_session_end import handler


def _patch_memory_env(tmp_dir: str):
    """Patch environment to use temp directory for memory DB."""
    db_path = os.path.join(tmp_dir, "test.db")
    return patch.dict(os.environ, {"JARVIS_MEMORY_DB_PATH": db_path})


def _reset_singletons():
    """Reset handler singletons between tests so they pick up the new DB path."""
    import mcp_server.handlers.remember as rem_mod

    rem_mod._store = None
    rem_mod._embeddings = None
    import mcp_server.handlers.record_session_end as rse_mod

    rse_mod._memory_available = None
    from mcp_server.infrastructure.memory_config import get_memory_settings

    get_memory_settings.cache_clear()


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
        patch("mcp_server.handlers.record_session_end.save_profiles"),
    )


class TestRecordSessionEndHandler:
    def test_returns_domain_and_profile_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2, p3, p4 = _mock_io()
            with _patch_memory_env(tmp), p1, p2, p3, p4:
                _reset_singletons()
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
                _reset_singletons()

    def test_returns_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2, p3, p4 = _mock_io()
            with _patch_memory_env(tmp), p1, p2, p3, p4:
                _reset_singletons()
                result = asyncio.run(
                    handler(
                        {
                            "session_id": f"test-session-conf-{int(time.time() * 1000)}",
                        }
                    )
                )
                assert "confidence" in result
                assert isinstance(result["confidence"], (int, float))
                _reset_singletons()

    def test_accepts_optional_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2, p3, p4 = _mock_io()
            with _patch_memory_env(tmp), p1, p2, p3, p4:
                _reset_singletons()
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
                _reset_singletons()

    def test_returns_new_patterns_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2, p3, p4 = _mock_io()
            with _patch_memory_env(tmp), p1, p2, p3, p4:
                _reset_singletons()
                result = asyncio.run(
                    handler(
                        {
                            "session_id": f"test-session-patterns-{int(time.time() * 1000)}",
                        }
                    )
                )
                assert "newPatterns" in result
                assert isinstance(result["newPatterns"], list)
                _reset_singletons()

    def test_defaults_to_unknown_domain(self):
        """When no domain, cwd, or project provided, defaults to 'unknown'."""
        with tempfile.TemporaryDirectory() as tmp:
            with (
                _patch_memory_env(tmp),
                patch(
                    "mcp_server.handlers.record_session_end.load_profiles",
                    return_value={"domains": {}},
                ),
                patch(
                    "mcp_server.handlers.record_session_end.load_session_log",
                    return_value={"sessions": []},
                ),
                patch("mcp_server.handlers.record_session_end.save_session_log"),
                patch("mcp_server.handlers.record_session_end.save_profiles"),
            ):
                _reset_singletons()
                result = asyncio.run(
                    handler(
                        {
                            "session_id": "test-unknown-domain",
                        }
                    )
                )
                _reset_singletons()
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
        with tempfile.TemporaryDirectory() as tmp:
            with (
                _patch_memory_env(tmp),
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
                patch("mcp_server.handlers.record_session_end.save_profiles"),
            ):
                _reset_singletons()
                result = asyncio.run(
                    handler(
                        {
                            "session_id": "test-detect-domain",
                            "project": "proj-123",
                        }
                    )
                )
                _reset_singletons()
            assert result["domain"] == "my-domain"
            assert result["profileUpdated"] is True

    def test_categorizes_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                _patch_memory_env(tmp),
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
                _reset_singletons()
                asyncio.run(
                    handler(
                        {
                            "session_id": "test-categorize",
                            "keywords": ["fix", "bug", "error"],
                        }
                    )
                )
                _reset_singletons()
            # Session log was saved — check that session entry was appended
            mock_save.assert_called_once()
            saved_log = mock_save.call_args[0][0]
            session_entry = saved_log["sessions"][-1]
            assert session_entry["category"] == "bug-fix"

    def test_session_log_rolling_limit(self):
        """Log should be capped at 1000 entries."""
        existing_sessions = [{"sessionId": f"old-{i}"} for i in range(1000)]
        with tempfile.TemporaryDirectory() as tmp:
            with (
                _patch_memory_env(tmp),
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
                _reset_singletons()
                asyncio.run(
                    handler(
                        {
                            "session_id": "test-rolling",
                        }
                    )
                )
                _reset_singletons()
            saved_log = mock_save.call_args[0][0]
            assert len(saved_log["sessions"]) == 1000

    def test_profile_not_updated_when_domain_not_in_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                _patch_memory_env(tmp),
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
                _reset_singletons()
                result = asyncio.run(
                    handler(
                        {
                            "session_id": "test-no-update",
                            "domain": "nonexistent",
                        }
                    )
                )
                _reset_singletons()
            assert result["profileUpdated"] is False
            assert result["confidence"] == 0
