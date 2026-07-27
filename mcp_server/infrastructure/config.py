"""Centralized path constants for all filesystem locations.

All paths are absolute, derived from the Claude configuration root plus
constants. No I/O operations — only path construction.

The root is overridable via ``CORTEX_CLAUDE_DIR``. Every real-data path in
Cortex — the SQLite store, the wiki tree, profiles, the session log —
derives from it, so that single variable is the one seam a test session (or
any sandboxed run) needs in order to bind to a throwaway tree instead of the
operator's real ``~/.claude``.

source: incident 2026-07-28 (issue #219). Without this seam the test suite
had no way to redirect the wiki root: ``consolidate.handler()`` calls
``write_dashboards(WIKI_ROOT)``, which walked the developer's real wiki
(16,234 files — the reported "suite hangs at 58%") and wrote generated
dashboards into ``~/.claude/methodology/wiki/_dashboards/``. Patching each
derived constant per test is the throw-site fix; the root is here.

Unset (the default for every production install), behavior is unchanged:
the root stays ``~/.claude``.
"""

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
