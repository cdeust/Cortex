"""Tests for mcp_server.infrastructure.profile_store — ported from profile-store.test.js."""

from unittest.mock import patch
from datetime import datetime

from mcp_server.infrastructure.profile_store import (
    load_profiles,
    save_profiles,
    empty_profiles,
)


class TestLoadProfiles:
    def test_returns_valid_v2_structure(self):
        profiles = load_profiles()
        assert profiles is not None
        assert profiles.get("version", 0) >= 2 or "domains" in profiles
        assert isinstance(profiles.get("domains", {}), dict)

    def test_empty_profiles_structure(self):
        p = empty_profiles()
        assert p["version"] == 2
        assert p["updatedAt"] is None
        assert p["globalStyle"] is None
        assert p["domains"] == {}


class TestSaveProfiles:
    def test_saves_without_error(self, tmp_path):
        path = tmp_path / "profiles.json"
        with patch("mcp_server.infrastructure.profile_store.PROFILES_PATH", path):
            profiles = empty_profiles()
            save_profiles(profiles)
            assert profiles["updatedAt"] is not None
            # Verify it's a valid ISO date
            datetime.fromisoformat(profiles["updatedAt"].replace("Z", "+00:00"))
