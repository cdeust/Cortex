"""Tests for mcp_server.handlers.rebuild_profiles — ported from rebuild-profiles.test.js."""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from mcp_server.handlers.rebuild_profiles import handler


class TestRebuildProfilesHandler:
    def test_returns_domains_array_with_force(self):
        result = asyncio.run(handler({"force": True}))
        assert result is not None
        assert "domains" in result
        assert isinstance(result["domains"], list)

    def test_includes_total_sessions_and_memories(self):
        result = asyncio.run(handler({"force": True}))
        assert "totalSessions" in result
        assert "totalMemories" in result
        assert isinstance(result["totalSessions"], (int, float))
        assert isinstance(result["totalMemories"], (int, float))

    def test_includes_duration_metric(self):
        result = asyncio.run(handler({"force": True}))
        assert "duration" in result
        assert isinstance(result["duration"], (int, float))
        assert result["duration"] >= 0

    def test_default_args_is_none(self):
        """handler(None) should work same as handler({})."""
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler(None))
        assert "domains" in result


class TestRebuildSmartCaching:
    def test_skips_rebuild_when_recent(self):
        recent_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        profiles = {
            "updatedAt": recent_time,
            "domains": {"test-domain": {"label": "Test"}},
        }
        with patch(
            "mcp_server.handlers.rebuild_profiles.load_profiles", return_value=profiles
        ):
            result = asyncio.run(handler({"force": False}))
        assert result.get("skipped") is True
        assert "less than 1 hour" in result["reason"]
        assert "test-domain" in result["domains"]

    def test_does_not_skip_when_old(self):
        old_time = (
            (datetime.now(timezone.utc) - timedelta(hours=2))
            .isoformat()
            .replace("+00:00", "Z")
        )
        profiles = {
            "updatedAt": old_time,
            "domains": {"old-domain": {"label": "Old"}},
        }
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {"rebuilt": {}}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler({"force": False}))
        assert "skipped" not in result
        assert "domains" in result

    def test_force_overrides_cache(self):
        recent_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        profiles = {
            "updatedAt": recent_time,
            "domains": {"test-domain": {"label": "Test"}},
        }
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler({"force": True}))
        assert "skipped" not in result

    def test_does_not_skip_when_no_domains(self):
        recent_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        profiles = {
            "updatedAt": recent_time,
            "domains": {},
        }
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler({}))
        assert "skipped" not in result

    def test_handles_invalid_updated_at_gracefully(self):
        profiles = {
            "updatedAt": "not-a-date",
            "domains": {"d": {}},
        }
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler({}))
        # Should not skip (exception in date parsing is caught)
        assert "skipped" not in result

    def test_does_not_skip_when_no_updated_at(self):
        profiles = {"domains": {"d": {}}}
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ),
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            result = asyncio.run(handler({}))
        assert "skipped" not in result

    def test_passes_target_domain(self):
        with (
            patch(
                "mcp_server.handlers.rebuild_profiles.load_profiles", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_all_memories",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.discover_conversations",
                return_value=[],
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.group_by_project", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.load_brain_index", return_value={}
            ),
            patch(
                "mcp_server.handlers.rebuild_profiles.build_domain_profiles",
                return_value={"domains": {}},
            ) as mock_build,
            patch("mcp_server.handlers.rebuild_profiles.save_profiles"),
        ):
            asyncio.run(handler({"domain": "my-domain", "force": True}))
        assert mock_build.call_args[1]["target_domain"] == "my-domain"
