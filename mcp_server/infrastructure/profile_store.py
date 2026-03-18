"""Persistence layer for methodology profiles.

- load_profiles always returns a valid ProfilesV2 object
- save_profiles sets updatedAt before writing
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcp_server.infrastructure.config import PROFILES_PATH
from mcp_server.infrastructure.file_io import read_json, write_json


def empty_profiles() -> dict:
    return {"version": 2, "updatedAt": None, "globalStyle": None, "domains": {}}


def load_profiles() -> dict:
    """Load profiles from disk, or return empty v2 structure."""
    return read_json(PROFILES_PATH) or empty_profiles()


def save_profiles(profiles: dict) -> None:
    """Save profiles to disk, updating the timestamp."""
    profiles["updatedAt"] = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    write_json(PROFILES_PATH, profiles)
