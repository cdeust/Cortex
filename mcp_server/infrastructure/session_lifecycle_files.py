"""Reject corrupt lifecycle state before acknowledging durable jobs.

source: ADR-1084
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_server.infrastructure import profile_store, session_store


def _object_if_present(path: Path) -> dict | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Lifecycle state must be a JSON object: {path}")
    return value


def validate_lifecycle_files() -> None:
    """Absence is a cold start; malformed existing state must stop replay.

    source: ADR-1084
    """
    log = _object_if_present(session_store.SESSION_LOG_PATH)
    if log is not None:
        rows = log.get("sessions", [])
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError("Lifecycle sessions must be a list of objects")
    _object_if_present(profile_store.PROFILES_PATH)
    _object_if_present(profile_store.INDEX_PATH)
    for path in profile_store.DOMAINS_DIR.glob("*.json"):
        _object_if_present(path)
