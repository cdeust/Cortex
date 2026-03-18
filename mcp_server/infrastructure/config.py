"""Centralized path constants for all filesystem locations.

All paths are absolute, derived from os.path.expanduser("~") + constants.
No I/O operations — only path construction.
"""

from __future__ import annotations

from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
METHODOLOGY_DIR = CLAUDE_DIR / "methodology"
PROFILES_PATH = METHODOLOGY_DIR / "profiles.json"
SESSION_LOG_PATH = METHODOLOGY_DIR / "session-log.json"
BRAIN_INDEX_PATH = CLAUDE_DIR / "brain-index.json"
MCP_CONNECTIONS_PATH = METHODOLOGY_DIR / "mcp-connections.json"
