"""Centralized path constants for all filesystem locations.

All paths are absolute, derived from the Claude configuration root plus
constants. No I/O operations — only path construction.

Unset (the default for every production install), behavior is unchanged:
the root stays ``~/.claude``.

source: ADR-0514"""

from __future__ import annotations

import os
from pathlib import Path

_CLAUDE_DIR_OVERRIDE = os.environ.get("CORTEX_CLAUDE_DIR", "").strip()

CLAUDE_DIR = (
    Path(_CLAUDE_DIR_OVERRIDE).expanduser()
    if _CLAUDE_DIR_OVERRIDE
    else Path.home() / ".claude"
)
METHODOLOGY_DIR = CLAUDE_DIR / "methodology"
PROFILES_PATH = METHODOLOGY_DIR / "profiles.json"
SESSION_LOG_PATH = METHODOLOGY_DIR / "session-log.json"
BRAIN_INDEX_PATH = CLAUDE_DIR / "brain-index.json"
MCP_CONNECTIONS_PATH = METHODOLOGY_DIR / "mcp-connections.json"
WIKI_ROOT = METHODOLOGY_DIR / "wiki"
