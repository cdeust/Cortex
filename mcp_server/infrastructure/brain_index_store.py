"""Persistence layer for the brain index (cross-reference graph).

- load_brain_index always returns a valid structure (never None)
"""

from __future__ import annotations

from mcp_server.infrastructure.config import BRAIN_INDEX_PATH
from mcp_server.infrastructure.file_io import read_json


def load_brain_index() -> dict:
    """Load the brain index from disk."""
    return read_json(BRAIN_INDEX_PATH) or {
        "version": 1,
        "updatedAt": None,
        "memories": {},
        "conversations": {},
        "threads": {},
    }
