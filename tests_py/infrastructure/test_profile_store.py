"""Tests for mcp_server.infrastructure.profile_store — ported from profile-store.test.js.

Updated for D5 per-domain split: save_profiles now splits into per-domain
files + index, so tests that patch PROFILES_PATH must also patch the
per-domain directory and the index path.
"""

from unittest.mock import patch
from datetime import datetime

from mcp_server.infrastructure.profile_store import (
    load_profiles,
    save_profiles,
    empty_profiles,
)


class TestLoadProfiles:
    def test_returns_valid_v2_structure(self, tmp_path):
        # D5: sandbox to tmp_path so load_profiles doesn't trigger a real
        # migration of the user's profiles.json — pre-existing test hygiene
        # gap made unsafe by the migration step.
        methodology = tmp_path / "methodology"
        methodology.mkdir()
        with (
            patch(
                "mcp_server.infrastructure.profile_store.PROFILES_PATH",
                methodology / "profiles.json",
            ),
            patch(
                "mcp_server.infrastructure.profile_store.DOMAINS_DIR",
                methodology / "domains",
            ),
            patch(
                "mcp_server.infrastructure.profile_store.INDEX_PATH",
                methodology / "index.json",
            ),
            patch(
                "mcp_server.infrastructure.profile_store.METHODOLOGY_DIR",
                methodology,
            ),
            patch(
                "mcp_server.infrastructure.profile_store.LEGACY_BACKUP_PATH",
                methodology / "profiles.json.v1_backup",
            ),
        ):
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
        # D5: save_profiles now splits into per-domain files + index, so
        # every filesystem target must be redirected at tmp_path.
        methodology = tmp_path / "methodology"
        methodology.mkdir()
        with (
            patch(
                "mcp_server.infrastructure.profile_store.PROFILES_PATH",
                methodology / "profiles.json",
            ),
            patch(
                "mcp_server.infrastructure.profile_store.DOMAINS_DIR",
                methodology / "domains",
            ),
            patch(
                "mcp_server.infrastructure.profile_store.INDEX_PATH",
                methodology / "index.json",
            ),
            patch(
                "mcp_server.infrastructure.profile_store.METHODOLOGY_DIR",
                methodology,
            ),
            patch(
                "mcp_server.infrastructure.profile_store.LEGACY_BACKUP_PATH",
                methodology / "profiles.json.v1_backup",
            ),
        ):
            profiles = empty_profiles()
            save_profiles(profiles)
            assert profiles["updatedAt"] is not None
            # Verify it's a valid ISO date
            datetime.fromisoformat(profiles["updatedAt"].replace("Z", "+00:00"))
            # Index file was written.
            assert (methodology / "index.json").exists()
